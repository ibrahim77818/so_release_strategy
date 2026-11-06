# -*- coding: utf-8 -*-
from odoo import models

from .sale_order_line_stock import BUCKET


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def write(self, vals):
        # order_line commands create/write lines inside this call: collect
        # their procurements until the release status of the order is final
        if self.env.context.get(BUCKET) is not None:
            return super().write(vals)
        bucket = []
        res = super(SaleOrder, self.with_context(**{BUCKET: bucket})).write(vals)
        self.env['sale.order.line']._so_release_flush_procurements(bucket)
        return res

    def _so_release_after_release(self):
        res = super()._so_release_after_release()
        # create the deliveries held while the order was waiting; sale_stock
        # only procures the quantity not yet covered by stock moves
        self.filtered(lambda o: o.state in ('sale', 'done')).order_line.with_context(
            **{BUCKET: None})._action_launch_stock_rule()
        return res
