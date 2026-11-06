# Sales Order Release Strategy (Odoo 18.0)

Team-driven, multi-level approval ("release strategy") for Odoo sales orders.
Community and Enterprise. English and Arabic (`ar_001`), right-to-left ready.

Author: [Ibrahim Yahia](https://www.linkedin.com/in/ibrahim-yahia) · License: LGPL-3

## Branches

Each branch holds the code for one Odoo version:

| Branch | Odoo | `so_release_strategy` |
|---|---|---|
| `16.0` | 16.0 | 16.0.1.2.0 |
| `17.0` | 17.0 | 17.0.1.2.0 |
| `18.0` | 18.0 | 18.0.1.1.0 |
| `19.0` | 19.0 | 19.0.1.1.0 |

This branch: **18.0** (`so_release_strategy` 18.0.1.1.0).

Depends on `sale_stock` (Sales and Inventory) and `mail`.

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
  invoiced, and the deliveries for added quantities wait until it is approved.
- Online signature and payment are held for approval.
- Switching the feature off cancels pending approvals, keeps the approval history and creates
  the held deliveries.

## Installation

1. Put the `so_release_strategy` folder in your addons path (on Odoo.sh, push this branch to
   your repository).
2. Install **Sales Order Release Strategy** (Inventory is installed with it if missing).
3. Create strategies in **Sales › Configuration › Release Strategies**, assign one to each
   sales team, then enable the setting.

### Upgrading from an earlier release

Earlier releases shipped the Inventory part as a separate module,
`so_release_strategy_stock`. It is now part of `so_release_strategy`:

1. Remove the `so_release_strategy_stock` folder from your addons path.
2. Upgrade **Sales Order Release Strategy**. The upgrade marks the old module as
   uninstalled (it held no data) and installs Inventory if it was not installed.

## Tests

```
odoo-bin -d <db> -i so_release_strategy --test-tags /so_release_strategy
```

## Other versions

`16.0`, `17.0`, `19.0`
