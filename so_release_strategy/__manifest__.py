# -*- coding: utf-8 -*-
{
    'name': 'Sales Order Release Strategy',
    'version': '16.0.1.2.1',
    'category': 'Sales/Sales',
    'summary': 'Multi-level sales order approvals driven by the sales team: '
               'amount-based release strategies, user/group approvers, '
               'activities, supervisor bypass and post-approval field locking.',
    'description': """
Sales Order Release Strategy
============================
* Company-level switch in Sales settings. Once enabled, every sales team must
  carry a default release strategy.
* No strategy to pick on quotations: the strategy of the order's sales team is
  applied automatically, and approvals are triggered on confirmation when the
  order amount falls within the range of one of its rules.
* Sales team and salesperson become mandatory, and an order can only be
  assigned to a team the salesperson belongs to (member or team leader).
* Release strategy templates with sequenced approval rules (specific user or
  user group, role, min/max amount in company currency).
* Foreign-currency orders are normalized to the company currency before the
  rules are evaluated.
* Approval lines and mail activities are generated automatically, stage by
  stage; approval logs assignment/approval timestamps, approver and notes.
* Reject, manual reset and supervisor bypass.
* Post-approval behaviour: confirm automatically or notify the salesperson.
* Locked fields: modifying them after submission or confirmation re-evaluates
  the order, clears approvals and re-notifies every approver.
* Online signature and payment flows hold orders that need approval instead of
  confirming them.
* While a confirmed order waits for a new approval it cannot be invoiced and
  the deliveries for added quantities are created only once it is approved.
* Arabic (ar_001) translation, RTL ready.
""",
    'author': 'Ibrahim Yahia',
    'website': 'https://www.linkedin.com/in/ibrahim-yahia',
    'license': 'LGPL-3',
    'images': ['static/description/banner.png'],
    'depends': ['sale_stock', 'mail'],
    'data': [
        'security/so_release_security.xml',
        'security/ir.model.access.csv',
        'data/mail_activity_type_data.xml',
        'wizard/so_release_action_wizard_views.xml',
        'views/so_release_strategy_views.xml',
        'views/crm_team_views.xml',
        'views/sale_order_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'so_release_strategy/static/src/css/so_release_strategy.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
