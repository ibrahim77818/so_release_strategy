# Sales Order Release Strategy (Odoo 16.0)

Team-driven, multi-level approval ("release strategy") for Odoo sales orders.
Community and Enterprise. English and Arabic (`ar_001`), right-to-left ready.

Author: [Ibrahim Yahia](https://www.linkedin.com/in/ibrahim-yahia) · License: LGPL-3

## Branches

Each branch holds the code for one Odoo version:

| Branch | Odoo | `so_release_strategy` | `so_release_strategy_stock` |
|---|---|---|---|
| `16.0` | 16.0 | 16.0.1.1.0 | 16.0.1.0.0 |
| `17.0` | 17.0 | 17.0.1.1.0 | 17.0.1.0.0 |
| `18.0` | 18.0 | 18.0.1.0.0 | 18.0.1.0.0 |
| `19.0` | 19.0 | 19.0.1.0.0 | 19.0.1.0.0 |

This branch: **16.0** (`so_release_strategy` 16.0.1.1.0, `so_release_strategy_stock` 16.0.1.0.0).

## Modules

| Module | Depends on | Purpose |
|---|---|---|
| `so_release_strategy` | `sale`, `mail` | Release strategies, approvals, locked fields |
| `so_release_strategy_stock` | `so_release_strategy`, `sale_stock` | Holds new deliveries while a confirmed order waits for re-approval. Installed automatically with Inventory |

## Features

- Company switch in **Sales › Configuration › Settings › Release Strategies**. Once enabled,
  every sales team must have a release strategy.
- No strategy to pick on quotations: the sales team's strategy applies automatically, and
  **Confirm** requests the approvals when the amount falls within one of its rules.
- Sales team and salesperson are mandatory; the team must be one the salesperson belongs to
  (member or team leader).
- Rules by stage, role, approver type (specific user or user group) and min/max amount in
  company currency; foreign-currency orders are converted at the order date.
- Approval activities stage by stage, with assignment/approval timestamps, approver and notes;
  reject with reason, reset, and supervisor bypass.
- After final approval: confirm automatically, or notify the salesperson.
- Locked fields: changing them after submission or confirmation re-evaluates the order and
  notifies every approver again. While a confirmed order waits for re-approval it cannot be
  invoiced, and new deliveries wait.
- Online signature and payment are held for approval.
- Switching the feature off cancels pending approvals and keeps the approval history.

## Installation

1. Put both module folders in your addons path (on Odoo.sh, push this branch to your repository).
2. Install **Sales Order Release Strategy**. With Inventory installed, **Sales Order Release
   Strategy - Inventory** installs automatically; on a database where both are already
   installed, install it once from Apps.
3. Create strategies in **Sales › Configuration › Release Strategies**, assign one to each
   sales team, then enable the setting.

## Tests

```
odoo-bin -d <db> -i so_release_strategy,so_release_strategy_stock \
    --test-tags /so_release_strategy,/so_release_strategy_stock
```

## Other versions

`17.0`, `18.0`, `19.0`

