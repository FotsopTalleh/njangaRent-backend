# ---------------------------------------------------------------------------
# blueprints/payments/routes.py — /payments/* endpoints
# ---------------------------------------------------------------------------
import logging

from flask import Blueprint, g, request
from marshmallow import ValidationError as MarshmallowValidationError

from app.blueprints.payments.schemas import ApprovePaymentSchema, RejectPaymentSchema
from app.extensions import get_db, limiter
from app.middleware.auth_middleware import require_auth, require_role
from app.middleware.rate_limit_middleware import LIMIT_UPLOAD_ENDPOINT, key_by_jwt_sub
from app.services.cloudinary_service import CloudinaryService
from app.services.notification_service import NotificationService
from app.services.ocr_service import OcrService
from app.services.payment_service import PaymentService
from app.services.tenant_service import TenantService
from app.services.user_service import UserService
from app.utils.constants import (
    AUTH_FORBIDDEN,
    PAYMENT_ALREADY_REVIEWED,
    PAYMENT_NOT_FOUND,
    VALIDATION_ERROR,
)
from app.utils.pagination import paginate_query, parse_pagination_args
from app.utils.response import error_response, paginated_response, success_response
from app.utils.validators import ValidationError as FileValidationError
from app.utils.validators import validate_upload_file

logger = logging.getLogger(__name__)
payments_bp = Blueprint("payments", __name__, url_prefix="/payments")


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


def _payment_owned_by(payment: dict) -> bool:
    """Return True if the current user owns this payment (role-aware)."""
    user = g.user
    if user["role"] == "landlord":
        return payment.get("landlordId") == user["sub"]
    return payment.get("userId") == user["sub"]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@payments_bp.route("", methods=["POST"])
@require_role("tenant")
@limiter.limit(LIMIT_UPLOAD_ENDPOINT, key_func=key_by_jwt_sub)
def submit_payment():
    """Multipart form-data upload: proof file + payment fields."""
    # Validate file first
    proof_file = request.files.get("proofFile")
    try:
        validate_upload_file(proof_file)
    except FileValidationError as exc:
        return error_response(exc.code, exc.message, field=exc.field, status_code=422)

    # Validate form fields
    from app.utils.constants import PAYMENT_METHODS
    amount_claimed   = request.form.get("amountClaimed")
    payment_date     = request.form.get("paymentDate")
    payment_method   = request.form.get("paymentMethod")
    reference_number = request.form.get("referenceNumber")
    notes            = request.form.get("notes")

    errors = {}
    if not amount_claimed:
        errors["amountClaimed"] = "Required."
    if not payment_date:
        errors["paymentDate"] = "Required."
    if not payment_method or payment_method not in PAYMENT_METHODS:
        errors["paymentMethod"] = f"Must be one of: {', '.join(PAYMENT_METHODS)}."
    if errors:
        first_field = next(iter(errors))
        return error_response(VALIDATION_ERROR, errors[first_field], field=first_field, status_code=422)

    try:
        amount_claimed = float(amount_claimed)
    except (TypeError, ValueError):
        return error_response(VALIDATION_ERROR, "amountClaimed must be a number.", field="amountClaimed", status_code=422)

    # Identify the tenant document for the current user
    tenant = TenantService.get_by_user_id(g.user["sub"])
    if not tenant:
        return error_response(AUTH_FORBIDDEN, "No active tenant record found for your account.", status_code=403)

    # Upload to Cloudinary
    upload_result = CloudinaryService.upload_payment_proof(
        file        = proof_file,
        landlord_id = tenant["landlordId"],
        tenant_id   = tenant["id"],
    )

    # Create Firestore payment doc
    payment = PaymentService.create(
        tenant_id        = tenant["id"],
        user_id          = g.user["sub"],
        landlord_id      = tenant["landlordId"],
        property_id      = tenant["propertyId"],
        amount_claimed   = amount_claimed,
        payment_date     = payment_date,
        payment_method   = payment_method,
        proof_image_url  = upload_result["secure_url"],
        proof_public_id  = upload_result["public_id"],
        reference_number = reference_number,
        notes            = notes,
    )

    # Notify landlord (in-app + FCM)
    tenant_user = UserService.get_by_id(g.user["sub"])
    tenant_name = tenant_user.get("fullName", "A tenant") if tenant_user else "A tenant"
    NotificationService.notify_payment_submitted(
        landlord_id = tenant["landlordId"],
        payment_id  = payment["id"],
        tenant_name = tenant_name,
    )

    # Fetch landlord contact details for the n8n message payload
    landlord_user = UserService.get_by_id(tenant["landlordId"])
    landlord_name  = landlord_user.get("fullName", "")  if landlord_user else ""
    landlord_phone = landlord_user.get("phone", "")     if landlord_user else ""
    landlord_email = landlord_user.get("email", "")     if landlord_user else ""

    # Fetch property name for the n8n message context
    from app.services.property_service import PropertyService
    prop_doc      = PropertyService.get_by_id(tenant["propertyId"])
    property_name = prop_doc["name"] if prop_doc else ""

    # Trigger n8n OCR + messaging (fire-and-forget).
    # n8n will:
    #   1. OCR the proof image to extract the payment amount.
    #   2. Send a message to the landlord with what it extracted.
    #   3. POST back to callbackUrl with { paymentId, extractedAmount, ocrSuccess }.
    # The extracted amount is stored on the payment and used as amountPaid on the receipt.
    OcrService.trigger_ocr(
        payment_id      = payment["id"],
        proof_image_url = upload_result["secure_url"],
        landlord_id     = tenant["landlordId"],
        tenant_id       = tenant["id"],
        landlord_name   = landlord_name,
        landlord_phone  = landlord_phone,
        landlord_email  = landlord_email,
        tenant_name     = tenant_name,
        amount_claimed  = amount_claimed,
        payment_date    = payment_date,
        payment_method  = payment_method,
        property_name   = property_name,
    )

    return success_response(
        data={"paymentId": payment["id"], "proofImageUrl": upload_result["secure_url"]},
        status_code=201,
    )



