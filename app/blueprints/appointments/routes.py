# ---------------------------------------------------------------------------
# blueprints/appointments/routes.py — Appointment lifecycle endpoints
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone, date, timedelta

from flask import Blueprint, g, request

from app.extensions import get_db
from app.middleware.auth_middleware import require_auth, require_role, require_role_active
from app.utils.constants import (
    APPOINTMENT_NOT_FOUND, APPOINTMENT_LIMIT, APPOINTMENT_INVALID_DATE,
    APPOINTMENT_FORBIDDEN, AUTH_FORBIDDEN, LISTING_NOT_FOUND,
    APPT_STATUS_PENDING, APPT_STATUS_CONFIRMED, APPT_STATUS_RESCHEDULED,
    APPT_STATUS_DECLINED, APPT_STATUS_COMPLETED, APPT_STATUS_CANCELLED,
    APPT_STATUS_EXPIRED, APPOINTMENT_SLOTS, APPOINTMENT_STATUSES,
    ROLE_LANDLORD, ROLE_STUDENT, ROLE_TENANT, VALIDATION_ERROR,
)
from app.utils.response import error_response, success_response, paginated_response

logger = logging.getLogger(__name__)
appointments_bp = Blueprint("appointments", __name__, url_prefix="/appointments")
APPTS_COL = "appointments"


def _db():
    return get_db()


def _appt_doc(appt_id: str):
    doc = _db().collection(APPTS_COL).document(appt_id).get()
    if not doc.exists:
        return None
    d = doc.to_dict()
    d["id"] = doc.id
    return d


def _is_participant(appt: dict, user_id: str) -> bool:
    return appt.get("studentId") == user_id or appt.get("landlordId") == user_id


# ── Create ────────────────────────────────────────────────────────────────────

@appointments_bp.route("", methods=["POST"])
@require_role_active(ROLE_STUDENT, ROLE_TENANT)
def create_appointment():
    """POST /appointments — student creates an appointment request."""
    student_id = g.user["sub"]
    body       = request.get_json(silent=True) or {}

    listing_id    = body.get("listingId", "").strip()
    proposed_date = body.get("proposedDate", "").strip()  # ISO date string YYYY-MM-DD
    proposed_slot = body.get("proposedSlot", "").strip()
    student_note  = body.get("studentNote", "").strip()

    if not listing_id:
        return error_response(VALIDATION_ERROR, "listingId is required.", field="listingId", status_code=422)
    if not proposed_date:
        return error_response(VALIDATION_ERROR, "proposedDate is required.", field="proposedDate", status_code=422)
    if proposed_slot not in APPOINTMENT_SLOTS:
        return error_response(VALIDATION_ERROR, f"proposedSlot must be one of: {', '.join(APPOINTMENT_SLOTS)}", field="proposedSlot", status_code=422)

    # Validate date >= tomorrow
    try:
        appt_date = date.fromisoformat(proposed_date)
    except ValueError:
        return error_response(APPOINTMENT_INVALID_DATE, "proposedDate must be a valid YYYY-MM-DD date.", field="proposedDate", status_code=422)

    if appt_date <= date.today():
        return error_response(APPOINTMENT_INVALID_DATE, "Appointment must be scheduled for tomorrow or later.", field="proposedDate", status_code=422)

    # Check listing exists and get landlord
    listing_doc = _db().collection("listings").document(listing_id).get()
    if not listing_doc.exists:
        return error_response(LISTING_NOT_FOUND, "Listing not found.", status_code=404)
    landlord_id = listing_doc.to_dict().get("landlordId")

    # Enforce max 3 pending appointments per student
    pending_count = sum(
        1 for doc in _db().collection(APPTS_COL)
        .where("studentId", "==", student_id)
        .where("status", "==", APPT_STATUS_PENDING)
        .stream()
    )
    if pending_count >= 3:
        return error_response(APPOINTMENT_LIMIT, "You cannot have more than 3 pending appointments at once.", status_code=409)

    now = datetime.now(timezone.utc)
    doc_ref = _db().collection(APPTS_COL).document()
    appt_data = {
        "listingId":    listing_id,
        "studentId":    student_id,
        "landlordId":   landlord_id,
        "proposedDate": proposed_date,
        "proposedSlot": proposed_slot,
        "studentNote":  student_note,
        "status":       APPT_STATUS_PENDING,
        "createdAt":    now,
        "updatedAt":    now,
    }
    doc_ref.set(appt_data)
    appt_data["id"] = doc_ref.id
    logger.info("Appointment created id=%s student=%s listing=%s", doc_ref.id, student_id, listing_id)
    return success_response(data=appt_data, status_code=201)


# ── List ─────────────────────────────────────────────────────────────────────

@appointments_bp.route("", methods=["GET"])
@require_auth
def list_appointments():
    """GET /appointments — list own appointments, role-filtered."""
    user_id   = g.user["sub"]
    user_role = g.user.get("role", "")
    status_f  = request.args.get("status")
    page      = max(1, int(request.args.get("page", 1)))
    limit     = min(50, int(request.args.get("limit", 20)))

    if user_role in (ROLE_STUDENT, ROLE_TENANT, "student"):
        q = _db().collection(APPTS_COL).where("studentId", "==", user_id)
    elif user_role == ROLE_LANDLORD:
        q = _db().collection(APPTS_COL).where("landlordId", "==", user_id)
    else:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    if status_f and status_f in APPOINTMENT_STATUSES:
        q = q.where("status", "==", status_f)

    docs = list(q.order_by("createdAt", direction="DESCENDING").stream())
    appts = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        appts.append(d)

    total = len(appts)
    start = (page - 1) * limit
    return paginated_response(appts[start:start + limit], page=page, limit=limit, total=total)


