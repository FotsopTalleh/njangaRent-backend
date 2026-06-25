# ---------------------------------------------------------------------------
# blueprints/auth/routes.py — All /auth/* endpoints (NjangaRent extended)
# ---------------------------------------------------------------------------
import hashlib
import logging
import os
from datetime import datetime, timezone

import bcrypt
from flask import Blueprint, current_app, g, make_response, request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from marshmallow import ValidationError as MarshmallowValidationError

from app.blueprints.auth.schemas import (
    ForgotPasswordSchema,
    GoogleAuthSchema,
    InviteCompleteSchema,
    LoginSchema,
    NjangaRentSignupSchema,
    ResetPasswordSchema,
    SignupSchema,
)
from app.extensions import limiter
from app.middleware.auth_middleware import require_auth
from app.middleware.rate_limit_middleware import LIMIT_AUTH_ENDPOINTS, key_by_ip
from app.services.auth_service import AuthService
from app.services.cloudinary_service import CloudinaryService
from app.services.invite_service import InviteService
from app.services.property_service import PropertyService
from app.services.tenant_service import TenantService
from app.services.user_service import UserService
from app.utils.constants import (
    AUTH_EMAIL_EXISTS,
    AUTH_FORBIDDEN,
    AUTH_INVITE_EXPIRED,
    AUTH_INVITE_INVALID,
    AUTH_INVITE_USED,
    AUTH_INVALID_CREDENTIALS,
    AUTH_TOKEN_EXPIRED,
    AUTH_TOKEN_INVALID,
    ROLE_LANDLORD,
    ROLE_STUDENT,
    ROLE_TENANT,
    SERVER_ERROR,
    STATUS_PENDING,
    STATUS_ACTIVE,
    USER_NOT_FOUND,
    VALIDATION_ERROR,
)
from app.utils.response import error_response, success_response

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
_auth = AuthService()

# ── Helpers ──────────────────────────────────────────────────────────────────


def _issue_tokens_response(user: dict, status_code: int = 200):
    """Build a response with access token in body and refresh token as httpOnly cookie."""
    user_id = user["id"]
    access_token  = _auth.create_access_token(user_id, user["role"], user["email"])
    refresh_token = _auth.create_refresh_token(user_id)

    is_prod     = os.environ.get("FLASK_ENV", "development") == "production"
    same_site   = "Strict" if is_prod else "None"
    secure_flag = is_prod

    resp_data, http_code = success_response(
        data={"user": UserService.safe_dict(user), "accessToken": access_token},
        status_code=status_code,
    )
    response = make_response(resp_data, http_code)
    response.set_cookie(
        "refresh_token",
        refresh_token,
        max_age=_auth.refresh_expiry_seconds,
        httponly=True,
        secure=secure_flag,
        samesite=same_site,
        path="/",
    )
    return response


def _validate(schema_cls, data: dict):
    schema = schema_cls()
    try:
        return schema.load(data)
    except MarshmallowValidationError as exc:
        field = next(iter(exc.messages), None)
        msg = exc.messages[field][0] if isinstance(exc.messages.get(field), list) else str(exc.messages)
        from flask import abort
        from app.utils.response import error_response as _err
        # We return the response directly from routes, so raise a custom exception
        raise _ValidationFail(field, msg)


class _ValidationFail(Exception):
    def __init__(self, field, message):
        self.field = field
        self.message = message


# ── Routes ────────────────────────────────────────────────────────────────────


