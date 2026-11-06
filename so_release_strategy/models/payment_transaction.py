# -*- coding: utf-8 -*-
from odoo import models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _check_amount_and_confirm_order(self):
        """Quotations paid online but held for release approval are not
        confirmed: keep them out of the returned "confirmed" orders so that no
        confirmation mail is sent for them yet."""
        orders = super()._check_amount_and_confirm_order()
        return orders.filtered(lambda o: o.state == 'sale')
