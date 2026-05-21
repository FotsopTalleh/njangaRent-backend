# ---------------------------------------------------------------------------
# blueprints/receipts/routes.py — /receipts/* endpoints
# ---------------------------------------------------------------------------
import logging

from flask import Blueprint, Response, g, request
from jinja2 import Environment, FileSystemLoader, select_autoescape
import os

from app.extensions import get_db
from app.middleware.auth_middleware import require_auth, require_role
from app.utils.constants import AUTH_FORBIDDEN, RECEIPT_NOT_FOUND, VALIDATION_ERROR
from app.utils.pagination import paginate_query, parse_pagination_args
from app.utils.response import error_response, paginated_response, success_response

logger = logging.getLogger(__name__)
receipts_bp = Blueprint("receipts", __name__, url_prefix="/receipts")

RECEIPTS_COLLECTION = "receipts"

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "templates", "receipts"
)
_jinja_env = None


def _get_jinja_env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(_TEMPLATE_DIR),
            autoescape=select_autoescape(["html"]),
        )
    return _jinja_env


def _db():
    return get_db()


def _receipt_owned_by(receipt: dict) -> bool:
    """
    Return True if the current authenticated user owns this receipt.

    CRITICAL: For tenants, g.user["sub"] is the Firebase Auth UID, but
    receipts store tenantId as the Firestore *tenant document* ID — a
    completely different identifier.  We must resolve the mapping via
    TenantService before comparing.
    """
    user = g.user
    if user["role"] == "landlord":
        return receipt.get("landlordId") == user["sub"]

    # Tenant path: look up the Firestore tenant doc by Firebase UID, then compare.
    from app.services.tenant_service import TenantService
    tenant = TenantService.get_by_user_id(user["sub"])
    if not tenant:
        logger.warning(
            "_receipt_owned_by: no active tenant record for user_id=%s", user["sub"]
        )
        return False
    return receipt.get("tenantId") == tenant["id"]


def _build_query(user):
    query = _db().collection(RECEIPTS_COLLECTION)
    if user["role"] == "landlord":
        query = query.where("landlordId", "==", user["sub"])
    else:
        # Tenant's userId is stored on the tenant doc; receipts use tenantId (tenant doc ID).
        from app.services.tenant_service import TenantService
        tenant = TenantService.get_by_user_id(user["sub"])
        tenant_id = tenant["id"] if tenant else "__none__"
        query = query.where("tenantId", "==", tenant_id)
    # Sorting handled in Python by paginate_query — no composite index needed.
    return query


def _render_receipt_html(receipt: dict) -> str:
    """Render the receipt.html Jinja2 template using Firestore receipt data.

    Handles Firestore DatetimeWithNanoseconds objects safely — they are a
    datetime subclass so they support .strftime(), but older stored receipts
    may have them for fields we assumed were strings (e.g. paymentDate).
    """
    from datetime import datetime, timezone

    # ── generatedAt ──────────────────────────────────────────────────────────
    generated_at = receipt.get("generatedAt")
    if hasattr(generated_at, "strftime"):
        generated_at_str = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    elif isinstance(generated_at, str) and generated_at:
        generated_at_str = generated_at
    else:
        generated_at_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── paymentDate ───────────────────────────────────────────────────────────
    # Stored as a string "YYYY-MM-DD" by payment_service, but guard against
    # Firestore Timestamp objects in legacy data.
    payment_date = receipt.get("paymentDate", "")
    if hasattr(payment_date, "strftime"):
        payment_date = payment_date.strftime("%Y-%m-%d")
    elif not isinstance(payment_date, str):
        payment_date = str(payment_date)

    # ── amountPaid ────────────────────────────────────────────────────────────
    amount_paid = receipt.get("amountPaid") or receipt.get("amountClaimed") or 0
    try:
        amount_paid = float(amount_paid)
    except (TypeError, ValueError):
        amount_paid = 0.0

    template = _get_jinja_env().get_template("receipt.html")
    return template.render(
        tenantName      = receipt.get("tenantName", ""),
        landlordName    = receipt.get("landlordName", ""),
        propertyName    = receipt.get("propertyName", ""),
        propertyAddress = receipt.get("propertyAddress", ""),
        amountPaid      = amount_paid,
        amountClaimed   = receipt.get("amountClaimed"),
        amountExtracted = receipt.get("amountExtracted"),
        paymentDate     = payment_date,
        paymentMethod   = receipt.get("paymentMethod", ""),
        referenceNumber = receipt.get("referenceNumber", ""),
        receiptNumber   = receipt.get("receiptNumber", ""),
        generatedAt     = generated_at_str,
        isManual        = receipt.get("isManual", False),
    )



# ── Endpoints ─────────────────────────────────────────────────────────────────


@receipts_bp.route("", methods=["GET"])
@require_auth
def list_receipts():
    page, limit = parse_pagination_args(request.args)
    property_id = request.args.get("propertyId")
    query = _build_query(g.user)
    if property_id:
        query = query.where("propertyId", "==", property_id)
    docs, total = paginate_query(query, page, limit)
    return paginated_response(docs, page, limit, total)