@auth_bp.route("/signup", methods=["POST"])
@limiter.limit(LIMIT_AUTH_ENDPOINTS, key_func=key_by_ip)
def signup():
    """NjangaRent self-registration endpoint.

    Accepts multipart/form-data (for file uploads) OR application/json (legacy).
    New registrations create accounts with status=PENDING — admin must approve.
    """
    # Parse form data (multipart) or JSON
    if request.content_type and "multipart" in request.content_type:
        raw = request.form.to_dict()
        files = request.files
    else:
        raw = request.get_json(silent=True) or {}
        files = {}

    try:
        data = _validate(NjangaRentSignupSchema, raw)
    except _ValidationFail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    role = data.get("role", ROLE_LANDLORD)

    # Landlord requires phone
    if role == ROLE_LANDLORD and not data.get("phone"):
        return error_response(VALIDATION_ERROR, "Phone number is required for landlord registration.", field="phone", status_code=422)

    # Student requires matric number
    if role == ROLE_STUDENT and not data.get("matricNumber"):
        return error_response(VALIDATION_ERROR, "Matriculation number is required for student registration.", field="matricNumber", status_code=422)

    # Check email uniqueness
    if UserService.get_by_email(data["email"]):
        return error_response(AUTH_EMAIL_EXISTS, "An account with this email already exists.", status_code=409)

    # Upload verification documents to Cloudinary
    verification = {}
    try:
        _cs = CloudinaryService()
        if role == ROLE_STUDENT:
            if "studentIdImage" in files:
                result = _cs.upload_image(
                    files["studentIdImage"],
                    folder="njangrent/verifications/students",
                )
                verification["studentIdUrl"] = result["secure_url"]
            if "admissionLetter" in files:
                result = _cs.upload_image(
                    files["admissionLetter"],
                    folder="njangrent/verifications/students",
                )
                verification["admissionLetterUrl"] = result["secure_url"]
        else:  # landlord
            if "nationalIdFront" in files:
                result = _cs.upload_image(
                    files["nationalIdFront"],
                    folder="njangrent/verifications/landlords",
                )
                verification["nationalIdFrontUrl"] = result["secure_url"]
            if "nationalIdBack" in files:
                result = _cs.upload_image(
                    files["nationalIdBack"],
                    folder="njangrent/verifications/landlords",
                )
                verification["nationalIdBackUrl"] = result["secure_url"]
            if "ownershipDoc" in files:
                result = _cs.upload_image(
                    files["ownershipDoc"],
                    folder="njangrent/verifications/landlords",
                )
                verification["ownershipDocUrl"] = result["secure_url"]
    except Exception as exc:
        logger.error("Verification document upload failed during signup: %s", exc)
        # Continue without docs — admin will request them

    # Hash password
    pw_hash = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt(rounds=12)).decode()

    user = UserService.create(
        email         = data["email"],
        full_name     = data["fullName"],
        role          = role,
        password_hash = pw_hash,
        phone         = data.get("phone"),
        status        = STATUS_PENDING,  # All new accounts start as PENDING
        university    = data.get("university") if role == ROLE_STUDENT else None,
        program       = data.get("program") if role == ROLE_STUDENT else None,
        matric_number = data.get("matricNumber") if role == ROLE_STUDENT else None,
        verification  = verification if verification else None,
    )

    # Return user data without issuing tokens (PENDING cannot access protected routes)
    from app.utils.response import success_response as _success
    return _success(
        data={
            "user": UserService.safe_dict(user),
            "pendingVerification": True,
            "message": "Account created. Please wait for admin approval before logging in.",
        },
        status_code=201,
    )


@auth_bp.route("/login", methods=["POST"])
@limiter.limit(LIMIT_AUTH_ENDPOINTS, key_func=key_by_ip)
def login():
    try:
        data = _validate(LoginSchema, request.get_json(silent=True) or {})
    except _ValidationFail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    user = UserService.get_by_email(data["email"])
    if not user or not user.get("passwordHash"):
        return error_response(AUTH_INVALID_CREDENTIALS, "Invalid email or password.", status_code=401)

    if not bcrypt.checkpw(data["password"].encode(), user["passwordHash"].encode()):
        return error_response(AUTH_INVALID_CREDENTIALS, "Invalid email or password.", status_code=401)

    # PENDING / REJECTED / BANNED — return user info with status flag (no tokens)
    account_status = user.get("status", STATUS_ACTIVE)
    if account_status == STATUS_PENDING:
        return success_response(
            data={
                "user": UserService.safe_dict(user),
                "pendingVerification": True,
                "accessToken": None,
            },
            message="Your account is pending admin verification.",
        )
    if account_status in ("REJECTED", "BANNED"):
        return success_response(
            data={
                "user": UserService.safe_dict(user),
                "pendingVerification": True,
                "accountStatus": account_status,
                "accessToken": None,
            },
            message=f"Account {account_status.lower()}. Contact support for assistance.",
        )

    return _issue_tokens_response(user)