# ── Get detail ────────────────────────────────────────────────────────────────

@appointments_bp.route("/<appt_id>", methods=["GET"])
@require_auth
def get_appointment(appt_id: str):
    user_id = g.user["sub"]
    appt    = _appt_doc(appt_id)
    if not appt:
        return error_response(APPOINTMENT_NOT_FOUND, "Appointment not found.", status_code=404)
    if not _is_participant(appt, user_id):
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)
    return success_response(data=appt)


# ── Landlord respond ──────────────────────────────────────────────────────────

@appointments_bp.route("/<appt_id>/respond", methods=["PUT"])
@require_role_active(ROLE_LANDLORD)
def respond_appointment(appt_id: str):
    """PUT /appointments/:id/respond — landlord confirms, reschedules, or declines."""
    landlord_id = g.user["sub"]
    appt        = _appt_doc(appt_id)

    if not appt:
        return error_response(APPOINTMENT_NOT_FOUND, "Appointment not found.", status_code=404)
    if appt.get("landlordId") != landlord_id:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)
    if appt.get("status") not in (APPT_STATUS_PENDING, APPT_STATUS_RESCHEDULED):
        return error_response(APPOINTMENT_FORBIDDEN, "Cannot respond to this appointment in its current status.", status_code=409)

    body   = request.get_json(silent=True) or {}
    action = body.get("action", "")  # "confirm" | "reschedule" | "decline"

    if action not in ("confirm", "reschedule", "decline"):
        return error_response(VALIDATION_ERROR, "action must be confirm, reschedule, or decline.", field="action", status_code=422)

    updates = {"updatedAt": datetime.now(timezone.utc)}

    if action == "confirm":
        updates["status"]       = APPT_STATUS_CONFIRMED
        updates["landlordNote"] = body.get("landlordNote", "")
    elif action == "reschedule":
        counter_date = body.get("counterDate", "")
        counter_slot = body.get("counterSlot", "")
        if not counter_date or counter_slot not in APPOINTMENT_SLOTS:
            return error_response(VALIDATION_ERROR, "counterDate and counterSlot are required for rescheduling.", status_code=422)
        updates["status"]       = APPT_STATUS_RESCHEDULED
        updates["counterDate"]  = counter_date
        updates["counterSlot"]  = counter_slot
        updates["landlordNote"] = body.get("landlordNote", "")
    else:  # decline
        updates["status"]        = APPT_STATUS_DECLINED
        updates["declineReason"] = body.get("declineReason", "")

    _db().collection(APPTS_COL).document(appt_id).update(updates)
    appt.update(updates)
    return success_response(data=appt)


# ── Student cancel ────────────────────────────────────────────────────────────

@appointments_bp.route("/<appt_id>/cancel", methods=["PUT"])
@require_role_active(ROLE_STUDENT, ROLE_TENANT)
def cancel_appointment(appt_id: str):
    """PUT /appointments/:id/cancel — student cancels pending or confirmed appointment."""
    student_id = g.user["sub"]
    appt       = _appt_doc(appt_id)

    if not appt:
        return error_response(APPOINTMENT_NOT_FOUND, "Appointment not found.", status_code=404)
    if appt.get("studentId") != student_id:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)
    if appt.get("status") not in (APPT_STATUS_PENDING, APPT_STATUS_CONFIRMED, APPT_STATUS_RESCHEDULED):
        return error_response(APPOINTMENT_FORBIDDEN, "Cannot cancel this appointment in its current status.", status_code=409)

    _db().collection(APPTS_COL).document(appt_id).update({
        "status":    APPT_STATUS_CANCELLED,
        "updatedAt": datetime.now(timezone.utc),
    })
    return success_response(data=None, message="Appointment cancelled.")


# ── Landlord complete ─────────────────────────────────────────────────────────

@appointments_bp.route("/<appt_id>/complete", methods=["PUT"])
@require_role_active(ROLE_LANDLORD)
def complete_appointment(appt_id: str):
    """PUT /appointments/:id/complete — landlord marks appointment as completed."""
    landlord_id = g.user["sub"]
    appt        = _appt_doc(appt_id)

    if not appt:
        return error_response(APPOINTMENT_NOT_FOUND, "Appointment not found.", status_code=404)
    if appt.get("landlordId") != landlord_id:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)
    if appt.get("status") != APPT_STATUS_CONFIRMED:
        return error_response(APPOINTMENT_FORBIDDEN, "Only confirmed appointments can be marked complete.", status_code=409)

    _db().collection(APPTS_COL).document(appt_id).update({
        "status":    APPT_STATUS_COMPLETED,
        "updatedAt": datetime.now(timezone.utc),
    })
    return success_response(data=None, message="Appointment marked as completed.")
