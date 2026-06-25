# ---------------------------------------------------------------------------
# blueprints/nkwa_payments/routes.py — Nkwa Mobile Money (sandbox) payments
# ---------------------------------------------------------------------------
import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone

import requests as http_requests
from flask import Blueprint, g, request

from app.extensions import get_db
from app.middleware.auth_middleware import require_auth, require_role_active
from app.utils.constants import (
    AUTH_FORBIDDEN, LISTING_NOT_FOUND, NKWA_PAYMENT_NOT_FOUND,
    NKWA_INITIATE_FAILED, NKWA_WEBHOOK_INVALID,
    NKWA_STATUS_INITIATED, NKWA_STATUS_CONFIRMED, NKWA_STATUS_FAILED,
    ROLE_LANDLORD, ROLE_STUDENT, ROLE_TENANT, SERVER_ERROR, VALIDATION_ERROR,
)
from app.utils.response import error_response, success_response, paginated_response

logger = logging.getLogger(__name__)
nkwa_bp = Blueprint("nkwa_payments", __name__, url_prefix="/nkwa-payments")

NKWA_PAYMENTS_COL = "nkwaPayments"
NKWA_BASE_URL     = "https://api.sandbox.mynkwa.com"


def _db():
    return get_db()


def _payment_doc(payment_id: str):
    doc = _db().collection(NKWA_PAYMENTS_COL).document(payment_id).get()
    if not doc.exists:
        return None
    d = doc.to_dict()
    d["id"] = doc.id
    return d


# ── Initiate payment ──────────────────────────────────────────────────────────