@payments_bp.route("/calendar", methods=["GET"])
@require_auth
def payment_calendar():
    """Return 12-month payment summary for a tenant.

    Query params:
        tenantId  — required for landlords; ignored for tenants (own data).
        year      — YYYY (defaults to current year).

    Response data:
        months: list of 12 objects {
            month      — "YYYY-MM",
            totalPaid  — float,
            monthlyRent— float,
            percentage — float (0-100+),
            status     — "paid" | "partial" | "unpaid",
            payments   — list of payment summaries,
        }
    """
    from datetime import date
    from app.services.tenant_service import TenantService

    user = g.user
    year_str = request.args.get("year", str(date.today().year))
    try:
        year = int(year_str)
    except ValueError:
        return error_response(VALIDATION_ERROR, "year must be a 4-digit integer.", status_code=422)

    # ── Resolve tenant record ─────────────────────────────────────────────────
    if user["role"] == "landlord":
        tenant_id = request.args.get("tenantId", "").strip()
        if not tenant_id:
            return error_response(VALIDATION_ERROR, "tenantId is required.", field="tenantId", status_code=422)
        tenant = TenantService.get_by_id(tenant_id)
        if not tenant or tenant.get("landlordId") != user["sub"]:
            return error_response(AUTH_FORBIDDEN, "Tenant not found or not yours.", status_code=403)
    else:
        # Tenant can only see their own calendar
        tenant = TenantService.get_by_user_id(user["sub"])
        if not tenant:
            return error_response(AUTH_FORBIDDEN, "No active tenant record found.", status_code=403)
        tenant_id = tenant["id"]

    monthly_rent = float(tenant.get("monthlyRent", 0) or 0)

    # ── Fetch all payments for this tenant, filter approved in Python ──────────
    # We query by tenantId alone to avoid requiring a composite Firestore index.
    # Status and year filtering is done in Python — consistent with how the rest
    # of the app avoids composite-index requirements.
    raw_docs = (
        get_db()
        .collection("payments")
        .where("tenantId", "==", tenant_id)
        .stream()
    )

    # Build a dict: "YYYY-MM" → list of payment dicts
    month_map: dict = {f"{year}-{str(m).zfill(2)}": [] for m in range(1, 13)}
    for doc in raw_docs:
        p = doc.to_dict()
        if p.get("status") != "approved":
            continue
        payment_date = str(p.get("paymentDate", ""))
        if payment_date.startswith(str(year)):
            ym = payment_date[:7]   # "YYYY-MM"
            if ym in month_map:
                month_map[ym].append({
                    "id":            doc.id,
                    "amountPaid":    float(p.get("amountClaimed", 0) or 0),
                    "paymentDate":   payment_date,
                    "paymentMethod": p.get("paymentMethod", ""),
                })

    # ── Build response ─────────────────────────────────────────────────────────
    months = []
    for month_key in sorted(month_map.keys()):
        payments = month_map[month_key]
        total_paid = sum(x["amountPaid"] for x in payments)
        if monthly_rent > 0:
            pct = min(round(total_paid / monthly_rent * 100, 1), 200)
        else:
            pct = 0.0

        if total_paid <= 0:
            status = "unpaid"
        elif pct >= 100:
            status = "paid"
        else:
            status = "partial"

        months.append({
            "month":       month_key,
            "totalPaid":   total_paid,
            "monthlyRent": monthly_rent,
            "percentage":  pct,
            "status":      status,
            "payments":    payments,
        })

    return success_response(data={"year": year, "months": months, "monthlyRent": monthly_rent})


