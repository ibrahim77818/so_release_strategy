# -*- coding: utf-8 -*-
from odoo import api, models

# During a write/create the release status of the order is only final once
# every module's override has run (the locked-field check of
# this module may send the order back for approval). Procurements requested
# meanwhile by sale_stock are collected here and launched at the end.
# This file is imported after sale_order.py so that these overrides sit on top
# of the locked-field checks of the same module.
BUCKET = 'so_release_procurement_bucket'


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _action_launch_stock_rule(self, *, previous_product_uom_qty=False):  # keyword-only since v19
        bucket = self.env.context.get(BUCKET)
        if bucket is not None:
            bucket.append((self.ids, previous_product_uom_qty))
            return True
        held = self.filtered(lambda line: line.order_id._so_release_holds_operations())
        lines = self - held
        if not lines:
            return True
        return super(SaleOrderLine, lines)._action_launch_stock_rule(
            previous_product_uom_qty=previous_product_uom_qty)

    def _so_release_flush_procurements(self, bucket):
        Line = self.with_context(**{BUCKET: None})
        for ids, previous in bucket:
            # held orders are filtered out again; their deliveries are created
            # once the order is released (sale.order._so_release_after_release)
            Line.browse(ids).exists()._action_launch_stock_rule(previous_product_uom_qty=previous)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get(BUCKET) is not None:
            return super().create(vals_list)
        bucket = []
        lines = super(SaleOrderLine, self.with_context(**{BUCKET: bucket})).create(vals_list)
        lines = lines.with_context(**{BUCKET: None})
        lines._so_release_flush_procurements(bucket)
        return lines

    def write(self, vals):
        if self.env.context.get(BUCKET) is not None:
            return super().write(vals)
        bucket = []
        res = super(SaleOrderLine, self.with_context(**{BUCKET: bucket})).write(vals)
        self._so_release_flush_procurements(bucket)
        return res
