# -*- coding: utf-8 -*-
{
    'name': 'Sales Order Release Strategy - Inventory',
    'version': '18.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Holds new deliveries of confirmed sales orders while they wait '
               'for a new release approval.',
    'description': """
Bridge between Sales Order Release Strategy and Inventory, installed
automatically when both are installed.

When a locked field change sends a confirmed sales order back for release
approval, the deliveries for the added quantities are not created until the
order is approved again (or bypassed, or the feature is switched off).
""",
    'author': 'Ibrahim Yahia',
    'website': 'https://www.linkedin.com/in/ibrahim-yahia',
    'license': 'LGPL-3',
    'depends': ['so_release_strategy', 'sale_stock'],
    'data': [],
    'installable': True,
    'auto_install': True,
    'application': False,
}
