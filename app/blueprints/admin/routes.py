# ---------------------------------------------------------------------------
# blueprints/admin/routes.py — Admin dashboard & moderation endpoints
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request

from app.extensions import get_db
from app.middleware.auth_middleware import require_role
from app.services.user_service import UserService
from app.utils.constants import (
    AUTH_FORBIDDEN, LISTING_NOT_FOUND, USER_NOT_FOUND,
    LISTING_STATUS_ACTIVE, LISTING_STATUS_FLAGGED, LISTING_STATUS_DEACTIVATED,
    LISTING_STATUS_PENDING_ADMIN_REVIEW, LISTING_STATUSES,
    ROLE_ADMIN, ROLE_LANDLORD, ROLE_STUDENT,
    STATUS_ACTIVE, STATUS_PENDING, STATUS_REJECTED, STATUS_BANNED,
    VALIDATION_ERROR,
    NOTIF_ACCOUNT_APPROVED, NOTIF_ACCOUNT_REJECTED,
    NOTIF_LISTING_APPROVED, NOTIF_LISTING_FLAGGED, NOTIF_LISTING_REJECTED,
)
from app.utils.response import error_response, success_response, paginated_response

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

USERS_COL     = "users"
LISTINGS_COL  = "listings"
NKWA_COL      = "nkwaPayments"
CONVS_COL     = "conversations"


def _db():
    return get_db()


def _notify_user(user_id: str, notif_type: str, title: str, message: str):
    """Send FCM + in-app notification to a user (best-effort)."""
    try:
        from app.services.notification_service import NotificationService
        NotificationService.send_notification(user_id, notif_type, title, message)
    except Exception as exc:
        logger.debug("Admin notification skipped: %s", exc)


# ── Dashboard stats ───────────────────────────────────────────────────────────

@admin_bp.route("/dashboard", methods=["GET"])
@require_role(ROLE_ADMIN)
def dashboard():
    """GET /admin/dashboard — aggregate stats."""
    db = _db()

    # Active listings
    active_listings = sum(
        1 for _ in db.collection(LISTINGS_COL).where("status", "==", LISTING_STATUS_ACTIVE).stream()
    )

    # Pending verifications
    pending_landlords = UserService.count_by_role_and_status(ROLE_LANDLORD, STATUS_PENDING)
    pending_students  = UserService.count_by_role_and_status(ROLE_STUDENT, STATUS_PENDING)
    pending_total     = pending_landlords + pending_students

    # Active users (students + landlords)
    active_landlords = UserService.count_by_role_and_status(ROLE_LANDLORD, STATUS_ACTIVE)
    active_students  = UserService.count_by_role_and_status(ROLE_STUDENT, STATUS_ACTIVE)
    active_users     = active_landlords + active_students

    # Payments this month
    now           = datetime.now(timezone.utc)
    month_start   = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nkwa_docs     = list(
        db.collection(NKWA_COL)
        .where("nkwaStatus", "==", "confirmed")
        .where("confirmedAt", ">=", month_start)
        .stream()
    )
    payments_xaf  = sum(doc.to_dict().get("amountXaf", 0) for doc in nkwa_docs)
    payments_count = len(nkwa_docs)

    # Flagged listings
    flagged = sum(
        1 for _ in db.collection(LISTINGS_COL).where("status", "==", LISTING_STATUS_FLAGGED).stream()
    )

    return success_response(data={
        "activeListings":       active_listings,
        "pendingVerifications": pending_total,
        "pendingLandlords":     pending_landlords,
        "pendingStudents":      pending_students,
        "activeUsers":          active_users,
        "paymentsThisMonthXaf": payments_xaf,
        "paymentsThisMonth":    payments_count,
        "flaggedListings":      flagged,
    })


# ── Verification queues ───────────────────────────────────────────────────────

@admin_bp.route("/verifications/landlords", methods=["GET"])
@require_role(ROLE_ADMIN)
def verification_landlords():
    page  = max(1, int(request.args.get("page", 1)))
    limit = min(50, int(request.args.get("limit", 20)))
    users = UserService.list_by_role_and_status(ROLE_LANDLORD, STATUS_PENDING, limit=limit, offset=(page - 1) * limit)
    total = UserService.count_by_role_and_status(ROLE_LANDLORD, STATUS_PENDING)
    safe  = [UserService.safe_dict(u) for u in users]
    return paginated_response(safe, page=page, limit=limit, total=total)