@receipts_bp.route("/<receipt_id>", methods=["GET"])
@require_auth
def get_receipt(receipt_id: str):
    doc = _db().collection(RECEIPTS_COLLECTION).document(receipt_id).get()
    if not doc.exists:
        return error_response(RECEIPT_NOT_FOUND, "Receipt not found.", status_code=404)
    receipt = doc.to_dict()
    receipt["id"] = doc.id
    if not _receipt_owned_by(receipt):
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)
    return success_response(data=receipt)


@receipts_bp.route("/<receipt_id>/download", methods=["GET"])
@require_auth
def download_receipt(receipt_id: str):
    """Return the Cloudinary PDF URL (or signal hasPreview when PDF unavailable)."""
    doc = _db().collection(RECEIPTS_COLLECTION).document(receipt_id).get()
    if not doc.exists:
        return error_response(RECEIPT_NOT_FOUND, "Receipt not found.", status_code=404)
    receipt = doc.to_dict()
    receipt["id"] = doc.id
    if not _receipt_owned_by(receipt):
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    pdf_url = receipt.get("pdfUrl", "")
    return success_response(data={
        "pdfUrl":     pdf_url,
        # hasPreview=True tells the frontend to use /receipts/<id>/preview
        # when pdfUrl is empty (WeasyPrint/GTK not available in dev).
        "hasPreview": True,
    })


@receipts_bp.route("/<receipt_id>/preview", methods=["GET"])
@require_auth
def preview_receipt(receipt_id: str):
    """Render the receipt as a printable HTML page (no PDF required).

    The frontend fetches this with axios (auth header included), converts the
    response to a Blob URL, and opens it in a new tab.  Users can Ctrl+P → Save
    as PDF from the browser — no WeasyPrint/GTK dependency required.
    """
    doc = _db().collection(RECEIPTS_COLLECTION).document(receipt_id).get()
    if not doc.exists:
        return error_response(RECEIPT_NOT_FOUND, "Receipt not found.", status_code=404)
    receipt = doc.to_dict()
    receipt["id"] = doc.id
    if not _receipt_owned_by(receipt):
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    try:
        html_content = _render_receipt_html(receipt)
    except Exception as exc:
        logger.exception("Failed to render receipt HTML for id=%s: %s", receipt_id, exc)
        return error_response(
            "RECEIPT_RENDER_ERROR",
            "Could not render receipt.",
            status_code=500,
        )

    return Response(html_content, mimetype="text/html; charset=utf-8")


@receipts_bp.route("/manual", methods=["POST"])
@require_role("landlord")
def create_manual_receipt():
    """Landlord creates a receipt directly for a cash / in-person payment.

    This is the "hand payment" flow: the landlord records the payment amount
    and generates a receipt without requiring the tenant to upload a proof
    image first.  A payment record with status='approved' and isManual=True is
    created alongside the receipt, and the tenant receives an in-app
    notification with the receipt details.
    """
    from marshmallow import ValidationError as MarshmallowValidationError
    from app.blueprints.receipts.schemas import ManualReceiptSchema
    from app.services.receipt_service import ReceiptService
    from app.services.tenant_service import TenantService

    try:
        data = ManualReceiptSchema().load(request.get_json(silent=True) or {})
    except MarshmallowValidationError as exc:
        field = next(iter(exc.messages), None)
        msg = (
            exc.messages[field][0]
            if isinstance(exc.messages.get(field), list)
            else str(exc.messages)
        )
        return error_response(VALIDATION_ERROR, msg, field=field, status_code=422)

    # Verify the tenant belongs to this landlord
    tenant = TenantService.get_by_id(data["tenantId"])
    if not tenant or tenant.get("landlordId") != g.user["sub"]:
        return error_response(
            AUTH_FORBIDDEN,
            "Tenant not found or does not belong to your account.",
            status_code=403,
        )
    if tenant.get("status") != "active":
        return error_response(
            VALIDATION_ERROR,
            "Cannot create a receipt for an inactive tenant.",
            status_code=422,
        )

    try:
        receipt = ReceiptService.generate_manual_receipt(
            landlord_id      = g.user["sub"],
            tenant_id        = data["tenantId"],
            amount_paid      = data["amountPaid"],
            payment_date     = data["paymentDate"],
            payment_method   = data["paymentMethod"],
            reference_number = data.get("referenceNumber"),
            notes            = data.get("notes"),
        )
    except ValueError as exc:
        return error_response(VALIDATION_ERROR, str(exc), status_code=422)
    except Exception:
        logger.exception(
            "Manual receipt generation failed for landlord_id=%s tenant_id=%s",
            g.user["sub"], data.get("tenantId"),
        )
        return error_response(
            "RECEIPT_ERROR", "Could not generate receipt.", status_code=500
        )

    # Notify the tenant about the issued receipt
    try:
        from app.services.notification_service import NotificationService
        from app.services.property_service import PropertyService
        prop = PropertyService.get_by_id(tenant["propertyId"])
        property_name = prop["name"] if prop else "your property"
        NotificationService.notify_payment_approved(
            tenant_id      = tenant["userId"],
            payment_id     = receipt.get("paymentId", ""),
            property_name  = property_name,
            receipt_number = receipt["receiptNumber"],
            receipt_id     = receipt["id"],
        )
    except Exception as exc:
        logger.error(
            "Failed to notify tenant after manual receipt id=%s: %s",
            receipt.get("id"), exc,
        )

    return success_response(data=receipt, status_code=201)

