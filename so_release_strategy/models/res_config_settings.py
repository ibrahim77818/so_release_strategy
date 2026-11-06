# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    so_release_strategy_enabled = fields.Boolean(
        related='company_id.so_release_strategy_enabled', readonly=False)