@admin_bp.route("/verifications/students", methods=["GET"])
@require_role(ROLE_ADMIN)
def verification_students():
    page  = max(1, int(request.args.get("page", 1)))
    limit = min(50, int(request.args.get("limit", 20)))
    users = UserService.list_by_role_and_status(ROLE_STUDENT, STATUS_PENDING, limit=limit, offset=(page - 1) * limit)
    total = UserService.count_by_role_and_status(ROLE_STUDENT, STATUS_PENDING)
    safe  = [UserService.safe_dict(u) for u in users]
    return paginated_response(safe, page=page, limit=limit, total=total)


@admin_bp.route("/verifications/<user_id>/approve", methods=["PUT"])
@require_role(ROLE_ADMIN)
def approve_user(user_id: str):
    user = UserService.get_by_id(user_id)
    if not user:
        return error_response(USER_NOT_FOUND, "User not found.", status_code=404)
    UserService.set_status(user_id, STATUS_ACTIVE, admin_note=request.get_json(silent=True, force=True) and request.get_json().get("note"))
    _notify_user(user_id, NOTIF_ACCOUNT_APPROVED,
                 "Account Approved", "Your NjangaRent account has been verified. You can now log in.")
    return success_response(data=None, message="User approved.")


@admin_bp.route("/verifications/<user_id>/reject", methods=["PUT"])
@require_role(ROLE_ADMIN)
def reject_user(user_id: str):
    user   = UserService.get_by_id(user_id)
    if not user:
        return error_response(USER_NOT_FOUND, "User not found.", status_code=404)
    body   = request.get_json(silent=True) or {}
    reason = body.get("reason", "Verification requirements not met.")
    UserService.set_status(user_id, STATUS_REJECTED, reason=reason)
    _notify_user(user_id, NOTIF_ACCOUNT_REJECTED,
                 "Verification Rejected", f"Your account was not approved. Reason: {reason}")
    return success_response(data=None, message="User rejected.")


# ── Listing moderation ────────────────────────────────────────────────────────

@admin_bp.route("/listings", methods=["GET"])
@require_role(ROLE_ADMIN)
def admin_listings():
    page   = max(1, int(request.args.get("page", 1)))
    limit  = min(50, int(request.args.get("limit", 20)))
    status = request.args.get("status")

    q = _db().collection(LISTINGS_COL)
    if status and status in LISTING_STATUSES:
        q = q.where("status", "==", status)

    docs = list(q.order_by("createdAt", direction="DESCENDING").stream())
    all_listings = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        all_listings.append(d)

    total = len(all_listings)
    start = (page - 1) * limit
    return paginated_response(all_listings[start:start + limit], page=page, limit=limit, total=total)


@admin_bp.route("/listings/<listing_id>/approve", methods=["PUT"])
@require_role(ROLE_ADMIN)
def approve_listing(listing_id: str):
    doc = _db().collection(LISTINGS_COL).document(listing_id).get()
    if not doc.exists:
        return error_response(LISTING_NOT_FOUND, "Listing not found.", status_code=404)
    listing = doc.to_dict()
    _db().collection(LISTINGS_COL).document(listing_id).update({
        "status": LISTING_STATUS_ACTIVE, "updatedAt": datetime.now(timezone.utc)
    })
    _notify_user(listing.get("landlordId"), NOTIF_LISTING_APPROVED,
                 "Listing Approved", f"Your listing '{listing.get('title')}' is now live on NjangaRent.")
    return success_response(data=None, message="Listing approved.")


@admin_bp.route("/listings/<listing_id>/flag", methods=["PUT"])
@require_role(ROLE_ADMIN)
def flag_listing(listing_id: str):
    doc = _db().collection(LISTINGS_COL).document(listing_id).get()
    if not doc.exists:
        return error_response(LISTING_NOT_FOUND, "Listing not found.", status_code=404)
    listing = doc.to_dict()
    body    = request.get_json(silent=True) or {}
    note    = body.get("reason", "Policy violation")
    _db().collection(LISTINGS_COL).document(listing_id).update({
        "status": LISTING_STATUS_FLAGGED, "adminNote": note, "updatedAt": datetime.now(timezone.utc)
    })
    _notify_user(listing.get("landlordId"), NOTIF_LISTING_FLAGGED,
                 "Listing Flagged", f"Your listing has been flagged for review. Reason: {note}")
    return success_response(data=None, message="Listing flagged.")