@nkwa_bp.route("/initiate", methods=["POST"])
@require_role_active(ROLE_STUDENT, ROLE_TENANT)
def initiate_payment():
    """POST /nkwa-payments/initiate — student initiates Nkwa MoMo payment."""
    student_id = g.user["sub"]
    body       = request.get_json(silent=True) or {}

    listing_id   = body.get("listingId", "").strip()
    amount       = body.get("amount", 0)
    phone        = body.get("phone", "").strip()
    payment_type = body.get("paymentType", "rent")  # "deposit" | "rent"

    if not listing_id:
        return error_response(VALIDATION_ERROR, "listingId is required.", field="listingId", status_code=422)
    if not phone:
        return error_response(VALIDATION_ERROR, "Phone number is required.", field="phone", status_code=422)
    if not amount or float(amount) <= 0:
        return error_response(VALIDATION_ERROR, "Valid amount is required.", field="amount", status_code=422)
    if payment_type not in ("deposit", "rent"):
        return error_response(VALIDATION_ERROR, "paymentType must be deposit or rent.", field="paymentType", status_code=422)

    # Get listing and landlord
    listing_doc = _db().collection("listings").document(listing_id).get()
    if not listing_doc.exists:
        return error_response(LISTING_NOT_FOUND, "Listing not found.", status_code=404)
    listing     = listing_doc.to_dict()
    landlord_id = listing.get("landlordId")

    api_key = os.environ.get("NKWA_API_KEY", "")
    if not api_key:
        return error_response(SERVER_ERROR, "Payment service not configured.", status_code=500)

    # Create Firestore record first (to get our payment ID for the reference)
    now     = datetime.now(timezone.utc)
    doc_ref = _db().collection(NKWA_PAYMENTS_COL).document()

    # Call Nkwa sandbox API
    try:
        nkwa_resp = http_requests.post(
            f"{NKWA_BASE_URL}/collect",
            json={
                "amount":      int(amount),
                "currency":    "XAF",
                "phone":       phone,
                "reference":   doc_ref.id,
                "description": f"NjangaRent {payment_type} for listing {listing_id}",
                "callbackUrl": f"{os.environ.get('BACKEND_URL', 'http://localhost:5000')}/nkwa-payments/webhook",
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            timeout=15,
        )
        nkwa_resp.raise_for_status()
        nkwa_data      = nkwa_resp.json()
        nkwa_reference = nkwa_data.get("reference", nkwa_data.get("id", doc_ref.id))
    except Exception as exc:
        logger.error("Nkwa API call failed: %s", exc)
        return error_response(NKWA_INITIATE_FAILED, "Could not initiate payment. Please try again.", status_code=502)

    payment_data = {
        "listingId":    listing_id,
        "studentId":    student_id,
        "landlordId":   landlord_id,
        "amountXaf":    float(amount),
        "phone":        phone,
        "nkwaReference": nkwa_reference,
        "nkwaStatus":   NKWA_STATUS_INITIATED,
        "paymentType":  payment_type,
        "initiatedAt":  now,
    }
    doc_ref.set(payment_data)
    payment_data["id"] = doc_ref.id
    logger.info("Nkwa payment initiated id=%s student=%s amount=%s", doc_ref.id, student_id, amount)

    return success_response(data=payment_data, status_code=201)


# ── List payments ─────────────────────────────────────────────────────────────

@nkwa_bp.route("", methods=["GET"])
@require_auth
def list_payments():
    """GET /nkwa-payments — list own payments."""
    user_id   = g.user["sub"]
    user_role = g.user.get("role", "")

    if user_role in (ROLE_STUDENT, ROLE_TENANT, "student"):
        q = _db().collection(NKWA_PAYMENTS_COL).where("studentId", "==", user_id)
    elif user_role == ROLE_LANDLORD:
        q = _db().collection(NKWA_PAYMENTS_COL).where("landlordId", "==", user_id)
    else:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    docs = list(q.order_by("initiatedAt", direction="DESCENDING").limit(50).stream())
    payments = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        payments.append(d)

    return success_response(data=payments)


# ── Get payment detail ────────────────────────────────────────────────────────

@nkwa_bp.route("/<payment_id>", methods=["GET"])
@require_auth
def get_payment(payment_id: str):
    user_id = g.user["sub"]
    payment = _payment_doc(payment_id)

    if not payment:
        return error_response(NKWA_PAYMENT_NOT_FOUND, "Payment not found.", status_code=404)
    if payment.get("studentId") != user_id and payment.get("landlordId") != user_id:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    return success_response(data=payment)


# ── Webhook (HMAC verified, no JWT, no rate limit) ───────────────────────────

@nkwa_bp.route("/webhook", methods=["POST"])
def nkwa_webhook():
    """POST /nkwa-payments/webhook — Nkwa payment status update.

    Security: HMAC-SHA256 signature on request body using NKWA_WEBHOOK_SECRET.
    IMPORTANT: Returns HTTP 200 even on signature failure to avoid leaking info.
    """
    webhook_secret = os.environ.get("NKWA_WEBHOOK_SECRET", "")
    signature_header = request.headers.get("X-Nkwa-Signature", "")

    if webhook_secret:
        # Verify HMAC-SHA256
        body_bytes = request.get_data()
        expected   = hmac.new(
            webhook_secret.encode(),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()

        received = signature_header.replace("sha256=", "")
        if not hmac.compare_digest(expected, received):
            logger.warning("Nkwa webhook signature verification failed")
            # Return 200 to not leak verification failure
            return success_response(data=None, message="ok")

    payload = request.get_json(silent=True) or {}
    nkwa_ref = payload.get("reference") or payload.get("externalReference", "")
    status   = payload.get("status", "").lower()

    if not nkwa_ref:
        return success_response(data=None, message="ok")

    # Find our payment record by nkwaReference
    docs = list(
        _db().collection(NKWA_PAYMENTS_COL)
        .where("nkwaReference", "==", nkwa_ref)
        .limit(1)
        .stream()
    )

    if not docs:
        logger.warning("Nkwa webhook: no payment found for reference=%s", nkwa_ref)
        return success_response(data=None, message="ok")

    doc      = docs[0]
    payment  = doc.to_dict()
    payment["id"] = doc.id

    now = datetime.now(timezone.utc)
    if status in ("successful", "success", "completed"):
        new_status = NKWA_STATUS_CONFIRMED
        updates    = {"nkwaStatus": new_status, "confirmedAt": now}
    elif status in ("failed", "failure", "cancelled"):
        new_status = NKWA_STATUS_FAILED
        updates    = {"nkwaStatus": new_status, "failedAt": now}
    else:
        logger.info("Nkwa webhook: unhandled status=%s ref=%s", status, nkwa_ref)
        return success_response(data=None, message="ok")

    _db().collection(NKWA_PAYMENTS_COL).document(doc.id).update(updates)
    logger.info("Nkwa payment %s updated to %s", doc.id, new_status)

    # Emit Socket.io event to both parties
    try:
        from app.extensions import socketio as _socketio
        if _socketio:
            payment.update(updates)
            _socketio.emit("payment_status_update", {
                "paymentId": doc.id,
                "status":    new_status,
                "payment":   payment,
            }, room=payment.get("studentId"))
            _socketio.emit("payment_status_update", {
                "paymentId": doc.id,
                "status":    new_status,
                "payment":   payment,
            }, room=payment.get("landlordId"))
    except Exception as exc:
        logger.debug("Socket.io emit skipped: %s", exc)

    return success_response(data=None, message="ok")