@auth_bp.route("/google", methods=["POST"])
@limiter.limit(LIMIT_AUTH_ENDPOINTS, key_func=key_by_ip)
def google_auth():
    try:
        data = _validate(GoogleAuthSchema, request.get_json(silent=True) or {})
    except _ValidationFail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    try:
        id_info = id_token.verify_oauth2_token(
            data["credential"],
            google_requests.Request(),
            google_client_id,
        )
    except ValueError as exc:
        logger.warning("Google token verification failed: %s", exc)
        return error_response(AUTH_TOKEN_INVALID, "Invalid Google credential.", status_code=401)

    google_id = id_info["sub"]
    email     = id_info.get("email", "").lower().strip()
    full_name = id_info.get("name", "")

    # Upsert user
    user = UserService.get_by_email(email)
    if user:
        if not user.get("googleId"):
            UserService.update(user["id"], {"googleId": google_id})
            user["googleId"] = google_id
    else:
        user = UserService.create(
            email     = email,
            full_name = full_name,
            role      = ROLE_LANDLORD,
            google_id = google_id,
        )

    return _issue_tokens_response(user)


@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        return error_response(AUTH_TOKEN_INVALID, "Refresh token cookie is missing.", status_code=401)

    try:
        new_refresh_token, old_payload = _auth.rotate_refresh_token(refresh_token)
    except AuthService.TokenExpiredError:
        return error_response(AUTH_TOKEN_EXPIRED, "Refresh token has expired. Please log in again.", status_code=401)
    except AuthService.TokenInvalidError as exc:
        return error_response(AUTH_TOKEN_INVALID, str(exc), status_code=401)

    user_id = old_payload["sub"]
    user = UserService.get_by_id(user_id)
    if not user:
        return error_response(USER_NOT_FOUND, "User not found.", status_code=401)

    access_token = _auth.create_access_token(user_id, user["role"], user["email"])

    is_prod    = os.environ.get("FLASK_ENV", "development") == "production"
    same_site  = "Strict" if is_prod else "None"
    secure_flag = is_prod

    resp_data, http_code = success_response(data={"accessToken": access_token})
    response = make_response(resp_data, http_code)
    response.set_cookie(
        "refresh_token",
        new_refresh_token,
        max_age=_auth.refresh_expiry_seconds,
        httponly=True,
        secure=secure_flag,
        samesite=same_site,
        path="/",
    )
    return response


@auth_bp.route("/logout", methods=["POST"])
def logout():
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        _auth.blacklist_from_token_string(refresh_token)

    is_prod = os.environ.get("FLASK_ENV", "development") == "production"
    resp_data, http_code = success_response(data=None, message="Logged out successfully.")
    response = make_response(resp_data, http_code)
    response.set_cookie(
        "refresh_token", "", max_age=0, httponly=True,
        secure=is_prod, samesite="Strict" if is_prod else "None", path="/",
    )
    return response


