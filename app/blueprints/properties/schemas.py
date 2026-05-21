# ---------------------------------------------------------------------------
# blueprints/properties/schemas.py
# ---------------------------------------------------------------------------
from marshmallow import Schema, fields, validate

from app.utils.constants import PROPERTY_TYPES


class CreatePropertySchema(Schema):
    name         = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    address      = fields.Str(required=True, validate=validate.Length(min=1, max=500))
    description  = fields.Str(load_default="", validate=validate.Length(max=2000))
    propertyType = fields.Str(required=True, validate=validate.OneOf(PROPERTY_TYPES))
    monthlyRent  = fields.Float(required=True, validate=validate.Range(min=0))


class UpdatePropertySchema(Schema):
    name         = fields.Str(validate=validate.Length(min=1, max=200))
    address      = fields.Str(validate=validate.Length(min=1, max=500))
    description  = fields.Str(validate=validate.Length(max=2000))
    propertyType = fields.Str(validate=validate.OneOf(PROPERTY_TYPES))
    monthlyRent  = fields.Float(validate=validate.Range(min=0))
