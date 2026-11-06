# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    so_release_strategy_id = fields.Many2one(
        'so.release.strategy', string='Release Strategy',
        # No check_company: in Odoo 17 it injects a domain on company_id, which
        # the sales team views restrict to multi-company users. The domain below
        # and _check_so_release_strategy_company enforce the same rule.
        ondelete='restrict', tracking=True,
        domain="[('id', 'in', so_release_allowed_strategy_ids)]",
        help='Default release strategy of the team. It is applied automatically '
             'to the sales orders of the team: no strategy has to be selected '
             'on quotations.')
    so_release_allowed_strategy_ids = fields.Many2many(
        'so.release.strategy', compute='_compute_so_release_allowed_strategy_ids')
    so_release_required = fields.Boolean(
        compute='_compute_so_release_required',
        help='Technical: a company served by this team enforces sales release '
             'strategies.')

    @api.depends('company_id')
    def _compute_so_release_allowed_strategy_ids(self):
        Strategy = self.env['so.release.strategy']
        for team in self:
            domain = [('company_id', '=', team.company_id.id)] if team.company_id else []
            team.so_release_allowed_strategy_ids = Strategy.search(domain)

    @api.depends('company_id')
    def _compute_so_release_required(self):
        for team in self:
            team.so_release_required = bool(team._so_release_enforcing_companies())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _so_release_enforcing_companies(self):
        """Companies served by this team that enforce release strategies.
        A team without company serves every company."""
        self.ensure_one()
        if self.company_id:
            return self.company_id.filtered('so_release_strategy_enabled')
        return self.env['res.company'].sudo().search(
            [('so_release_strategy_enabled', '=', True)])

    def _so_release_strategy_valid_for(self, company):
        self.ensure_one()
        strategy = self.sudo().so_release_strategy_id
        return bool(strategy and strategy.active and strategy.company_id == company)

    def _so_release_is_member(self, user):
        """Odoo's own definition of "belonging to a team": team leader or
        active member (see crm.team._get_default_team_id)."""
        self.ensure_one()
        if not user:
            return False
        return user == self.user_id or user in self.sudo().crm_team_member_ids.user_id

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('so_release_strategy_id', 'company_id')
    def _check_so_release_strategy_company(self):
        for team in self:
            strategy = team.sudo().so_release_strategy_id
            if strategy and team.company_id and strategy.company_id != team.company_id:
                raise ValidationError(_(
                    'The release strategy "%(strategy)s" belongs to %(strategy_company)s, '
                    'but sales team %(team)s belongs to %(team_company)s.',
                    strategy=strategy.name, strategy_company=strategy.company_id.name,
                    team=team.display_name, team_company=team.company_id.name))

    @api.constrains('so_release_strategy_id')
    def _check_so_release_strategy(self):
        """Prevent removing (or mis-assigning) the strategy of a team while one
        of its companies enforces release strategies. Only checked when the
        strategy is written, so that teams created by other modules' data never
        block an installation; such teams are caught at order confirmation and
        when the feature is (re)enabled."""
        for team in self.filtered('active'):
            for company in team._so_release_enforcing_companies():
                if not team._so_release_strategy_valid_for(company):
                    raise ValidationError(_(
                        'Sales team %(team)s needs an active release strategy of '
                        '%(company)s because this company enforces sales release '
                        'strategies.', team=team.display_name, company=company.name))
