# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import new_test_user

from .common import SIGNATURE, SoReleaseCommon


@tagged('post_install', '-at_install')
class TestSoReleaseStrategy(SoReleaseCommon):

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------
    def test_00_disabled_keeps_native_flow(self):
        self.company.so_release_strategy_enabled = False
        so = self._create_so(price=50000, user=self.salesperson, team=self.team_b)
        self.assertFalse(so.release_required)
        self.assertFalse(so.release_needed)
        so.with_user(self.salesperson).action_confirm()
        self.assertEqual(so.state, 'sale')
        self.assertEqual(so.release_state, 'draft')
        self.assertFalse(so.release_line_ids)

    def test_01_activation_requires_team_strategies(self):
        self.company.so_release_strategy_enabled = False
        orphan = self.env['crm.team'].create({'name': 'No Strategy Team',
                                              'company_id': self.company.id})
        with self.assertRaises(ValidationError):
            self.company.so_release_strategy_enabled = True
        orphan.so_release_strategy_id = self.strategy
        self.company.so_release_strategy_enabled = True
        self.assertTrue(orphan.so_release_required)

    def test_02_team_strategy_protected(self):
        with self.assertRaises(ValidationError):
            self.team_a.so_release_strategy_id = False
        with self.assertRaises(ValidationError):
            self.strategy_b.active = False
        self.assertEqual(self.strategy.team_count, len(self.strategy.team_ids))
        self.assertIn(self.team_a, self.strategy.team_ids)

    def test_03_team_and_salesperson_enforced(self):
        # salesperson is not a member of team B
        with self.assertRaises(ValidationError):
            self._create_so(team=self.team_b)
        # team mandatory
        with self.assertRaises(ValidationError):
            self.env['sale.order'].with_user(self.salesperson).create({
                'partner_id': self.partner.id, 'user_id': self.salesperson.id,
                'team_id': False})
        # salesperson mandatory for backend users
        with self.assertRaises(ValidationError):
            self.env['sale.order'].with_user(self.sales_manager).create({
                'partner_id': self.partner.id, 'user_id': False,
                'team_id': self.team_a.id})
        # leaders belong to their team
        so_lead = self._create_so(user=self.team_lead, team=self.team_a)
        so_c = self._create_so(team=self.team_c)
        self.assertTrue(so_lead and so_c)
        # moving an order to a team of another salesperson is refused
        so = self._create_so()
        with self.assertRaises(ValidationError):
            so.with_user(self.sales_manager).write({'team_id': self.team_b.id})
        with self.assertRaises(ValidationError):
            so.with_user(self.sales_manager).write({'user_id': self.lonely.id})
        # selectable teams follow the salesperson
        self.assertEqual(set(so.so_release_team_ids.ids), {self.team_a.id, self.team_c.id})

    def test_04_rule_constraints(self):
        with self.assertRaises(ValidationError):
            self.env['so.release.strategy.rule'].create({
                'strategy_id': self.strategy.id, 'role': 'Bad', 'approver_type': 'user',
                'user_id': self.manager.id, 'min_amount': 500.0, 'max_amount': 100.0})
        with self.assertRaises(ValidationError):
            self.env['so.release.strategy.rule'].create({
                'strategy_id': self.strategy.id, 'role': 'No group', 'approver_type': 'group'})
        state_field = self.env['ir.model.fields']._get('sale.order', 'state')
        with self.assertRaises(ValidationError):
            self.strategy.locked_field_ids = [Command.link(state_field.id)]
        self.assertIn(self.f_amount_total, self.strategy.lockable_field_ids)
        self.assertNotIn(state_field, self.strategy.lockable_field_ids)
        new = self.env['so.release.strategy'].create({'name': 'Defaults'})
        self.assertEqual(set(new.locked_field_ids.mapped('name')),
                         {'partner_id', 'order_line', 'amount_total'})

    def test_05_settings_form(self):
        settings = Form(self.env['res.config.settings'])
        self.assertTrue(settings.so_release_strategy_enabled)

    # ------------------------------------------------------------------
    # automatic trigger from the sales team strategy
    # ------------------------------------------------------------------
    def test_10_below_rules_confirms_directly(self):
        so = self._create_so(price=500)
        self.assertFalse(so.release_needed)
        self.assertEqual(so.team_release_strategy_id, self.strategy)
        so.with_user(self.salesperson).action_confirm()
        self.assertEqual(so.state, 'sale')
        self.assertEqual(so.release_state, 'not_required')
        self.assertEqual(so.release_strategy_id, self.strategy)
        self.assertEqual(so.release_amount_company, 500.0)
        self.assertFalse(so.release_line_ids)

    def test_11_in_range_triggers_approval(self):
        so = self._create_so(price=5000)
        self.assertTrue(so.release_needed)
        so.with_user(self.salesperson).action_confirm()
        self.assertEqual(so.state, 'draft', 'the order is not confirmed')
        self.assertEqual(so.release_state, 'pending')
        self.assertEqual(so.release_strategy_id, self.strategy)
        self.assertEqual(so.release_amount_company, 5000.0)
        self.assertEqual(len(so.release_line_ids), 1, 'finance rule must not apply below 10000')
        line = so.release_line_ids
        self.assertEqual(line.state, 'pending')
        self.assertTrue(line.assigned_date)
        activities = self._release_activities(so)
        self.assertEqual(activities.user_id, self.manager)
        self.assertEqual(activities.so_release_line_id, line)

        # confirming again while pending is refused
        with self.assertRaises(UserError):
            so.with_user(self.salesperson).action_confirm()
        # nobody else can approve
        self.assertFalse(so.with_user(self.outsider).release_can_approve)
        with self.assertRaises(AccessError):
            so.with_user(self.outsider)._so_release_approve()

        self.assertTrue(so.with_user(self.manager).release_can_approve)
        self._wizard(so, self.manager, 'approve', 'Margin OK')
        self.assertEqual(line.state, 'approved')
        self.assertEqual(line.approved_by_id, self.manager)
        self.assertEqual(line.notes, 'Margin OK')
        self.assertTrue(line.approval_date)
        self.assertFalse(self._release_activities(so), 'activity must be completed')
        done_msg = so.message_ids.filtered(
            lambda m: m.mail_activity_type_id == self.activity_type)
        self.assertTrue(done_msg, 'completing the activity posts a "done" message')
        self.assertEqual(so.release_state, 'approved')
        self.assertEqual(so.state, 'sale')
        self.assertTrue(so.release_approval_date)

    def test_12_strategy_follows_the_team(self):
        so_a = self._create_so(price=20000, team=self.team_a)
        so_c = self._create_so(price=20000, team=self.team_c)
        self.assertEqual(so_c.team_release_strategy_id, self.strategy_b)
        self.assertTrue(so_a.release_needed)
        self.assertFalse(so_c.release_needed)
        (so_a | so_c).with_user(self.salesperson).action_confirm()
        self.assertEqual(so_a.release_state, 'pending')
        self.assertEqual(so_a.state, 'draft')
        self.assertEqual(so_c.release_state, 'not_required')
        self.assertEqual(so_c.state, 'sale')
        self.assertEqual(so_c.release_strategy_id, self.strategy_b)

    def test_13_request_approval_button(self):
        so = self._create_so(price=500)
        with self.assertRaises(UserError):
            so.with_user(self.salesperson).action_release_submit()
        so.order_line.price_unit = 2000
        so.with_user(self.salesperson).action_release_submit()
        self.assertEqual(so.release_state, 'pending')
        with self.assertRaises(UserError):
            so.with_user(self.salesperson).action_release_submit()

    def test_14_misconfigured_team_blocks_confirmation(self):
        team = self.env['crm.team'].create({
            'name': 'Unconfigured', 'company_id': self.company.id,
            'user_id': self.lonely.id})
        so = self._create_so(price=10, user=self.lonely, team=team)
        self.assertTrue(so.release_needed)
        with self.assertRaises(UserError):
            so.with_user(self.lonely).action_confirm()

    # ------------------------------------------------------------------
    # multi stage / groups
    # ------------------------------------------------------------------
    def test_20_multi_stage_with_group(self):
        so = self._create_so(price=20000)
        so.with_user(self.salesperson).action_confirm()
        self.assertEqual(len(so.release_line_ids), 2)
        manager_line, finance_line = so.release_line_ids.sorted('sequence')
        self.assertEqual(manager_line.state, 'pending')
        self.assertEqual(finance_line.state, 'waiting')
        self.assertEqual(self._release_activities(so).user_id, self.manager)
        self.assertEqual(so.release_pending_user_ids, self.manager)

        # finance approvers only see their own documents, yet can open this one
        so.with_user(self.fin1).read(['name', 'amount_total'])
        so.order_line.with_user(self.fin1).read(['name'])
        # but cannot approve before their stage
        with self.assertRaises(AccessError):
            so.with_user(self.fin1)._so_release_approve()

        self._wizard(so, self.manager, 'approve')
        self.assertEqual(finance_line.state, 'pending')
        self.assertEqual(self._release_activities(so).user_id, self.fin1 | self.fin2)
        self.assertEqual(so.state, 'draft')

        self._wizard(so, self.fin2, 'approve', 'Finance validated')
        self.assertEqual(finance_line.state, 'approved')
        self.assertEqual(finance_line.approved_by_id, self.fin2)
        self.assertFalse(self._release_activities(so), "other members' activities removed")
        self.assertEqual(so.state, 'sale')

    def test_21_parallel_stage(self):
        self.strategy.rule_ids.filtered(lambda r: r.role == 'Finance').write(
            {'sequence': 10, 'min_amount': 1000.0})
        so = self._create_so(price=2000)
        so.action_confirm()
        self.assertEqual(set(so.release_line_ids.mapped('state')), {'pending'})
        self._wizard(so, self.fin1, 'approve')
        self.assertEqual(so.release_state, 'pending')
        self._wizard(so, self.manager, 'approve')
        self.assertEqual(so.release_state, 'approved')

    def test_22_group_member_without_access_skipped(self):
        no_access = new_test_user(self.env, 'srs_noaccess', groups='base.group_user', name='No Access')
        self.finance_group.users = [Command.link(no_access.id)]
        so = self._create_so(price=20000)
        so.action_confirm()
        self._wizard(so, self.manager, 'approve')
        self.assertNotIn(no_access, self._release_activities(so).user_id)

    # ------------------------------------------------------------------
    # currency normalization
    # ------------------------------------------------------------------
    def test_30_foreign_currency_normalized(self):
        foreign = self.env['res.currency'].create({
            'name': 'SRX', 'symbol': 'S', 'rounding': 0.01})
        rates = self.env['res.currency.rate']
        own_rate = rates.search([('currency_id', '=', self.company_currency.id),
                                 ('company_id', '=', self.company.id),
                                 ('name', '=', fields.Date.today())])
        if own_rate:
            own_rate.rate = 1.0
        else:
            rates.create({'currency_id': self.company_currency.id, 'company_id': self.company.id,
                          'name': fields.Date.today(), 'rate': 1.0})
        rates.create({'currency_id': foreign.id, 'company_id': self.company.id,
                      'name': fields.Date.today(), 'rate': 0.5})  # 1 company unit = 0.5 SRX
        pricelist = self.env['product.pricelist'].create({
            'name': 'SRX pricelist', 'currency_id': foreign.id})
        # 6000 SRX = 12000 in company currency -> finance stage needed
        so = self._create_so(price=6000, pricelist=pricelist)
        self.assertEqual(so.currency_id, foreign)
        so.action_confirm()
        self.assertEqual(so.release_amount_company, 12000.0)
        self.assertEqual(len(so.release_line_ids), 2)
        # same face value in company currency stays below the finance threshold
        so2 = self._create_so(price=6000)
        so2.action_confirm()
        self.assertEqual(len(so2.release_line_ids), 1)

    def test_31_untaxed_basis(self):
        tax = self.env['account.tax'].create({
            'name': 'SRS 100%', 'amount': 100.0, 'type_tax_use': 'sale'})
        so = self._create_so(price=6000)
        so.order_line.tax_id = tax
        self.assertEqual(so.amount_total, 12000.0)
        so.action_confirm()
        self.assertEqual(len(so.release_line_ids), 2)
        so.with_user(self.supervisor)._so_release_manual_reset()
        self.strategy.amount_basis = 'untaxed'
        so.action_confirm()
        self.assertEqual(so.release_amount_company, 6000.0)
        self.assertEqual(len(so.release_line_ids), 1)

    # ------------------------------------------------------------------
    # reject / reset / bypass
    # ------------------------------------------------------------------
    def test_40_reject_and_resubmit(self):
        so = self._create_so(price=20000)
        so.action_confirm()
        with self.assertRaises(UserError):
            self._wizard(so, self.manager, 'reject', '')
        self._wizard(so, self.manager, 'reject', 'Discount too high')
        manager_line, finance_line = so.release_line_ids.sorted('sequence')
        self.assertEqual(manager_line.state, 'rejected')
        self.assertEqual(manager_line.rejected_by_id, self.manager)
        self.assertEqual(finance_line.state, 'cancelled')
        self.assertEqual(so.release_state, 'rejected')
        self.assertEqual(so.state, 'draft')
        self.assertFalse(self._release_activities(so))
        todo = so.activity_ids.filtered(lambda a: a.user_id == self.salesperson)
        self.assertTrue(todo, 'the salesperson is notified of the rejection')

        so.order_line.price_unit = 9000
        so.with_user(self.salesperson).action_confirm()
        self.assertEqual(so.release_state, 'pending')
        self.assertEqual(len(so.release_line_ids), 1)

    def test_41_manual_reset(self):
        so = self._create_so(price=20000)
        so.action_confirm()
        self._wizard(so, self.manager, 'approve')
        with self.assertRaises(AccessError):
            so.with_user(self.outsider)._so_release_manual_reset()
        self._wizard(so, self.salesperson, 'reset', 'Wrong customer')
        self.assertEqual(so.release_state, 'draft')
        self.assertEqual(so.state, 'draft')
        self.assertFalse(so.release_line_ids)
        self.assertFalse(self._release_activities(so))
        self.assertEqual(so.release_reset_count, 1)

    def test_42_supervisor_bypass(self):
        so = self._create_so(price=20000)
        so.action_confirm()
        with self.assertRaises(AccessError):
            so.with_user(self.manager)._so_release_bypass('urgent')
        with self.assertRaises(UserError):
            self._wizard(so, self.supervisor, 'bypass', '')
        self._wizard(so, self.supervisor, 'bypass', 'Strategic customer')
        self.assertEqual(set(so.release_line_ids.mapped('state')), {'bypassed'})
        self.assertTrue(so.release_bypassed)
        self.assertEqual(so.release_bypass_user_id, self.supervisor)
        self.assertEqual(so.release_bypass_reason, 'Strategic customer')
        self.assertFalse(self._release_activities(so))
        self.assertEqual(so.state, 'sale')

    def test_43_activity_cannot_be_completed_manually(self):
        so = self._create_so(price=2000)
        so.action_confirm()
        activity = self._release_activities(so).with_user(self.manager)
        with self.assertRaises(UserError):
            activity.action_feedback(feedback='done from chatter')
        with self.assertRaises(UserError):
            activity.unlink()

    def test_44_cancel_clears_release(self):
        so = self._create_so(price=20000)
        so.action_confirm()
        so._action_cancel()
        self.assertEqual(so.state, 'cancel')
        self.assertEqual(so.release_state, 'draft')
        self.assertFalse(so.release_line_ids)
        self.assertFalse(self._release_activities(so))
        so.action_draft()
        so.action_confirm()
        self.assertEqual(so.release_state, 'pending')

    def test_45_copy_resets_release(self):
        so = self._create_so(price=2000)
        so.action_confirm()
        self._wizard(so, self.manager, 'approve')
        copy = so.copy()
        self.assertEqual(copy.release_state, 'draft')
        self.assertFalse(copy.release_line_ids)
        self.assertFalse(copy.release_strategy_id)
        self.assertEqual(copy.team_release_strategy_id, self.strategy)

    # ------------------------------------------------------------------
    # post-approval: notify the salesperson
    # ------------------------------------------------------------------
    def test_50_notify_salesperson(self):
        self.strategy.post_approval_action = 'notify_salesperson'
        so = self._create_so(price=2000)
        so.action_confirm()
        self._wizard(so, self.manager, 'approve')
        self.assertEqual(so.release_state, 'approved')
        self.assertEqual(so.state, 'draft')
        self.assertFalse(so.release_needed, 'released: the native confirm is available')
        confirm_activity = so.activity_ids.filtered(lambda a: a.activity_type_id == self.confirm_type)
        self.assertEqual(confirm_activity.user_id, self.salesperson)
        so.with_user(self.salesperson).action_confirm()
        self.assertEqual(so.state, 'sale')
        self.assertEqual(so.release_state, 'approved')
        self.assertEqual(so.release_reset_count, 0, 'confirmation must not reset the release')
        self.assertFalse(so.activity_ids.filtered(lambda a: a.activity_type_id == self.confirm_type))

    # ------------------------------------------------------------------
    # field locking / re-evaluation
    # ------------------------------------------------------------------
    def test_60_locked_field_resets_and_renotifies(self):
        self.strategy.post_approval_action = 'notify_salesperson'
        so = self._create_so(price=20000)
        so.action_confirm()
        self._approve_all(so)
        self.assertEqual(so.release_state, 'approved')
        self.assertEqual(so.state, 'draft')
        messages_before = so.message_ids

        so.with_user(self.salesperson).write({'partner_id': self.partner2.id})
        self.assertEqual(so.release_state, 'pending')
        self.assertEqual(so.release_reset_count, 1)
        self.assertEqual(set(so.release_line_ids.mapped('state')), {'pending', 'waiting'})
        self.assertFalse(so.release_line_ids.filtered('approved_by_id'), 'approvals cleared')
        self.assertEqual(self._release_activities(so).user_id, self.manager)
        reset_msg = (so.message_ids - messages_before).filtered(
            lambda m: 'locked fields were modified' in (m.body or ''))
        self.assertTrue(reset_msg)
        self.assertEqual(set(reset_msg.partner_ids.ids),
                         set((self.manager | self.fin1 | self.fin2).partner_id.ids))

    def test_61_locked_order_lines(self):
        so = self._create_so(price=2000)
        so.action_confirm()  # pending, snapshot taken at submission
        so.order_line.with_user(self.salesperson).write({'product_uom_qty': 2})
        self.assertEqual(so.release_reset_count, 1)
        self.assertEqual(so.release_state, 'pending')
        so.with_user(self.salesperson).write({'order_line': [Command.create({
            'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': 1, 'tax_id': False})]})
        self.assertEqual(so.release_reset_count, 2)

    def test_62_unlocked_field_does_not_reset(self):
        so = self._create_so(price=2000)
        so.action_confirm()
        so.write({'note': '<p>internal remark</p>', 'client_order_ref': 'PO-123'})
        self.assertEqual(so.release_reset_count, 0)
        self.assertEqual(so.release_state, 'pending')

    def test_63_team_change_reevaluates(self):
        so = self._create_so(price=20000)
        so.action_confirm()
        self.assertEqual(so.release_state, 'pending')
        # team C (key accounts) only reviews orders above 50 000
        so.with_user(self.salesperson).write({'team_id': self.team_c.id})
        self.assertEqual(so.release_state, 'draft')
        self.assertFalse(so.release_line_ids)
        self.assertFalse(self._release_activities(so))
        so.with_user(self.salesperson).action_confirm()
        self.assertEqual(so.state, 'sale')
        self.assertEqual(so.release_strategy_id, self.strategy_b)

    def test_64_confirmed_order_reset_policy(self):
        so = self._create_so(price=500)
        so.action_confirm()
        self.assertEqual(so.release_state, 'not_required')
        # still below every rule: accepted, reference values refreshed
        so.order_line.write({'price_unit': 600})
        self.assertEqual(so.release_state, 'not_required')
        self.assertEqual(so.release_amount_company, 600.0)
        # now in range: approval requested, the order stays confirmed
        so.order_line.write({'price_unit': 2000})
        self.assertEqual(so.state, 'sale')
        self.assertEqual(so.release_state, 'pending')
        self.assertEqual(self._release_activities(so).user_id, self.manager)
        self._wizard(so, self.manager, 'approve')
        self.assertEqual(so.release_state, 'approved')
        self.assertEqual(so.state, 'sale')

    def test_65_confirmed_order_block_policy(self):
        self.strategy.lock_confirmed_policy = 'block'
        so = self._create_so(price=2000)
        so.action_confirm()
        self._wizard(so, self.manager, 'approve')
        self.assertEqual(so.state, 'sale')
        with self.assertRaises(UserError):
            so.write({'partner_id': self.partner2.id})
        so.write({'client_order_ref': 'allowed'})
        self.assertEqual(so.release_state, 'approved')

        small = self._create_so(price=500)
        small.action_confirm()
        small.order_line.write({'price_unit': 700})  # still no approval needed
        self.assertEqual(small.release_state, 'not_required')
        with self.assertRaises(UserError):
            small.order_line.write({'price_unit': 5000})

    def test_66_system_lines_do_not_reset(self):
        so = self._create_so(price=2000)
        so.action_confirm()
        self._wizard(so, self.manager, 'approve')
        self.assertEqual(so.state, 'sale')
        self.env['sale.order.line'].create({
            'order_id': so.id, 'name': 'Down payment', 'product_id': self.product.id,
            'product_uom_qty': 0.0, 'price_unit': 500.0, 'is_downpayment': True, 'tax_id': False,
        })
        self.assertEqual(so.release_reset_count, 0)
        self.assertEqual(so.release_state, 'approved')

    # ------------------------------------------------------------------
    # re-approval holds invoicing; switching off clears pending approvals
    # ------------------------------------------------------------------
    def test_67_invoicing_held_during_reapproval(self):
        so = self._create_so(price=500)
        so.action_confirm()
        self.assertEqual(so.release_state, 'not_required')
        self.assertFalse(so._so_release_holds_operations())
        so.order_line.write({'price_unit': 2000})
        self.assertEqual(so.state, 'sale')
        self.assertEqual(so.release_state, 'pending')
        self.assertTrue(so._so_release_holds_operations())
        with self.assertRaises(UserError):
            so._create_invoices()
        Wizard = self.env['sale.advance.payment.inv'].with_context(
            active_model='sale.order', active_ids=so.ids, active_id=so.id)
        with self.assertRaises(UserError):
            Wizard.create({'advance_payment_method': 'delivered'}).create_invoices()
        with self.assertRaises(UserError):
            Wizard.create({'advance_payment_method': 'percentage', 'amount': 10}).create_invoices()
        # automated invoicing (online payment) skips the held order quietly
        invoices = so.with_context(raise_if_nothing_to_invoice=False)._create_invoices()
        self.assertFalse(invoices)
        self.assertFalse(so.invoice_ids)
        # a rejected re-approval keeps holding
        self._wizard(so, self.manager, 'reject', 'Price too high')
        self.assertTrue(so._so_release_holds_operations())
        so.with_user(self.salesperson).action_release_submit()
        self._wizard(so, self.manager, 'approve')
        self.assertEqual(so.release_state, 'approved')
        self.assertFalse(so._so_release_holds_operations())

    def test_68_switch_off_cancels_pending(self):
        quotation = self._create_so(price=20000)
        quotation.action_confirm()
        self._wizard(quotation, self.manager, 'approve', 'OK')
        confirmed = self._create_so(price=500)
        confirmed.action_confirm()
        confirmed.order_line.write({'price_unit': 2000})
        self.assertEqual(quotation.release_state, 'pending')
        self.assertEqual(confirmed.release_state, 'pending')

        self.company.so_release_strategy_enabled = False

        for order in (quotation, confirmed):
            self.assertEqual(order.release_state, 'draft')
            self.assertFalse(self._release_activities(order))
            self.assertFalse(order.release_line_ids.filtered(lambda l: l.state in ('waiting', 'pending')))
            self.assertTrue(order.message_ids.filtered(lambda m: 'switched off' in (m.body or '')))
        # approval history is kept
        approved = quotation.release_line_ids.filtered(lambda l: l.state == 'approved')
        self.assertEqual(approved.notes, 'OK')
        self.assertFalse(confirmed._so_release_holds_operations())
        quotation.with_user(self.salesperson).action_confirm()
        self.assertEqual(quotation.state, 'sale')

    # ------------------------------------------------------------------
    # online acceptance (portal signature / payment)
    # ------------------------------------------------------------------
    def test_70_online_acceptance_is_held(self):
        so = self._create_so(price=20000)
        so.action_quotation_sent()
        portal_user = new_test_user(self.env, 'srs_portal', groups='base.group_portal',
                                    name='Portal Customer')
        so.sudo().write({'signature': SIGNATURE, 'signed_by': 'Customer',
                         'signed_on': fields.Datetime.now()})
        comments_before = so.message_ids.filtered(lambda m: m.message_type == 'comment')
        so_portal = so.with_user(portal_user).sudo()
        so_portal.action_confirm()
        so_portal._send_order_confirmation_mail()
        self.assertEqual(so.state, 'sent', 'held for approval, not confirmed')
        self.assertEqual(so.release_state, 'pending')
        comments_after = so.message_ids.filtered(lambda m: m.message_type == 'comment')
        self.assertEqual(comments_before, comments_after, 'no confirmation mail while held')
        self._approve_all(so)
        self.assertEqual(so.state, 'sale')

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def test_80_forms(self):
        with Form(self.env['sale.order'].with_user(self.salesperson)) as so_form:
            so_form.partner_id = self.partner
            so_form.team_id = self.team_a
            self.assertEqual(so_form.team_release_strategy_id, self.strategy)
            with so_form.order_line.new() as line:
                line.product_id = self.product
                line.product_uom_qty = 200
                line.price_unit = 10
            self.assertTrue(so_form.release_needed)
        so = so_form.save()
        so.with_user(self.salesperson).action_confirm()
        self.assertEqual(so.release_state, 'pending')
        Form(so.with_user(self.manager))
        Form(so.with_user(self.fin1))
        strategy_form = Form(self.strategy)
        with strategy_form.rule_ids.new() as rule:
            rule.role = 'CEO'
            rule.approver_type = 'user'
            rule.user_id = self.supervisor
            rule.min_amount = 100000
        strategy_form.save()
        self.assertEqual(len(self.strategy.rule_ids), 3)
        team_form = Form(self.team_b)
        self.assertEqual(team_form.so_release_strategy_id, self.strategy_b)

    def test_81_my_approvals_filter(self):
        so = self._create_so(price=2000)
        so.action_confirm()
        domain = [('activity_ids.user_id', '=', self.manager.id),
                  ('activity_ids.so_release_line_id', '!=', False)]
        found = self.env['sale.order'].with_user(self.manager).search(domain)
        self.assertIn(so, found)

    # ------------------------------------------------------------------
    # integration with sale_stock (skipped when not installed)
    # ------------------------------------------------------------------
    def test_90_delivery_created_only_after_release(self):
        if 'picking_ids' not in self.env['sale.order']._fields:
            self.skipTest('sale_stock is not installed')
        storable = self.env['product.product'].create({
            'name': 'Release Storable', 'type': 'product', 'taxes_id': False,
            'list_price': 1.0})
        self.env['stock.quant']._update_available_quantity(
            storable, self.env['stock.warehouse'].search(
                [('company_id', '=', self.company.id)], limit=1).lot_stock_id, 10)
        so = self._create_so(price=20000)
        so.order_line.product_id = storable
        so.order_line.price_unit = 20000
        so.action_confirm()
        self.assertFalse(so.picking_ids, 'no delivery while waiting for approval')
        self._wizard(so, self.manager, 'approve')
        self.assertFalse(so.picking_ids)
        self._wizard(so, self.fin2, 'approve')
        self.assertEqual(len(so.picking_ids), 1)
        picking = so.picking_ids
        picking.move_ids.quantity_done = 1
        picking.button_validate()
        self.assertEqual(so.order_line.qty_delivered, 1)
        self.assertEqual(so.release_state, 'approved')
        self.assertEqual(so.release_reset_count, 0)
