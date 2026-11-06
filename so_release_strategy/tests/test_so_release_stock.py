# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged

from .common import SoReleaseCommon


@tagged('post_install', '-at_install')
class TestSoReleaseStock(SoReleaseCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.storable = cls.env['product.product'].create({
            'name': 'Release Storable', 'type': 'product', 'list_price': 100.0,
            'taxes_id': False, 'invoice_policy': 'order'})
        warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.env['stock.quant']._update_available_quantity(
            cls.storable, warehouse.lot_stock_id, 100)

    def _confirmed_so(self, qty=5):
        so = self._create_so(order_line=[Command.create({
            'product_id': self.storable.id, 'product_uom_qty': qty,
            'price_unit': 100.0, 'tax_id': False})])
        so.action_confirm()
        self.assertEqual(so.state, 'sale')
        self.assertEqual(so.release_state, 'not_required')
        return so

    def _demand(self, so):
        moves = so.order_line.move_ids.filtered(lambda m: m.state != 'cancel')
        return sum(moves.mapped('product_uom_qty'))

    def test_01_quantity_increase_held_until_approved(self):
        so = self._confirmed_so()
        self.assertEqual(self._demand(so), 5)
        so.order_line.write({'product_uom_qty': 40})
        self.assertEqual(so.release_state, 'pending')
        self.assertEqual(self._demand(so), 5, 'no extra delivery while waiting')
        self._wizard(so, self.manager, 'approve')
        self.assertEqual(so.release_state, 'approved')
        self.assertEqual(self._demand(so), 40)

    def test_02_new_line_through_order_write_then_bypass(self):
        so = self._confirmed_so()
        so.write({'order_line': [Command.create({
            'product_id': self.storable.id, 'product_uom_qty': 30,
            'price_unit': 100.0, 'tax_id': False})]})
        self.assertEqual(so.release_state, 'pending')
        self.assertEqual(self._demand(so), 5)
        self._wizard(so, self.supervisor, 'bypass', 'Urgent')
        self.assertEqual(self._demand(so), 35)

    def test_03_rejected_then_back_below_rules(self):
        so = self._confirmed_so()
        so.order_line.write({'product_uom_qty': 40})
        self._wizard(so, self.manager, 'reject', 'Too much')
        self.assertEqual(self._demand(so), 5)
        so.order_line.write({'product_uom_qty': 8})
        self.assertEqual(self._demand(so), 5, 'still held: the order is rejected')
        so.with_user(self.salesperson).action_release_submit()  # 800: no rule applies
        self.assertEqual(so.release_state, 'not_required')
        self.assertEqual(self._demand(so), 8)

    def test_04_switch_off_launches_held_deliveries(self):
        so = self._confirmed_so()
        so.order_line.write({'product_uom_qty': 40})
        self.assertEqual(self._demand(so), 5)
        self.company.so_release_strategy_enabled = False
        self.assertEqual(self._demand(so), 40)

    def test_05_small_change_not_held(self):
        so = self._confirmed_so()
        so.order_line.write({'product_uom_qty': 8})  # 800: still below every rule
        self.assertEqual(so.release_state, 'not_required')
        self.assertEqual(self._demand(so), 8)

    def test_06_switch_off_releases_rejected_order(self):
        so = self._confirmed_so()
        so.order_line.write({'product_uom_qty': 40})
        self._wizard(so, self.manager, 'reject', 'Too much')
        self.assertEqual(self._demand(so), 5)
        self.company.so_release_strategy_enabled = False
        self.assertEqual(so.release_state, 'rejected', 'history kept')
        self.assertEqual(self._demand(so), 40)
