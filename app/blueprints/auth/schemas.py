# ---------------------------------------------------------------------------
# blueprints/auth/schemas.py — Marshmallow validation schemas for auth
# ---------------------------------------------------------------------------
from marshmallow import Schema, fields, validate, validates, ValidationError


class SignupSchema(Schema):
    fullName = fields.Str(required=True, validate=validate.Length(min=2, max=120))
    email    = fields.Email(required=True)
    password = fields.Str(required=True, validate=validate.Length(min=8, max=128), load_only=True)
    phone    = fields.Str(load_default=None, validate=validate.Length(max=30))


class LoginSchema(Schema):
    email    = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True)


class GoogleAuthSchema(Schema):
    credential = fields.Str(required=True)


class ForgotPasswordSchema(Schema):
    email = fields.Email(required=True)


class ResetPasswordSchema(Schema):
    token       = fields.Str(required=True)
    newPassword = fields.Str(required=True, validate=validate.Length(min=8, max=128), load_only=True)


class InviteCompleteSchema(Schema):
    fullName = fields.Str(required=True, validate=validate.Length(min=2, max=120))
    password = fields.Str(required=True, validate=validate.Length(min=8, max=128), load_only=True)
