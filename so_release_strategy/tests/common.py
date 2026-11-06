# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.tests.common import TransactionCase, new_test_user

SIGNATURE = b'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'


class SoReleaseCommon(TransactionCase):
    """Shared data: also used by so_release_strategy_stock."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=False,
                                       mail_create_nolog=True, mail_notrack=False))
        cls.company = cls.env.company
        cls.company_currency = cls.company.currency_id

        own_docs = 'base.group_user,sales_team.group_sale_salesman'
        all_docs = 'base.group_user,sales_team.group_sale_salesman_all_leads'
        cls.salesperson = new_test_user(cls.env, 'srs_sales', groups=own_docs, name='Release Salesperson')
        cls.salesperson2 = new_test_user(cls.env, 'srs_sales2', groups=own_docs, name='Other Salesperson')
        cls.team_lead = new_test_user(cls.env, 'srs_lead', groups=own_docs, name='Team Leader')
        cls.lonely = new_test_user(cls.env, 'srs_lonely', groups=own_docs, name='No Team Salesperson')
        cls.manager = new_test_user(cls.env, 'srs_manager', groups=all_docs, name='Sales Approver')
        # finance approvers only see their own documents: the module's record
        # rule must still let them open the orders they approve
        cls.fin1 = new_test_user(cls.env, 'srs_fin1', groups=own_docs, name='Finance One')
        cls.fin2 = new_test_user(cls.env, 'srs_fin2', groups=own_docs, name='Finance Two')
        cls.outsider = new_test_user(cls.env, 'srs_outsider', groups=all_docs, name='Outsider')
        cls.supervisor = new_test_user(
            cls.env, 'srs_supervisor', name='Release Supervisor',
            groups=f'{all_docs},so_release_strategy.group_so_release_supervisor')
        cls.sales_manager = new_test_user(
            cls.env, 'srs_sales_manager', name='Sales Manager',
            groups='base.group_user,sales_team.group_sale_manager')
        cls.finance_group = cls.env['res.groups'].create({
            'name': 'Sales Release Finance Approvers',
            'user_ids': [Command.link(cls.fin1.id), Command.link(cls.fin2.id)],
        })

        cls.partner = cls.env['res.partner'].create({'name': 'Release Customer'})
        cls.partner2 = cls.env['res.partner'].create({'name': 'Other Customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'Release Product', 'type': 'consu', 'list_price': 10.0,
            'taxes_id': False, 'supplier_taxes_id': False, 'invoice_policy': 'order',
        })

        fields_model = cls.env['ir.model.fields']
        cls.f_partner = fields_model._get('sale.order', 'partner_id')
        cls.f_order_line = fields_model._get('sale.order', 'order_line')
        cls.f_amount_total = fields_model._get('sale.order', 'amount_total')

        Strategy = cls.env['so.release.strategy']
        # team A: manager above 1 000, finance above 10 000
        cls.strategy = Strategy.create({
            'name': 'Standard Sales',
            'post_approval_action': 'auto_confirm',
            'locked_field_ids': [Command.set([cls.f_partner.id, cls.f_order_line.id])],
            'rule_ids': [
                Command.create({'sequence': 10, 'role': 'Sales Director',
                                'approver_type': 'user', 'user_id': cls.manager.id,
                                'min_amount': 1000.0, 'max_amount': 0.0}),
                Command.create({'sequence': 20, 'role': 'Finance',
                                'approver_type': 'group', 'group_id': cls.finance_group.id,
                                'min_amount': 10000.0, 'max_amount': 0.0}),
            ],
        })
        # team B: only orders above 50 000 need an approval
        cls.strategy_b = Strategy.create({
            'name': 'Key Accounts',
            'rule_ids': [
                Command.create({'sequence': 10, 'role': 'Sales Director',
                                'approver_type': 'user', 'user_id': cls.manager.id,
                                'min_amount': 50000.0, 'max_amount': 0.0}),
            ],
        })

        Team = cls.env['crm.team']
        # every team of the company needs a strategy before activation
        Team.search([('company_id', 'in', [False, cls.company.id])]).write(
            {'so_release_strategy_id': cls.strategy.id})
        cls.team_a = Team.create({
            'name': 'Release Team A', 'company_id': cls.company.id,
            'user_id': cls.team_lead.id,
            'crm_team_member_ids': [Command.create({'user_id': cls.salesperson.id})],
            'so_release_strategy_id': cls.strategy.id,
        })
        cls.team_b = Team.create({
            'name': 'Release Team B', 'company_id': cls.company.id,
            'crm_team_member_ids': [Command.create({'user_id': cls.salesperson2.id})],
            'so_release_strategy_id': cls.strategy_b.id,
        })
        # the salesperson leads team C (leaders belong to their team)
        cls.team_c = Team.create({
            'name': 'Release Team C', 'company_id': cls.company.id,
            'user_id': cls.salesperson.id,
            'so_release_strategy_id': cls.strategy_b.id,
        })
        cls.company.so_release_strategy_enabled = True
        cls.activity_type = cls.env.ref('so_release_strategy.mail_activity_type_so_release')
        cls.confirm_type = cls.env.ref('so_release_strategy.mail_activity_type_so_release_confirm')

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _create_so(self, price=100.0, qty=1.0, user=None, team=None, pricelist=None, **vals):
        user = user or self.salesperson
        values = {
            'partner_id': self.partner.id,
            'user_id': user.id,
            'team_id': (team or self.team_a).id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'price_unit': price,
                'tax_ids': False,
            })],
        }
        if pricelist:
            values['pricelist_id'] = pricelist.id
        values.update(vals)
        return self.env['sale.order'].with_user(user).create(values)

    def _release_activities(self, order, user=None):
        activities = order.sudo().activity_ids.filtered(
            lambda a: a.activity_type_id == self.activity_type)
        if user:
            activities = activities.filtered(lambda a: a.user_id == user)
        return activities

    def _wizard(self, order, user, action, notes=False):
        res = order.with_user(user)._so_release_open_wizard(action)
        wizard = self.env['so.release.action.wizard'].with_user(user).with_context(
            **res['context']).create({'notes': notes})
        return wizard.action_confirm()

    def _approve_all(self, order):
        self._wizard(order, self.manager, 'approve')
        if order.release_state == 'pending':
            self._wizard(order, self.fin1, 'approve')
