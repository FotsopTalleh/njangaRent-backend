# ---------------------------------------------------------------------------
# blueprints/tenants/routes.py — /tenants/* endpoints
# ---------------------------------------------------------------------------
import logging
import os

from flask import Blueprint, g, request
from marshmallow import ValidationError as MarshmallowValidationError

from app.blueprints.tenants.schemas import InviteTenantSchema
from app.middleware.auth_middleware import require_role
from app.services.invite_service import InviteService
from app.services.payment_service import PaymentService
from app.services.property_service import PropertyService
from app.services.tenant_service import TenantService
from app.services.user_service import UserService
from app.utils.constants import (
    AUTH_FORBIDDEN,
    PROPERTY_NOT_FOUND,
    TENANT_NOT_FOUND,
    VALIDATION_ERROR,
)
from app.utils.pagination import paginate_query, parse_pagination_args
from app.utils.response import error_response, paginated_response, success_response

logger = logging.getLogger(__name__)
tenants_bp = Blueprint("tenants", __name__, url_prefix="/tenants")


def _validate(schema_cls, data: dict):
    try:
        return schema_cls().load(data)
    except MarshmallowValidationError as exc:
        field = next(iter(exc.messages), None)
        msg   = exc.messages[field][0] if isinstance(exc.messages.get(field), list) else str(exc.messages)
        raise _Fail(field, msg)


class _Fail(Exception):
    def __init__(self, field, message):
        self.field, self.message = field, message


# ── Endpoints ─────────────────────────────────────────────────────────────────


@tenants_bp.route("/me", methods=["GET"])
@require_role("tenant")
def get_my_tenant_record():
    """Return the tenant record for the currently authenticated tenant user."""
    tenant = TenantService.get_by_user_id(g.user["sub"])
    if not tenant:
        return error_response(TENANT_NOT_FOUND, "No active tenant record found for your account.", status_code=404)
    return success_response(data={"tenant": tenant})


@tenants_bp.route("", methods=["GET"])
@require_role("landlord")
def list_tenants():
    page, limit  = parse_pagination_args(request.args)
    property_id  = request.args.get("propertyId")
    status       = request.args.get("status")

    query = TenantService.list_for_landlord(g.user["sub"], property_id=property_id, status=status)
    docs, total  = paginate_query(query, page, limit)

    # Enrich each tenant record with the user's fullName and email so the
    # landlord-facing UI (e.g. manual receipt form) can show real names
    # instead of truncated Firestore document IDs.
    for doc in docs:
        user_id = doc.get("userId")
        if user_id:
            user = UserService.get_by_id(user_id) or {}
            doc["fullName"] = user.get("fullName", "")
            doc["email"]    = user.get("email", "")

    return paginated_response(docs, page, limit, total)


@tenants_bp.route("/invite", methods=["POST"])
@require_role("landlord")
def invite_tenant():
    try:
        data = _validate(InviteTenantSchema, request.get_json(silent=True) or {})
    except _Fail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    # Verify property belongs to this landlord
    prop = PropertyService.get_by_id(data["propertyId"])
    if not prop:
        return error_response(PROPERTY_NOT_FOUND, "Property not found.", status_code=404)
    if prop["landlordId"] != g.user["sub"]:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    try:
        raw_token, invitation_id = InviteService.create_invitation(
            email        = data["email"],
            landlord_id  = g.user["sub"],
            property_id  = data["propertyId"],
            monthly_rent = data["monthlyRent"],
            rent_due_day = data["rentDueDay"],
        )
    except ValueError as exc:
        return error_response(VALIDATION_ERROR, str(exc), status_code=409)

    # Send invitation email (non-blocking)
    _send_invite_email(data["email"], raw_token, prop["name"])

    response_data = {"invitationId": invitation_id}

    # In development, also return the raw token so it can be used directly
    # without needing to check email or have a frontend running.
    import os as _os
    if _os.environ.get("FLASK_ENV", "development") != "production":
        response_data["inviteToken"] = raw_token
        response_data["inviteUrl"] = f"{_os.environ.get('FRONTEND_URL', 'http://localhost:3000')}/invite?token={raw_token}"

    return success_response(data=response_data, status_code=201)


@tenants_bp.route("/<tenant_id>", methods=["GET"])
@require_role("landlord")
def get_tenant(tenant_id: str):
    tenant = TenantService.get_by_id(tenant_id)
    if not tenant:
        return error_response(TENANT_NOT_FOUND, "Tenant not found.", status_code=404)
    if tenant["landlordId"] != g.user["sub"]:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    user_profile = UserService.safe_dict(UserService.get_by_id(tenant["userId"]) or {})

    # Summary: last 5 payments
    payment_query = PaymentService.list_query(
        landlord_id=None, user_id=tenant["userId"]
    )
    from app.utils.pagination import paginate_query
    payments, _ = paginate_query(payment_query, page=1, limit=5)

    return success_response(data={
        "tenant":         tenant,
        "user":           user_profile,
        "recentPayments": payments,
    })


@tenants_bp.route("/<tenant_id>", methods=["DELETE"])
@require_role("landlord")
def remove_tenant(tenant_id: str):
    tenant = TenantService.get_by_id(tenant_id)
    if not tenant:
        return error_response(TENANT_NOT_FOUND, "Tenant not found.", status_code=404)
    if tenant["landlordId"] != g.user["sub"]:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    TenantService.remove(tenant_id)
    PropertyService.increment_tenant_count(tenant["propertyId"], delta=-1)
    return success_response(data=None, message="Tenant removed successfully.")


# ── Email helper ──────────────────────────────────────────────────────────────


def _send_invite_email(to_email: str, token: str, property_name: str) -> None:
    import threading

    def _send():
        try:
            frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
            invite_link  = f"{frontend_url}/invite?token={token}"
            provider     = os.environ.get("EMAIL_PROVIDER", "sendgrid").lower()
            from_name    = os.environ.get("MAIL_FROM_NAME", "MyTenant")
            subject      = f"You've been invited to join {property_name} on MyTenant"
            body         = (
                f"Hello,\n\nYou have been invited to manage your rent for {property_name} "
                f"digitally via MyTenant.\n\nClick the link below to create your account "
                f"(valid for 72 hours):\n\n{invite_link}\n\n"
                f"If you did not expect this invitation, please ignore this email."
            )

            if provider == "sendgrid":
                from_addr = os.environ.get("MAIL_FROM_ADDRESS", "noreply@mytenant.app")
                import sendgrid
                from sendgrid.helpers.mail import Content, From, Mail, To
                sg = sendgrid.SendGridAPIClient(api_key=os.environ.get("SENDGRID_API_KEY", ""))
                message = Mail(
                    from_email=From(from_addr, from_name),
                    to_emails=To(to_email),
                    subject=subject,
                    plain_text_content=Content("text/plain", body),
                )
                sg.send(message)
            else:
                # SMTP path — use MAIL_USERNAME as FROM so Gmail accepts the send.
                # Gmail SMTP rejects messages whose envelope-FROM doesn't match
                # the authenticated account.
                smtp_user = os.environ.get("MAIL_USERNAME", "")
                from_addr = smtp_user or os.environ.get("MAIL_FROM_ADDRESS", "noreply@mytenant.app")
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
                    server.login(smtp_user, os.environ.get("MAIL_PASSWORD", ""))
                    server.sendmail(from_addr, [to_email], msg.as_string())
            logger.info("Invite email sent to %s", to_email)
        except Exception as exc:
            logger.error("Failed to send invite email to %s: %s", to_email, exc)

    threading.Thread(target=_send, daemon=True).start()
