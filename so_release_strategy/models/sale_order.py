# -*- coding: utf-8 -*-
import json
from contextlib import contextmanager

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_round

from .mail_activity import RELEASE_CTX

# Context keys
SKIP_CHECK_CTX = 'so_release_skip_lock_check'
DEFER_CHECK_CTX = 'so_release_defer_lock_check'

# Transaction-scoped state kept in env.cr.cache (v19: env.transaction uses __slots__)
WRITE_DEPTH_KEY = 'so_release_write_depth'
CHECKING_KEY = 'so_release_checking'

RELEASE_STATES = [
    ('draft', 'Not Submitted'),
    ('pending', 'Waiting Approval'),
    ('approved', 'Released'),
    ('rejected', 'Rejected'),
    ('not_required', 'No Approval Needed'),
]

# sale.order fields that can never be locked: workflow, technical and values
# that legitimately evolve after confirmation. team_id and company_id are
# always watched (they decide the strategy), so they are not offered either.
NON_LOCKABLE_FIELDS = {
    'id', 'display_name', 'state', 'name', 'create_uid', 'create_date',
    'write_uid', 'write_date', '__last_update', 'company_id', 'team_id',
    'user_id', 'date_order', 'currency_rate', 'invoice_status', 'invoice_ids',
    'invoice_count', 'signature', 'signed_by', 'signed_on', 'reference',
    'transaction_ids', 'authorized_transaction_ids', 'procurement_group_id',
    'picking_ids', 'delivery_count', 'effective_date', 'expected_date',
    'show_update_pricelist', 'show_update_fpos', 'recompute_delivery_price',
    'tax_totals', 'tax_country_id', 'country_code', 'amount_to_invoice',
    'amount_invoiced', 'amount_undiscounted', 'locked',
    # v19: technical, written by Odoo when an email is queued
    'pending_email_template_id',
}
# Computed totals that are still meaningful to freeze.
LOCKABLE_COMPUTED_FIELDS = {'amount_untaxed', 'amount_tax', 'amount_total'}
# Always part of the snapshot: changing them changes the applicable strategy.
ALWAYS_WATCHED_FIELDS = ('team_id', 'company_id')
NON_LOCKABLE_PREFIXES = (
    'message_', 'activity_', 'release_', 'so_release_', 'website_', 'access_',
    'cart_', 'delivery_',
)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    release_required = fields.Boolean(
        compute='_compute_release_required',
        help='Technical: the company enforces sales release strategies.')
    team_release_strategy_id = fields.Many2one(
        related='team_id.so_release_strategy_id', string='Team Release Strategy')
    release_strategy_id = fields.Many2one(
        'so.release.strategy', string='Applied Release Strategy',
        ondelete='restrict', copy=False, readonly=True, tracking=True, index=True,
        help='Release strategy of the sales team, recorded when the order was '
             'evaluated for approval.')
    release_state = fields.Selection(
        RELEASE_STATES, string='Release Status', default='draft', required=True,
        copy=False, tracking=True, index=True)
    release_needed = fields.Boolean(
        compute='_compute_release_needed',
        help='Technical: the order amount is within the range of an approval '
             'rule of the sales team strategy, so confirming it requests the '
             'approvals.')
    so_release_team_ids = fields.Many2many(
        'crm.team', compute='_compute_so_release_team_ids',
        help='Technical: sales teams the salesperson can sell for.')
    release_line_ids = fields.One2many(
        'sale.order.release.line', 'order_id', string='Release Approvals',
        copy=False)
    release_currency_id = fields.Many2one(
        related='company_id.currency_id', string='Company Currency')
    release_amount_company = fields.Monetary(
        string='Release Amount', currency_field='release_currency_id',
        copy=False, readonly=True,
        help='Order amount converted to the company currency when the order '
             'was evaluated; used to select the approval rules.')
    release_submit_date = fields.Datetime(
        string='Submitted On', copy=False, readonly=True)
    release_approval_date = fields.Datetime(
        string='Released On', copy=False, readonly=True)
    release_bypassed = fields.Boolean(
        string='Approval Bypassed', copy=False, readonly=True)
    release_bypass_user_id = fields.Many2one(
        'res.users', string='Bypassed By', copy=False, readonly=True)
    release_bypass_reason = fields.Text(
        string='Bypass Reason', copy=False, readonly=True)
    release_reset_count = fields.Integer(
        string='Release Resets', copy=False, readonly=True)
    release_snapshot = fields.Text(copy=False, readonly=True, groups='base.group_system')
    release_pending_user_ids = fields.Many2many(
        'res.users', string='Waiting For', compute='_compute_release_pending_user_ids')
    release_can_approve = fields.Boolean(compute='_compute_release_permissions')
    release_can_reset = fields.Boolean(compute='_compute_release_permissions')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('company_id.so_release_strategy_enabled')
    def _compute_release_required(self):
        for order in self:
            order.release_required = order.company_id.so_release_strategy_enabled

    @api.depends('company_id', 'team_id', 'team_id.so_release_strategy_id',
                 'amount_total', 'amount_untaxed', 'currency_id', 'date_order',
                 'state', 'release_state')
    def _compute_release_needed(self):
        for order in self:
            needed = False
            if (order.company_id.so_release_strategy_enabled
                    and order.state in ('draft', 'sent')
                    and order.release_state != 'approved'):
                strategy = order.team_id.so_release_strategy_id
                if (not strategy or not strategy.active
                        or strategy.company_id != order.company_id):
                    # misconfiguration: confirmation goes through the release
                    # checks, which explain what is missing
                    needed = True
                else:
                    amount = order._so_release_compute_amount(strategy)
                    needed = bool(strategy._get_applicable_rules(amount))
            order.release_needed = needed

    @api.depends('user_id', 'company_id')
    def _compute_so_release_team_ids(self):
        Team = self.env['crm.team']
        for order in self:
            domain = [('company_id', 'in', [False, order.company_id.id])]
            if order.company_id.so_release_strategy_enabled and order.user_id:
                domain += ['|', ('user_id', '=', order.user_id.id),
                           ('member_ids', 'in', order.user_id.ids)]
            order.so_release_team_ids = Team.search(domain)

    @api.depends('release_line_ids.state')
    def _compute_release_pending_user_ids(self):
        for order in self:
            users = self.env['res.users']
            for line in order.release_line_ids.filtered(lambda l: l.state == 'pending'):
                users |= line._get_approver_users()
            order.release_pending_user_ids = users

    @api.depends_context('uid')
    @api.depends('release_state', 'release_line_ids.state', 'user_id', 'state')
    def _compute_release_permissions(self):
        user = self.env.user
        is_manager = self._so_release_is_manager()
        for order in self:
            order.release_can_approve = bool(
                order.release_state == 'pending'
                and order._so_release_lines_for_user(user))
            order.release_can_reset = bool(
                order.release_state in ('pending', 'approved', 'rejected')
                and order.state in ('draft', 'sent')
                and (is_manager or order.user_id == user))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _so_release_is_required(self):
        self.ensure_one()
        return bool(self.company_id.so_release_strategy_enabled)

    def _so_release_is_manager(self):
        return (self.env.user.has_group('sales_team.group_sale_manager')
                or self.env.user.has_group('so_release_strategy.group_so_release_supervisor'))

    def _so_release_skip_membership_check(self):
        """The salesperson/team membership rule protects interactive backend
        work. Website and portal flows (public/portal users) and system
        operations (superuser, e.g. crons) are not blocked by it; release
        approvals still apply to them."""
        return self.env.su or self.env.user.share

    def _so_release_lines_for_user(self, user):
        self.ensure_one()
        return self.release_line_ids.filtered(
            lambda l: l.state == 'pending' and user in l._get_approver_users())

    def _so_release_check_team_salesperson(self):
        """Sales team mandatory, salesperson mandatory, and the salesperson
        must belong to the team (member or team leader)."""
        for order in self:
            if not order._so_release_is_required() or order.state == 'cancel':
                continue
            if not order.team_id:
                raise ValidationError(_(
                    'A sales team is mandatory on %s: its release strategy '
                    'decides the approvals of the order.', order.display_name))
            if order._so_release_skip_membership_check():
                continue
            if not order.user_id:
                raise ValidationError(_(
                    'A salesperson is mandatory on %s.', order.display_name))
            if not order.team_id._so_release_is_member(order.user_id):
                raise ValidationError(_(
                    'Salesperson %(user)s is not a member of the sales team '
                    '%(team)s. Choose one of their teams, or add them to the '
                    'team first.', user=order.user_id.name,
                    team=order.team_id.display_name))

    def _so_release_get_strategy(self):
        """Strategy of the order's sales team (never chosen on the order)."""
        self.ensure_one()
        if not self.team_id:
            raise UserError(_(
                'A sales team is mandatory on %s: its release strategy '
                'decides the approvals of the order.', self.display_name))
        strategy = self.team_id.sudo().so_release_strategy_id
        if not strategy or not strategy.active:
            raise UserError(_(
                'Sales team %(team)s has no active release strategy. Set one on '
                'the team (Sales > Configuration > Sales Teams).',
                team=self.team_id.display_name))
        if strategy.company_id != self.company_id:
            raise UserError(_(
                'The release strategy "%(strategy)s" of sales team %(team)s '
                'belongs to another company than sales order %(order)s.',
                strategy=strategy.name, team=self.team_id.display_name,
                order=self.display_name))
        return strategy.with_env(self.env)

    def _so_release_compute_amount(self, strategy):
        """Order amount normalized to the company currency."""
        self.ensure_one()
        amount = self.amount_untaxed if strategy.amount_basis == 'untaxed' else self.amount_total
        company_currency = self.company_id.currency_id
        if self.currency_id and self.currency_id != company_currency:
            amount = self.currency_id._convert(
                amount, company_currency, self.company_id,
                self.date_order or fields.Date.context_today(self))
        return company_currency.round(amount)

    def _so_release_rules(self):
        """(strategy, amount, applicable rules) of the order's team strategy."""
        self.ensure_one()
        strategy = self._so_release_get_strategy()
        amount = self._so_release_compute_amount(strategy)
        return strategy, amount, strategy._get_applicable_rules(amount)

    def _so_release_holds_operations(self):
        """Confirmed order waiting for (or refused) a new release approval:
        invoicing and new deliveries wait until it is approved again."""
        self.ensure_one()
        return bool(self.state == 'sale' and self._so_release_is_required()
                    and self.release_state in ('pending', 'rejected'))

    def _so_release_check_invoicing(self):
        held = self.filtered(lambda o: o._so_release_holds_operations())
        if held:
            raise UserError(_(
                'Sales order(s) %s are waiting for a new release approval after a '
                'change of locked fields. They can be invoiced once approved again.',
                ', '.join(held.mapped('name'))))

    def _so_release_after_release(self):
        """Hook: confirmed orders whose release is complete again (approved,
        bypassed, no longer needed or feature switched off). Extended by
        so_release_strategy_stock to create the deliveries held meanwhile."""
        return True

    def _so_release_customer_accepted(self):
        self.ensure_one()
        return bool(self.signature) or bool(self.transaction_ids.filtered(
            lambda tx: tx.state in ('authorized', 'done')))

    @api.model
    def _so_release_lockable_field_names(self):
        names = []
        for name, field in self._fields.items():
            if name in NON_LOCKABLE_FIELDS or not field.store:
                continue
            if name.startswith(NON_LOCKABLE_PREFIXES):
                continue
            if field.type == 'binary':
                continue
            if field.type == 'one2many' and name != 'order_line':
                continue
            if field.compute and field.readonly and name not in LOCKABLE_COMPUTED_FIELDS:
                continue
            if field.related:
                continue
            names.append(name)
        return names

    # ----- locked fields snapshot -----
    @staticmethod
    def _so_release_norm(value):
        if isinstance(value, float):
            return float_round(value, precision_digits=6)
        return value

    def _so_release_snapshot_lines(self):
        """Order lines covered by the lock. Lines added by Odoo itself after
        confirmation (down payments, re-invoiced expenses, delivery costs) are
        not part of the approved scope."""
        self.ensure_one()
        has_delivery = 'is_delivery' in self.env['sale.order.line']._fields
        return self.order_line.filtered(
            lambda l: not l.is_downpayment and not l.is_expense
            and not (has_delivery and l.is_delivery))

    def _so_release_field_value(self, field_name):
        field = self._fields[field_name]
        value = self[field_name]
        norm = self._so_release_norm
        if field_name == 'order_line':
            return [
                [line.id, line.display_type or '', line.product_id.id, line.name or '',
                 norm(line.product_uom_qty), line.product_uom_id.id, norm(line.price_unit),
                 norm(line.discount), sorted(line.tax_ids.ids)]  # v19: product_uom_id, tax_ids
                for line in self._so_release_snapshot_lines().sorted('id')
            ]
        if field_name in LOCKABLE_COMPUTED_FIELDS:
            lines = self._so_release_snapshot_lines()
            total = sum(lines.mapped({
                'amount_untaxed': 'price_subtotal',
                'amount_tax': 'price_tax',
                'amount_total': 'price_total',
            }[field_name]))
            return norm(self.currency_id.round(total) if self.currency_id else total)
        if field.type == 'many2one':
            return value.id
        if field.type in ('one2many', 'many2many'):
            return sorted(value.ids)
        if field.type == 'monetary':
            return norm(self.currency_id.round(value) if self.currency_id else value)
        if field.type == 'date':
            return fields.Date.to_string(value) if value else False
        if field.type == 'datetime':
            return fields.Datetime.to_string(value) if value else False
        if field.type in ('html', 'text', 'char'):
            return str(value) if value else False
        if field.type == 'properties':
            return json.dumps(value, sort_keys=True, default=str)
        return norm(value)

    def _so_release_build_snapshot(self):
        self.ensure_one()
        names = set(self.release_strategy_id.sudo().locked_field_ids.mapped('name'))
        names.update(ALWAYS_WATCHED_FIELDS)
        return {name: self._so_release_field_value(name) for name in names
                if name in self._fields}

    def _so_release_store_snapshot(self):
        for order in self:
            snapshot = order._so_release_build_snapshot()
            order.sudo().with_context(**{SKIP_CHECK_CTX: True}).write({
                'release_snapshot': json.dumps(snapshot, sort_keys=True, default=str),
            })

    def _so_release_changed_fields(self):
        """Names of watched fields whose value differs from the snapshot."""
        self.ensure_one()
        if not self.sudo().release_snapshot:
            return []
        # Build the current values first: reading the lines can trigger v19
        # recomputations that write back to them (e.g. _reset_price_unit) and
        # re-enter this check, which may store a fresh snapshot. Reading the
        # stored snapshot afterwards avoids comparing against a stale one.
        current = json.loads(json.dumps(self._so_release_build_snapshot(),
                                        sort_keys=True, default=str))
        raw = self.sudo().release_snapshot
        if not raw or self.release_state not in ('pending', 'approved', 'not_required'):
            return []
        stored = json.loads(raw)
        return [name for name in stored if stored.get(name) != current.get(name)]

    @contextmanager
    def _so_release_write_scope(self):
        """Track nested writes on orders/lines within the transaction.

        Yields True for the outermost write only, so the locked-field check runs
        once, after the ORM has finished the write and its side effects (v19
        recomputations such as _reset_price_unit write back to the lines)."""
        cache = self.env.cr.cache
        depth = cache.get(WRITE_DEPTH_KEY, 0)
        cache[WRITE_DEPTH_KEY] = depth + 1
        try:
            yield depth == 0
        finally:
            cache[WRITE_DEPTH_KEY] = depth

    def _so_release_check_locked_changes(self):
        if self.env.context.get(SKIP_CHECK_CTX) or self.env.context.get(DEFER_CHECK_CTX):
            return
        cache = self.env.cr.cache
        if cache.get(CHECKING_KEY):
            # re-entered from a recomputation triggered by the running check
            return
        orders = self.exists().filtered(
            lambda o: o.release_state in ('pending', 'approved', 'not_required')
            and o.state != 'cancel' and o._so_release_is_required()
            and o.sudo().release_snapshot)
        if not orders:
            return
        cache[CHECKING_KEY] = True
        try:
            orders._so_release_apply_locked_changes()
        finally:
            cache[CHECKING_KEY] = False

    def _so_release_apply_locked_changes(self):
        for order in self:
            changed = order._so_release_changed_fields()
            if not changed:
                continue
            labels = [order._fields[n].get_description(self.env)['string'] for n in changed]
            order._so_release_on_locked_change(labels)

    def _so_release_on_locked_change(self, labels):
        """A watched field changed: re-evaluate the order against the strategy
        of its (possibly new) sales team."""
        self.ensure_one()
        _strategy, _amount, rules = self._so_release_rules()
        confirmed = self.state == 'sale'
        policy = self.release_strategy_id.lock_confirmed_policy
        if confirmed and policy == 'block' and (self.release_state != 'not_required' or rules):
            raise UserError(_(
                'Sales order %(order)s is confirmed. The following fields are '
                'locked by its release strategy: %(fields)s',
                order=self.name, fields=', '.join(labels)))
        if self.release_state == 'not_required' and not rules:
            # still below every approval rule: refresh the reference values
            self._so_release_mark_not_required()
            return
        self._so_release_reset(changed_labels=labels, resubmit=bool(rules))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    def write(self, vals):
        if self.env.context.get(SKIP_CHECK_CTX):
            return super().write(vals)
        with self._so_release_write_scope() as outermost:
            res = super(SaleOrder, self.with_context(**{DEFER_CHECK_CTX: True})).write(vals)
        if outermost:
            self._so_release_check_locked_changes()
        return res

    @api.constrains('team_id', 'user_id', 'company_id')
    def _check_so_release_team_salesperson(self):
        if self._so_release_skip_membership_check():
            return
        self._so_release_check_team_salesperson()

    # ------------------------------------------------------------------
    # Native workflow integration
    # ------------------------------------------------------------------
    def action_confirm(self):
        """Orders under release strategy are evaluated against the strategy of
        their sales team: when an approval rule covers the amount, the
        approvals are requested instead of confirming the order."""
        candidates = self.filtered(
            lambda o: o.state in ('draft', 'sent') and o._so_release_is_required())
        waiting = candidates.filtered(lambda o: o.release_state == 'pending')
        if waiting:
            raise UserError(_(
                'Sales order(s) %s are waiting for release approval and cannot '
                'be confirmed yet.', ', '.join(waiting.mapped('name'))))
        to_check = candidates.filtered(lambda o: o.release_state != 'approved')
        to_submit = self.env['sale.order']
        for order in to_check:
            order._so_release_check_team_salesperson()
            if order._so_release_rules()[2]:
                # v18: same checks as a confirmation (e.g. lines without
                # product) before approvers are asked
                error_msg = order._confirmation_error_message()
                if error_msg:
                    raise UserError(error_msg)
                to_submit |= order
        if to_submit:
            to_submit.order_line._validate_analytic_distribution()
            to_submit._so_release_submit()
            for order in to_submit.filtered(
                    lambda o: o.state in ('draft', 'sent') and o._so_release_customer_accepted()):
                order.sudo().message_post(body=_(
                    'The customer accepted the quotation online. The order will '
                    'be confirmed once its release approval is complete.'))
        to_confirm = self - to_submit
        if not to_confirm:
            return True
        res = super(SaleOrder, to_confirm.with_context(**{SKIP_CHECK_CTX: True})).action_confirm()
        released = to_confirm.filtered(
            lambda o: o._so_release_is_required() and o.state == 'sale')
        (released & to_check)._so_release_mark_not_required()
        (released - to_check)._so_release_store_snapshot()
        released._so_release_close_salesperson_activity()
        return res

    def _send_order_confirmation_mail(self):
        # orders held for release approval are not confirmed: no mail yet
        # (v17 calls this from action_confirm() when send_email is set)
        held = self.filtered(
            lambda o: o._so_release_is_required() and o.state != 'sale')
        return super(SaleOrder, self - held)._send_order_confirmation_mail()

    def _create_invoices(self, grouped=False, final=False, date=None):
        held = self.filtered(lambda o: o._so_release_holds_operations())
        if held and self.env.context.get('raise_if_nothing_to_invoice', True):
            self._so_release_check_invoicing()
        # automated invoicing (e.g. after an online payment) skips held orders
        return super(SaleOrder, self - held)._create_invoices(
            grouped=grouped, final=final, date=date)

    def _action_cancel(self):
        res = super()._action_cancel()
        self.filtered(lambda o: o.state == 'cancel')._so_release_clear()
        return res

    # ------------------------------------------------------------------
    # Release engine
    # ------------------------------------------------------------------
    def _so_release_prepare_lines(self, strategy, amount):
        self.ensure_one()
        return [{
            'order_id': self.id,
            'rule_id': rule.id,
            'sequence': rule.sequence,
            'role': rule.role,
            'approver_type': rule.approver_type,
            'user_id': rule.user_id.id,
            'group_id': rule.group_id.id,
            'approver_display': rule._get_approver_display(),
            'min_amount': rule.min_amount,
            'max_amount': rule.max_amount,
            'state': 'waiting',
        } for rule in strategy._get_applicable_rules(amount)]

    def _so_release_clear(self):
        """Drop approval lines/activities and go back to 'Not Submitted'."""
        for order in self.sudo().with_context(**{SKIP_CHECK_CTX: True, RELEASE_CTX: True}):
            order.release_line_ids.unlink()
            order.write({
                'release_state': 'draft',
                'release_amount_company': 0.0,
                'release_submit_date': False,
                'release_approval_date': False,
                'release_bypassed': False,
                'release_bypass_user_id': False,
                'release_bypass_reason': False,
                'release_snapshot': False,
            })
            order._so_release_close_salesperson_activity()

    def _so_release_mark_not_required(self):
        """Confirmed without approval: record the strategy, the amount and the
        reference values so that later changes are re-evaluated."""
        for order in self:
            strategy = order._so_release_get_strategy()
            order.sudo().with_context(**{SKIP_CHECK_CTX: True}).write({
                'release_state': 'not_required',
                'release_strategy_id': strategy.id,
                'release_amount_company': order._so_release_compute_amount(strategy),
            })
            order._so_release_store_snapshot()

    def _so_release_submit(self):
        """Generate the approval lines and start the first stage."""
        for order in self:
            if order.state == 'cancel':
                raise UserError(_('Cancelled order %s cannot be submitted.', order.name))
            strategy = order._so_release_get_strategy()
            sudo_order = order.sudo().with_context(**{SKIP_CHECK_CTX: True, RELEASE_CTX: True})
            amount = order._so_release_compute_amount(strategy)
            sudo_order.release_line_ids.unlink()
            sudo_order.write({
                'release_strategy_id': strategy.id,
                'release_state': 'pending',
                'release_amount_company': amount,
                'release_submit_date': fields.Datetime.now(),
                'release_approval_date': False,
                'release_bypassed': False,
                'release_bypass_user_id': False,
                'release_bypass_reason': False,
            })
            sudo_order.env['sale.order.release.line'].create(
                order._so_release_prepare_lines(strategy, amount))
            order._so_release_store_snapshot()
            if not sudo_order.release_line_ids:
                sudo_order.message_post(body=_(
                    'No approval rule of release strategy "%s" applies to this '
                    'amount: the order is released automatically.', strategy.name))
            else:
                sudo_order.message_post(body=_(
                    'Order submitted for release approval (%(strategy)s, sales '
                    'team %(team)s).', strategy=strategy.name,
                    team=order.team_id.display_name))
            sudo_order._so_release_activate_next_stage()
        return True

    def _so_release_activate_next_stage(self):
        for order in self:
            lines = order.release_line_ids
            if lines.filtered(lambda l: l.state == 'pending'):
                continue
            waiting = lines.filtered(lambda l: l.state == 'waiting')
            if not waiting:
                order._so_release_finalize()
                continue
            stage = min(waiting.mapped('sequence'))
            waiting.filtered(lambda l: l.sequence == stage)._activate()

    def _so_release_finalize(self):
        """All stages approved (or bypassed): apply the post-approval action."""
        for order in self.sudo().with_context(**{SKIP_CHECK_CTX: True, RELEASE_CTX: True}):
            order.write({
                'release_state': 'approved',
                'release_approval_date': fields.Datetime.now(),
            })
            strategy = order.release_strategy_id
            if order.state == 'sale':
                order._so_release_store_snapshot()
                order.message_post(body=_('Release strategy approved again.'))
                order._so_release_notify_salesperson(_('The order was approved again.'))
                order._so_release_after_release()
                continue
            if strategy.post_approval_action == 'auto_confirm':
                # same as the portal / payment flows: the customer already
                # accepted online, so action_confirm() sends the mail
                order.with_context(
                    send_email=order._so_release_customer_accepted()).action_confirm()
                order.message_post(body=_('Order released and confirmed automatically.'))
            else:
                order.message_post(body=_(
                    'Order released. Waiting for the salesperson to confirm it.'))
                order._so_release_notify_salesperson(
                    _('Released: please confirm this sales order.'), confirm=True)

    def _so_release_notify_salesperson(self, summary, confirm=False):
        for order in self:
            salesperson = order.user_id
            if not salesperson or not salesperson.active or salesperson.share:
                continue
            xmlid = ('so_release_strategy.mail_activity_type_so_release_confirm'
                     if confirm else 'mail.mail_activity_data_todo')
            order.sudo().activity_schedule(xmlid, summary=summary, user_id=salesperson.id)

    def _so_release_close_salesperson_activity(self):
        self.sudo().activity_unlink(['so_release_strategy.mail_activity_type_so_release_confirm'])

    def _so_release_reset(self, reason=False, changed_labels=None, resubmit=False):
        """Clear every approval; optionally resubmit and re-notify approvers."""
        for order in self:
            sudo_order = order.sudo().with_context(**{SKIP_CHECK_CTX: True, RELEASE_CTX: True})
            notified = self.env['res.users']
            for line in order.release_line_ids:
                notified |= line._get_approver_users()
            was_confirmed = order.state == 'sale'
            was_held = was_confirmed and order.release_state in ('pending', 'rejected')
            sudo_order._so_release_clear()
            sudo_order.release_reset_count += 1
            if changed_labels:
                body = Markup('<p>%s</p><ul>%s</ul>') % (
                    _('Release strategy reset: the following locked fields were modified. '
                      'Previous approvals have been cleared.'),
                    Markup('').join(Markup('<li>%s</li>') % escape(l) for l in changed_labels))
            else:
                body = Markup('<p>%s</p>') % _('Release strategy reset by %s.', self.env.user.name)
                if reason:
                    body += Markup('<p>%s</p>') % reason
            if resubmit:
                # a confirmed order keeps its state and only requests a new approval
                sudo_order._so_release_submit()
            elif was_confirmed:
                sudo_order._so_release_mark_not_required()
                if was_held:
                    sudo_order._so_release_after_release()
            elif changed_labels:
                body += Markup('<p>%s</p>') % _(
                    'No approval rule applies to the new amount anymore: the '
                    'order can be confirmed directly.')
            for line in sudo_order.release_line_ids:
                notified |= line._get_approver_users()
            sudo_order.message_post(
                body=body,
                partner_ids=notified.partner_id.ids,
                subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    # User actions (called by buttons / wizard)
    # ------------------------------------------------------------------
    @api.model
    def _so_release_on_feature_disabled(self, companies):
        """Release strategies switched off: cancel the approvals still pending
        (approval history is kept) so that no order stays blocked."""
        orders = self.sudo().search([
            ('company_id', 'in', companies.ids), ('release_state', '=', 'pending')])
        # confirmed orders held (pending or rejected re-approval) are released too
        confirmed = self.sudo().search([
            ('company_id', 'in', companies.ids), ('state', '=', 'sale'),
            ('release_state', 'in', ('pending', 'rejected'))])
        for order in orders.with_context(**{SKIP_CHECK_CTX: True, RELEASE_CTX: True}):
            order.release_line_ids._cancel()
            order.write({'release_state': 'draft', 'release_snapshot': False})
            order._so_release_close_salesperson_activity()
            order.message_post(body=_(
                'Sales release strategies were switched off for %s: the pending '
                'release approval was cancelled.', order.company_id.name))
        confirmed._so_release_after_release()
        return orders

    def _so_release_open_wizard(self, action):
        self.ensure_one()
        titles = {
            'approve': _('Approve Release'),
            'reject': _('Reject Release'),
            'bypass': _('Bypass Release Approval'),
            'reset': _('Reset Release Strategy'),
        }
        return {
            'type': 'ir.actions.act_window',
            'name': titles[action],
            'res_model': 'so.release.action.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id, 'default_action': action},
        }

    def action_release_submit(self):
        to_submit = self.env['sale.order']
        for order in self:
            if not order._so_release_is_required():
                raise UserError(_('Release strategies are not enabled for %s.',
                                  order.company_id.name))
            resubmit_confirmed = order.state == 'sale' and order.release_state == 'rejected'
            if order.state not in ('draft', 'sent') and not resubmit_confirmed:
                raise UserError(_('Only quotations can be submitted for approval.'))
            if order.release_state not in ('draft', 'rejected'):
                raise UserError(_('%s is already submitted.', order.name))
            order._so_release_check_team_salesperson()
            if not order._so_release_rules()[2]:
                if resubmit_confirmed:
                    order._so_release_mark_not_required()
                    order._so_release_after_release()
                    continue
                raise UserError(_(
                    'No approval rule of the sales team strategy applies to the '
                    'amount of %s: it can be confirmed directly.', order.name))
            if not resubmit_confirmed:
                error_msg = order._confirmation_error_message()
                if error_msg:
                    raise UserError(error_msg)
            order.order_line._validate_analytic_distribution()
            to_submit |= order
        to_submit._so_release_submit()
        return True

    def action_release_approve(self):
        return self._so_release_open_wizard('approve')

    def action_release_reject(self):
        return self._so_release_open_wizard('reject')

    def action_release_bypass(self):
        return self._so_release_open_wizard('bypass')

    def action_release_reset(self):
        return self._so_release_open_wizard('reset')

    def _so_release_approve(self, notes=False):
        user = self.env.user
        for order in self:
            if order.release_state != 'pending':
                raise UserError(_('%s is not waiting for release approval.', order.name))
            lines = order._so_release_lines_for_user(user)
            if not lines:
                raise AccessError(_(
                    'You are not an approver of the current release stage of %s.',
                    order.name))
            sudo_lines = lines.sudo().with_context(**{RELEASE_CTX: True, SKIP_CHECK_CTX: True})
            sudo_lines._mark_approved(user, notes)
            sudo_order = order.sudo().with_context(**{RELEASE_CTX: True, SKIP_CHECK_CTX: True})
            sudo_order._so_release_activate_next_stage()
        return True

    def _so_release_reject(self, notes):
        if not notes:
            raise UserError(_('Please give a reason for the rejection.'))
        user = self.env.user
        for order in self:
            if order.release_state != 'pending':
                raise UserError(_('%s is not waiting for release approval.', order.name))
            lines = order._so_release_lines_for_user(user)
            if not lines:
                raise AccessError(_(
                    'You are not an approver of the current release stage of %s.',
                    order.name))
            sudo_order = order.sudo().with_context(**{RELEASE_CTX: True, SKIP_CHECK_CTX: True})
            lines.sudo().with_context(**{RELEASE_CTX: True})._mark_rejected(user, notes)
            (sudo_order.release_line_ids - lines)._cancel()
            sudo_order.write({'release_state': 'rejected', 'release_snapshot': False})
            sudo_order.message_post(body=Markup('<p>%s</p><p>%s</p>') % (
                _('Release rejected by %s.', user.name), notes))
            sudo_order._so_release_notify_salesperson(_('Release rejected: %s', notes))
        return True

    def _so_release_bypass(self, notes):
        if not self.env.user.has_group('so_release_strategy.group_so_release_supervisor'):
            raise AccessError(_('Only release supervisors can bypass a release strategy.'))
        if not notes:
            raise UserError(_('Please give a reason for the bypass.'))
        user = self.env.user
        for order in self:
            if order.release_state not in ('pending', 'rejected', 'draft'):
                raise UserError(_('%s is already released.', order.name))
            if order.release_state != 'pending':
                order._so_release_check_team_salesperson()
                order._so_release_submit()
                if order.release_state == 'approved':
                    continue
            sudo_order = order.sudo().with_context(**{RELEASE_CTX: True, SKIP_CHECK_CTX: True})
            sudo_order.release_line_ids.filtered(
                lambda l: l.state in ('waiting', 'pending'))._mark_approved(user, notes, bypass=True)
            sudo_order.write({
                'release_bypassed': True,
                'release_bypass_user_id': user.id,
                'release_bypass_reason': notes,
            })
            sudo_order.message_post(body=Markup('<p>%s</p><p>%s</p>') % (
                _('Release approval bypassed by supervisor %s.', user.name), notes))
            sudo_order._so_release_finalize()
        return True

    def _so_release_manual_reset(self, notes=False):
        for order in self:
            if not order.release_can_reset:
                raise AccessError(_(
                    'Only the salesperson, sales managers or release supervisors '
                    'can reset the release strategy of %s.', order.name))
            order._so_release_reset(reason=notes, resubmit=False)
        return True


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _so_release_check_orders(self, orders):
        ctx = self.env.context
        if ctx.get(SKIP_CHECK_CTX) or ctx.get(DEFER_CHECK_CTX):
            return
        orders._so_release_check_locked_changes()

    @api.model_create_multi
    def create(self, vals_list):
        with self.env['sale.order']._so_release_write_scope() as outermost:
            lines = super().create(vals_list)
        if outermost:
            self._so_release_check_orders(lines.order_id)
        return lines

    def write(self, vals):
        with self.env['sale.order']._so_release_write_scope() as outermost:
            res = super().write(vals)
        if outermost:
            self._so_release_check_orders(self.order_id)
        return res

    def unlink(self):
        orders = self.order_id
        with self.env['sale.order']._so_release_write_scope() as outermost:
            res = super().unlink()
        if outermost:
            self._so_release_check_orders(orders)
        return res