@payments_bp.route("", methods=["GET"])
@require_auth
def list_payments():
    page, limit = parse_pagination_args(request.args)
    status       = request.args.get("status")
    property_id  = request.args.get("propertyId")
    user         = g.user

    if user["role"] == "landlord":
        query = PaymentService.list_query(landlord_id=user["sub"], status=status, property_id=property_id)
    else:
        query = PaymentService.list_query(user_id=user["sub"], status=status, property_id=property_id)

    docs, total = paginate_query(query, page, limit)
    return paginated_response(docs, page, limit, total)


@payments_bp.route("/<payment_id>", methods=["GET"])
@require_auth
def get_payment(payment_id: str):
    payment = PaymentService.get_by_id(payment_id)
    if not payment:
        return error_response(PAYMENT_NOT_FOUND, "Payment not found.", status_code=404)
    if not _payment_owned_by(payment):
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)
    return success_response(data=payment)


@payments_bp.route("/<payment_id>/approve", methods=["PATCH"])
@require_role("landlord")
def approve_payment(payment_id: str):
    payment = PaymentService.get_by_id(payment_id)
    if not payment:
        return error_response(PAYMENT_NOT_FOUND, "Payment not found.", status_code=404)
    if payment["landlordId"] != g.user["sub"]:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)
    if payment["status"] != "pending":
        return error_response(PAYMENT_ALREADY_REVIEWED, "Payment has already been reviewed.", status_code=409)

    try:
        data = _validate(ApprovePaymentSchema, request.get_json(silent=True) or {})
    except _Fail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    PaymentService.approve(payment_id, landlord_note=data.get("note"))

    # Create a draft receipt that the landlord can review/edit before disbursing.
    receipt = None
    try:
        from app.services.receipt_service import ReceiptService
        receipt = ReceiptService.create_draft_receipt(payment_id)
        logger.info("Draft receipt created: id=%s payment_id=%s", receipt.get("id"), payment_id)
    except Exception:
        logger.exception(
            "Draft receipt creation failed for payment_id=%s — payment remains approved.",
            payment_id,
        )

    return success_response(
        data={
            "paymentId":  payment_id,
            "receiptId":  receipt["id"] if receipt else None,
            "receiptNumber": receipt["receiptNumber"] if receipt else None,
        },
        message="Payment approved. Please edit and disburse the receipt.",
    )


@payments_bp.route("/<payment_id>/reject", methods=["PATCH"])
@require_role("landlord")
def reject_payment(payment_id: str):
    payment = PaymentService.get_by_id(payment_id)
    if not payment:
        return error_response(PAYMENT_NOT_FOUND, "Payment not found.", status_code=404)
    if payment["landlordId"] != g.user["sub"]:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)
    if payment["status"] != "pending":
        return error_response(PAYMENT_ALREADY_REVIEWED, "Payment has already been reviewed.", status_code=409)

    try:
        data = _validate(RejectPaymentSchema, request.get_json(silent=True) or {})
    except _Fail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    PaymentService.reject(payment_id, rejection_reason=data["rejectionReason"])

    # Notify tenant
    NotificationService.notify_payment_rejected(
        tenant_id  = payment["userId"],
        payment_id = payment_id,
        reason     = data["rejectionReason"],
    )

    return success_response(data={"paymentId": payment_id})