@admin_bp.route("/listings/<listing_id>/remove", methods=["PUT"])
@require_role(ROLE_ADMIN)
def remove_listing(listing_id: str):
    doc = _db().collection(LISTINGS_COL).document(listing_id).get()
    if not doc.exists:
        return error_response(LISTING_NOT_FOUND, "Listing not found.", status_code=404)
    listing = doc.to_dict()
    body    = request.get_json(silent=True) or {}
    reason  = body.get("reason", "Removed by admin")
    _db().collection(LISTINGS_COL).document(listing_id).update({
        "status": LISTING_STATUS_DEACTIVATED, "adminNote": reason, "updatedAt": datetime.now(timezone.utc)
    })
    _notify_user(listing.get("landlordId"), NOTIF_LISTING_REJECTED,
                 "Listing Removed", f"Your listing was removed. Reason: {reason}")
    return success_response(data=None, message="Listing removed.")


# ── User management ───────────────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@require_role(ROLE_ADMIN)
def admin_users():
    q = request.args.get("q", "").strip()
    page  = max(1, int(request.args.get("page", 1)))
    limit = min(50, int(request.args.get("limit", 20)))

    if q:
        users = UserService.search_users(q, limit=limit)
    else:
        # Paginate all users (ordered by createdAt)
        docs = list(
            _db().collection(USERS_COL)
            .order_by("createdAt", direction="DESCENDING")
            .limit(limit)
            .offset((page - 1) * limit)
            .stream()
        )
        users = []
        for doc in docs:
            d = doc.to_dict()
            d["id"] = doc.id
            users.append(d)

    safe  = [UserService.safe_dict(u) for u in users]
    return success_response(data=safe)


@admin_bp.route("/users/<user_id>/ban", methods=["PUT"])
@require_role(ROLE_ADMIN)
def ban_user(user_id: str):
    user = UserService.get_by_id(user_id)
    if not user:
        return error_response(USER_NOT_FOUND, "User not found.", status_code=404)
    body   = request.get_json(silent=True) or {}
    reason = body.get("reason", "Banned by admin")
    UserService.set_status(user_id, STATUS_BANNED, reason=reason)
    return success_response(data=None, message="User banned.")


@admin_bp.route("/users/<user_id>/unban", methods=["PUT"])
@require_role(ROLE_ADMIN)
def unban_user(user_id: str):
    user = UserService.get_by_id(user_id)
    if not user:
        return error_response(USER_NOT_FOUND, "User not found.", status_code=404)
    UserService.set_status(user_id, STATUS_ACTIVE)
    return success_response(data=None, message="User unbanned.")


# ── Payments (all) ────────────────────────────────────────────────────────────

@admin_bp.route("/payments", methods=["GET"])
@require_role(ROLE_ADMIN)
def admin_payments():
    page   = max(1, int(request.args.get("page", 1)))
    limit  = min(50, int(request.args.get("limit", 20)))
    status = request.args.get("status")

    q = _db().collection(NKWA_COL)
    if status:
        q = q.where("nkwaStatus", "==", status)

    docs = list(q.order_by("initiatedAt", direction="DESCENDING").stream())
    all_payments = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        all_payments.append(d)

    total = len(all_payments)
    start = (page - 1) * limit
    return paginated_response(all_payments[start:start + limit], page=page, limit=limit, total=total)


# ── Messages audit ────────────────────────────────────────────────────────────

@admin_bp.route("/messages", methods=["GET"])
@require_role(ROLE_ADMIN)
def admin_messages():
    page  = max(1, int(request.args.get("page", 1)))
    limit = min(50, int(request.args.get("limit", 20)))

    docs = list(
        _db().collection(CONVS_COL)
        .order_by("lastActivity", direction="DESCENDING")
        .limit(limit)
        .offset((page - 1) * limit)
        .stream()
    )
    convs = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        convs.append(d)

    return success_response(data=convs)
