# -*- coding: utf-8 -*-
"""The Inventory integration formerly shipped as the separate module
so_release_strategy_stock is now part of this module. Mark the old module
uninstalled: it only held Python overrides, no data or views."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_module_module
           SET state = 'uninstalled', latest_version = NULL
         WHERE name = 'so_release_strategy_stock'
           AND state IN ('installed', 'to upgrade', 'to install')
     RETURNING id
    """)
    if cr.fetchall():
        cr.execute("""
            DELETE FROM ir_model_data
             WHERE module = 'so_release_strategy_stock'
               AND model IN ('ir.model', 'ir.model.fields', 'ir.model.constraint')
        """)
        _logger.info('so_release_strategy_stock merged into so_release_strategy: '
                     'old module marked uninstalled')
