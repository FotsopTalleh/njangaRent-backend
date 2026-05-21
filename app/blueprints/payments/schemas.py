# ---------------------------------------------------------------------------
# blueprints/payments/schemas.py
# ---------------------------------------------------------------------------
from marshmallow import Schema, fields, validate

from app.utils.constants import PAYMENT_METHODS


class ApprovePaymentSchema(Schema):
    note = fields.Str(load_default=None, validate=validate.Length(max=1000))


class RejectPaymentSchema(Schema):
    rejectionReason = fields.Str(required=True, validate=validate.Length(min=1, max=1000))
