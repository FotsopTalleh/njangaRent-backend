# ---------------------------------------------------------------------------
# blueprints/notifications/schemas.py
# ---------------------------------------------------------------------------
from marshmallow import Schema, fields, validate


class SubscribeFcmSchema(Schema):
    fcmToken   = fields.Str(required=True)
    deviceType = fields.Str(required=True, validate=validate.OneOf(["web", "android", "ios", "other"]))


class UnsubscribeFcmSchema(Schema):
    fcmToken = fields.Str(required=True)