@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit(LIMIT_AUTH_ENDPOINTS, key_func=key_by_ip)
def forgot_password():
    try:
        data = _validate(ForgotPasswordSchema, request.get_json(silent=True) or {})
    except _ValidationFail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    # Always return success to prevent email enumeration
    user = UserService.get_by_email(data["email"])
    if user:
        from datetime import timedelta
        raw_token, token_hash = _auth.create_reset_token(user["id"], expiry_minutes=15)
        exp = datetime.now(timezone.utc) + timedelta(minutes=15)
        UserService.set_reset_token(user["id"], token_hash, exp)

        # Send email (non-blocking, best-effort)
        _send_reset_email(user["email"], raw_token)

    return success_response(data=None, message="If that email exists, a reset link has been sent.")


@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    try:
        data = _validate(ResetPasswordSchema, request.get_json(silent=True) or {})
    except _ValidationFail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    try:
        payload = _auth.verify_reset_token(data["token"])
    except AuthService.TokenExpiredError:
        return error_response(AUTH_TOKEN_EXPIRED, "Password reset link has expired.", status_code=400)
    except AuthService.TokenInvalidError:
        return error_response(AUTH_TOKEN_INVALID, "Invalid password reset token.", status_code=400)

    user = UserService.get_by_id(payload["sub"])
    if not user:
        return error_response(USER_NOT_FOUND, "User not found.", status_code=404)

    # Verify hash matches stored value
    token_hash = hashlib.sha256(data["token"].encode()).hexdigest()
    if user.get("resetTokenHash") != token_hash:
        return error_response(AUTH_TOKEN_INVALID, "Invalid or already used reset token.", status_code=400)

    pw_hash = bcrypt.hashpw(data["newPassword"].encode(), bcrypt.gensalt(rounds=12)).decode()
    UserService.update(user["id"], {"passwordHash": pw_hash})
    UserService.clear_reset_token(user["id"])

    return success_response(data=None, message="Password updated successfully.")


@auth_bp.route("/invite/<token>/verify", methods=["GET"])
def verify_invite(token: str):
    try:
        payload, invitation = InviteService.verify_invitation(token)
    except AuthService.TokenExpiredError:
        return error_response(AUTH_INVITE_EXPIRED, "Invitation has expired.", status_code=400)
    except AuthService.TokenInvalidError:
        return error_response(AUTH_INVITE_INVALID, "Invalid invitation token.", status_code=400)
    except ValueError as exc:
        msg = str(exc)
        if "expired" in msg.lower():
            return error_response(AUTH_INVITE_EXPIRED, msg, status_code=400)
        if "used" in msg.lower():
            return error_response(AUTH_INVITE_USED, msg, status_code=400)
        return error_response(AUTH_INVITE_INVALID, msg, status_code=400)

    # Fetch property and landlord name for preview
    from app.services.property_service import PropertyService
    prop = PropertyService.get_by_id(payload.get("propertyId", ""))
    landlord = UserService.get_by_id(payload.get("landlordId", ""))

    return success_response(data={
        "email":        payload.get("email"),
        "propertyName": prop["name"] if prop else "",
        "landlordName": landlord["fullName"] if landlord else "",
        "monthlyRent":  payload.get("monthlyRent"),
    })


@auth_bp.route("/invite/<token>/complete", methods=["POST"])
def complete_invite(token: str):
    try:
        data = _validate(InviteCompleteSchema, request.get_json(silent=True) or {})
    except _ValidationFail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    try:
        payload, invitation = InviteService.verify_invitation(token)
    except AuthService.TokenExpiredError:
        return error_response(AUTH_INVITE_EXPIRED, "Invitation has expired.", status_code=400)
    except AuthService.TokenInvalidError:
        return error_response(AUTH_INVITE_INVALID, "Invalid invitation token.", status_code=400)
    except ValueError as exc:
        msg = str(exc)
        code = AUTH_INVITE_USED if "used" in msg.lower() else AUTH_INVITE_INVALID
        return error_response(code, msg, status_code=400)

    email    = payload["email"]
    existing = UserService.get_by_email(email)
    if existing:
        return error_response(AUTH_EMAIL_EXISTS, "An account with this email already exists.", status_code=409)

    pw_hash = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt(rounds=12)).decode()
    user = UserService.create(
        email         = email,
        full_name     = data["fullName"],
        role          = ROLE_TENANT,
        password_hash = pw_hash,
    )

    TenantService.create(
        user_id      = user["id"],
        landlord_id  = payload["landlordId"],
        property_id  = payload["propertyId"],
        monthly_rent = payload["monthlyRent"],
        rent_due_day = payload["rentDueDay"],
    )

    # Increment property tenant count
    PropertyService.increment_tenant_count(payload["propertyId"])

    InviteService.accept_invitation(invitation["id"])

    return _issue_tokens_response(user, status_code=201)


