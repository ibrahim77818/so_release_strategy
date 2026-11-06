# -*- coding: utf-8 -*-
from odoo import models


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    def _create_invoices(self, sale_orders):
        # covers regular invoices and down payments
        sale_orders._so_release_check_invoicing()
        return super()._create_invoices(sale_orders)
