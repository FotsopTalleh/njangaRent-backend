# ---------------------------------------------------------------------------
# blueprints/tenants/schemas.py
# ---------------------------------------------------------------------------
from marshmallow import Schema, fields, validate


class InviteTenantSchema(Schema):
    email       = fields.Email(required=True)
    propertyId  = fields.Str(required=True)
    monthlyRent = fields.Float(required=True, validate=validate.Range(min=0))
    rentDueDay  = fields.Int(required=True, validate=validate.Range(min=1, max=28))
