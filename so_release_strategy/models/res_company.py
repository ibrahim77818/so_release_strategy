# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    so_release_strategy_enabled = fields.Boolean(
        string='Sales Release Strategies',
        default=False,
        help='When enabled, every sales team of this company must have a '
             'release strategy, and sales orders whose amount falls within '
             'its rules must be approved before confirmation.')

    def write(self, vals):
        disabling = self.env['res.company']
        if 'so_release_strategy_enabled' in vals and not vals['so_release_strategy_enabled']:
            disabling = self.filtered('so_release_strategy_enabled')
        res = super().write(vals)
        if disabling:
            self.env['sale.order']._so_release_on_feature_disabled(disabling)
        return res

    @api.constrains('so_release_strategy_enabled')
    def _check_so_release_teams(self):
        """Activation requires every sales team serving the company to carry
        an active release strategy of that company."""
        Team = self.env['crm.team'].sudo()
        for company in self.filtered('so_release_strategy_enabled'):
            teams = Team.search([('company_id', 'in', [False, company.id])])
            missing = teams.filtered(
                lambda t: not t._so_release_strategy_valid_for(company))
            if missing:
                raise ValidationError(_(
                    'Before enabling sales release strategies for %(company)s, '
                    'assign an active release strategy of this company to every '
                    'sales team. Teams to fix: %(teams)s',
                    company=company.name,
                    teams=', '.join(missing.mapped('display_name'))))
