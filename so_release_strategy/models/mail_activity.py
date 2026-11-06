# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

RELEASE_CTX = 'so_release_internal'


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    so_release_line_id = fields.Many2one(
        'sale.order.release.line', string='Sales Release Approval Line',
        ondelete='cascade', index=True, readonly=True)

    def _so_release_guard(self):
        """Release activities are driven by the Approve / Reject buttons only,
        so that the approval log and the activity always stay in sync."""
        if self.env.context.get(RELEASE_CTX) or self.env.su:
            return
        if self.filtered(lambda a: a.so_release_line_id.state == 'pending'):
            raise UserError(_(
                'This activity belongs to a sales release strategy. Use the '
                '"Approve" or "Reject" buttons on the sales order instead.'))

    def _action_done(self, feedback=False, attachment_ids=None):
        self._so_release_guard()
        return super()._action_done(feedback=feedback, attachment_ids=attachment_ids)

    def unlink(self):
        self._so_release_guard()
        return super().unlink()
