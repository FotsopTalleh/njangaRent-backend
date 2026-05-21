# ---------------------------------------------------------------------------
# blueprints/receipts/schemas.py
# ---------------------------------------------------------------------------
from marshmallow import Schema, fields, validate

from app.utils.constants import PAYMENT_METHODS


class ManualReceiptSchema(Schema):
    """Validation schema for landlord-initiated (cash / in-person) receipt creation.

    The landlord provides payment details directly — no proof image is required.
    A payment record with status='approved' and isManual=True is created,
    followed by a receipt document.
    """

    tenantId        = fields.Str(required=True, metadata={"description": "Firestore tenant document ID"})
    amountPaid      = fields.Float(required=True, validate=validate.Range(min=0.01))
    paymentDate     = fields.Str(required=True, metadata={"description": "ISO date string: YYYY-MM-DD"})
    paymentMethod   = fields.Str(
        required=True,
        validate=validate.OneOf(PAYMENT_METHODS, error="Invalid payment method."),
    )
    referenceNumber = fields.Str(load_default=None, validate=validate.Length(max=200))
    notes           = fields.Str(load_default=None, validate=validate.Length(max=1000))
