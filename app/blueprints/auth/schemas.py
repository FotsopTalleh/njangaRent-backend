# ---------------------------------------------------------------------------
# blueprints/auth/schemas.py — Marshmallow validation schemas (NjangaRent)
# ---------------------------------------------------------------------------
from marshmallow import Schema, fields, validate, validates, ValidationError, pre_load


class NjangaRentSignupSchema(Schema):
    """Step-1 self-registration for students and landlords."""
    role     = fields.Str(required=True, validate=validate.OneOf(["student", "landlord"]))
    fullName = fields.Str(required=True, validate=validate.Length(min=2, max=120))
    email    = fields.Email(required=True)
    password = fields.Str(required=True, validate=validate.Length(min=8, max=128), load_only=True)
    phone    = fields.Str(load_default=None, validate=validate.Length(max=30))

    # Student-only (required when role=="student")
    university   = fields.Str(load_default="University of Buea", validate=validate.Length(max=200))
    program      = fields.Str(load_default=None, validate=validate.Length(max=200))
    matricNumber = fields.Str(load_default=None, validate=validate.Length(max=50))

    @validates("phone")
    def validate_phone_landlord(self, value):
        # Phone is required for landlords — enforced in the route, not here,
        # because we don't have cross-field context in marshmallow easily.
        pass


# Keep legacy SignupSchema as alias for backward compat (invite flow still uses it)
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
