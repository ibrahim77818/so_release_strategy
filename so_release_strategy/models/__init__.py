# -*- coding: utf-8 -*-
from . import res_company
from . import res_config_settings
from . import so_release_strategy
from . import crm_team
from . import mail_activity
from . import sale_order_release_line
from . import sale_order
from . import payment_transaction
# Inventory integration: keep last, these overrides must wrap the ones above
from . import sale_order_line_stock
from . import sale_order_stock
