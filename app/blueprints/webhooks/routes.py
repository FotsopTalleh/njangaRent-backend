# ---------------------------------------------------------------------------
# blueprints/webhooks/routes.py — Internal webhook endpoints (n8n callback)
# ---------------------------------------------------------------------------
import logging
import os

from flask import Blueprint, request

from app.extensions import limiter
from app.middleware.rate_limit_middleware import LIMIT_WEBHOOK, key_by_ip
from app.services.payment_service import PaymentService
from app.utils.constants import PAYMENT_NOT_FOUND
from app.utils.response import error_response, success_response

logger = logging.getLogger(__name__)
webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")


def _verify_n8n_secret() -> bool:
    expected = os.environ.get("N8N_WEBHOOK_SECRET", "")
    received = request.headers.get("X-N8N-Secret", "")
    return expected and received == expected


# ── POST /webhooks/n8n/ocr-result ────────────────────────────────────────────


@webhooks_bp.route("/n8n/ocr-result", methods=["POST"])
@limiter.limit(LIMIT_WEBHOOK, key_func=key_by_ip)
def ocr_result():
    """Receive OCR extraction result from n8n and store it on the payment.

    n8n is now triggered on upload (payment status = pending).
    This callback simply persists the OCR data so the landlord can
    see the extracted amount during review. Receipt generation happens
    synchronously inside the approve endpoint.

    Authentication: X-N8N-Secret header (shared secret — NOT JWT).
    Always returns 200 on non-auth errors to prevent n8n retry storms.
    """
    # ── 1. Authenticate ───────────────────────────────────────────────────────
    if not _verify_n8n_secret():
        logger.warning("OCR callback received with invalid N8N secret — rejecting.")
        return error_response("AUTH_TOKEN_INVALID", "Invalid webhook secret.", status_code=401)

    body = request.get_json(silent=True) or {}

    payment_id       = body.get("paymentId")
    extracted_amount = body.get("extractedAmount")
    ocr_success      = body.get("ocrSuccess", False)
    ocr_error        = body.get("ocrError")

    if not payment_id:
        logger.error("OCR callback missing paymentId.")
        return success_response(data=None, message="Missing paymentId.")

    # ── 2. Fetch payment ──────────────────────────────────────────────────────
    payment = PaymentService.get_by_id(payment_id)
    if not payment:
        logger.error("OCR callback: payment not found paymentId=%s", payment_id)
        return error_response(PAYMENT_NOT_FOUND, "Payment not found.", status_code=404)

    # ── 3. Store OCR data (works on both pending and approved payments) ────────
    if ocr_success and extracted_amount is not None:
        PaymentService.set_ocr_data(payment_id, float(extracted_amount))
        logger.info(
            "OCR data stored: payment_id=%s extracted_amount=%s status=%s",
            payment_id, extracted_amount, payment["status"],
        )
    elif not ocr_success:
        logger.warning("OCR failed for payment_id=%s: %s", payment_id, ocr_error)

    logger.info("OCR webhook processed: payment_id=%s", payment_id)
    return success_response(data={"paymentId": payment_id, "ocrSuccess": ocr_success})