# ── Email helper (non-blocking) ───────────────────────────────────────────────


def _send_reset_email(to_email: str, token: str) -> None:
    """Send password reset email (SendGrid or SMTP). Best-effort, non-blocking."""
    import threading

    def _send():
        try:
            frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
            reset_link   = f"{frontend_url}/reset-password?token={token}"
            provider     = os.environ.get("EMAIL_PROVIDER", "sendgrid").lower()
            from_addr    = os.environ.get("MAIL_FROM_ADDRESS", "noreply@mytenant.app")
            from_name    = os.environ.get("MAIL_FROM_NAME", "MyTenant")
            subject      = "Reset your MyTenant password"
            body         = (
                f"Hello,\n\nClick the link below to reset your password (valid for 15 minutes):\n\n"
                f"{reset_link}\n\nIf you did not request this, ignore this email."
            )

            if provider == "sendgrid":
                import sendgrid
                from sendgrid.helpers.mail import Mail, To, From, Content
                sg = sendgrid.SendGridAPIClient(api_key=os.environ.get("SENDGRID_API_KEY", ""))
                message = Mail(
                    from_email=From(from_addr, from_name),
                    to_emails=To(to_email),
                    subject=subject,
                    plain_text_content=Content("text/plain", body),
                )
                sg.send(message)
            else:
                # SMTP fallback
                import smtplib
                from email.mime.text import MIMEText
                msg = MIMEText(body)
                msg["Subject"] = subject
                msg["From"]    = f"{from_name} <{from_addr}>"
                msg["To"]      = to_email
                with smtplib.SMTP(
                    os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
                    int(os.environ.get("MAIL_PORT", 587)),
                ) as server:
                    if os.environ.get("MAIL_USE_TLS", "true").lower() == "true":
                        server.starttls()
                    server.login(
                        os.environ.get("MAIL_USERNAME", ""),
                        os.environ.get("MAIL_PASSWORD", ""),
                    )
                    server.sendmail(from_addr, [to_email], msg.as_string())
            logger.info("Password reset email sent to %s", to_email)
        except Exception as exc:
            logger.error("Failed to send password reset email to %s: %s", to_email, exc)

    threading.Thread(target=_send, daemon=True).start()


# ── Internal endpoint for n8n ────────────────────────────────────────────────


@auth_bp.route("/internal/landlord/<landlord_id>/phone", methods=["GET"])
def get_landlord_phone(landlord_id: str):
    """Internal-only endpoint: n8n calls this to fetch a landlord's phone number.

    Authentication: X-Internal-Secret header (same value as N8N_WEBHOOK_SECRET).
    NOT protected by JWT — only reachable inside the Docker network.
    """
    secret = request.headers.get("X-Internal-Secret", "")
    expected = os.environ.get("N8N_WEBHOOK_SECRET", "")
    if not expected or secret != expected:
        return error_response(AUTH_FORBIDDEN, "Forbidden.", status_code=403)

    user = UserService.get_by_id(landlord_id)
    if not user:
        return error_response(USER_NOT_FOUND, "Landlord not found.", status_code=404)

    return success_response(data={
        "phone":    user.get("phone", ""),
        "fullName": user.get("fullName", ""),
        "email":    user.get("email", ""),
    })
