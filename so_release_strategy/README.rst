============================
Sales Order Release Strategy
============================

Multi-level, amount-based approval ("release strategy") for Odoo 19 sales
orders, driven by the sales team. Works on Community and Enterprise, depends
on ``sale_stock`` (Sales and Inventory) and ``mail``. Sales twin of ``po_release_strategy``.

Configuration
=============

1. *Sales > Configuration > Release Strategies*: create templates.

   * **Approval Rules**: stage (sequence), role, approver type (specific
     user or user group), minimum / maximum amount in company currency
     (maximum 0 = no limit). A rule applies when ``min <= amount <= max``.
     Rules sharing a stage are approved in parallel.
   * **Amount Basis**: total (taxes included) or untaxed amount. Orders in
     a foreign currency are converted to the company currency at the order
     date before rules are evaluated.
   * **After Final Approval**: confirm the order automatically, or give the
     salesperson a "Confirm Released Sales Order" activity.
   * **Approval Deadline**: days given to approvers on their activity.
   * **Locked Fields** (customer, order lines and total by default) and
     **Changes on Confirmed Orders** (see below).
2. *Sales > Configuration > Sales Teams*: set the **Release Strategy** of
   every team. This is the team's default strategy; it is never selected on
   quotations.
3. *Sales > Configuration > Settings > Release Strategies*: enable
   **Sales Release Strategies** (company specific, off by default). Enabling
   is refused while a sales team of the company (or a team without company)
   has no active strategy of that company.
4. Give the *Release Supervisor* right (Settings > Users, Sales Release
   Strategy privilege) to users allowed to bypass approvals.

Approvers must be internal users with Sales rights. Approvers limited to
their own documents can still open the orders they have to approve (read
only, through a dedicated record rule). Group members without Sales rights
are skipped; a rule with no eligible approver blocks the request with a
clear error.

Sales team and salesperson
==========================

Once enabled, the sales team and the salesperson are mandatory on quotations
and the team must be one the salesperson belongs to: active member or team
leader, which is Odoo's own definition (``crm.team._get_default_team_id``).
The team field only offers those teams, and the rule is enforced server side
on create, write and confirmation.

Website and portal flows (public/portal users) and superuser operations such
as crons are not blocked by the membership rule, so eCommerce carts keep
working with the website's sales team; release approvals still apply to
them.

Workflow
========

* **Confirm** a quotation: the strategy of its sales team is evaluated.

  * No rule covers the amount: the order is confirmed normally (release
    status *No Approval Needed*).
  * A rule covers the amount: the approvals are requested instead of
    confirming. On the form, **Confirm** is replaced by **Request
    Approval** and an information banner explains why.

* Requesting approval generates the approval lines and schedules a
  *Sales Release Approval* activity for each approver of the first stage
  (every eligible member for group rules).
* **Approve** (with optional notes) completes the approver's activity,
  removes the other group members' activities and logs the assignment
  date, approval date, approver and notes. The next stage starts when the
  current stage is fully approved.
* **Reject** (reason required) cancels the remaining lines and notifies the
  salesperson. Confirming or requesting approval again resubmits.
* **Reset Release** (salesperson, sales manager or supervisor) clears every
  approval and returns the order to *Not Submitted*.
* **Bypass Approval** (supervisor, reason required) marks the remaining
  lines as bypassed and applies the post-approval action.
* Release activities cannot be marked done or cancelled from the chatter.
* *Sales > Orders > Release Approvals* lists orders waiting for the current
  user.
* Cancelling an order clears its release; copies start from scratch.

Locked fields and re-evaluation
===============================

From submission (or from confirmation for orders that needed no approval),
the module keeps a snapshot of the locked fields plus the sales team and the
company. When one of them changes, the order is re-evaluated against the
strategy of its (possibly new) team:

* Quotation waiting for approval or released: approvals are cleared, the
  approvers are notified, and the approval is requested again if a rule
  still applies (otherwise the quotation can be confirmed directly).
* Confirmed order, policy *Reset*: approvals are cleared and requested
  again if a rule applies, while the order stays confirmed. A confirmed
  order that needed no approval and still needs none just refreshes its
  reference values.
* Confirmed order, policy *Block*: the change is refused (for an order that
  needed no approval, only when the change brings it within a rule).

Lines Odoo adds by itself after confirmation (down payments, re-invoiced
expenses, delivery costs) are outside the lock.

While a confirmed order waits for a new approval, or the new approval was
rejected, it cannot be invoiced (down payments included); automated invoicing
after an online payment skips it. The deliveries for added quantities are
created only once the order is approved again.

Switching the feature off cancels the approvals still pending (activities
removed, approval history kept) and creates any held deliveries.

Online signature and payment
============================

A quotation accepted online whose amount requires approval is held: it is
not confirmed, no confirmation mail is sent, and a note is logged. Once the
approval is complete and the strategy confirms automatically, the order is
confirmed and the confirmation mail is sent. Automatic invoicing after
online payment only invoices confirmed orders.

Translations
============

Arabic (``ar_001`` and ``ar``). The interface uses logical CSS properties,
so banners and hints mirror correctly in right-to-left languages.

Tests
=====

``odoo-bin -d <db> -i so_release_strategy --test-tags /so_release_strategy``
