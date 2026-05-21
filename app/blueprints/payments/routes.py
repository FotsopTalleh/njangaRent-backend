# ---------------------------------------------------------------------------
# blueprints/payments/routes.py — /payments/* endpoints
# ---------------------------------------------------------------------------
import logging

from flask import Blueprint, g, request
from marshmallow import ValidationError as MarshmallowValidationError

from app.blueprints.payments.schemas import ApprovePaymentSchema, RejectPaymentSchema
from app.extensions import limiter
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

    # Generate receipt inline (synchronous) now that the payment is approved.
    # The receipt service handles WeasyPrint unavailability gracefully.
    receipt = None
    try:
        from app.services.receipt_service import ReceiptService
        receipt = ReceiptService.generate_receipt(payment_id)
        logger.info("Receipt generated: id=%s payment_id=%s", receipt.get("id"), payment_id)
    except Exception:
        logger.exception(
            "Receipt generation failed for payment_id=%s — payment remains approved "
            "but no receipt record was created.",
            payment_id,
        )

    # Notify tenant — include receipt details if available
    try:
        from app.services.property_service import PropertyService
        prop = PropertyService.get_by_id(payment["propertyId"])
        property_name = prop["name"] if prop else "your property"
        NotificationService.notify_payment_approved(
            tenant_id      = payment["userId"],
            payment_id     = payment_id,
            property_name  = property_name,
            receipt_number = receipt["receiptNumber"] if receipt else "N/A",
            receipt_id     = receipt["id"] if receipt else "",
        )
    except Exception as exc:
        logger.error("Failed to notify tenant for payment_id=%s: %s", payment_id, exc)

    return success_response(
        data={"paymentId": payment_id, "receiptId": receipt["id"] if receipt else None},
        message="Payment approved and receipt generated.",
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
