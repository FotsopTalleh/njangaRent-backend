# ---------------------------------------------------------------------------
# blueprints/messages/routes.py — Conversation REST endpoints
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request

from app.extensions import get_db
from app.middleware.auth_middleware import require_auth, require_role, require_role_active
from app.utils.constants import (
    AUTH_FORBIDDEN, CONVERSATION_NOT_FOUND, LISTING_NOT_FOUND,
    ROLE_LANDLORD, ROLE_STUDENT, ROLE_TENANT, VALIDATION_ERROR,
)
from app.utils.response import error_response, success_response, paginated_response

logger = logging.getLogger(__name__)
messages_bp = Blueprint("messages", __name__, url_prefix="/messages")

CONVS_COL = "conversations"
MSGS_COL  = "messages"


def _db():
    return get_db()


def _conv_doc(conv_id: str):
    doc = _db().collection(CONVS_COL).document(conv_id).get()
    if not doc.exists:
        return None
    d = doc.to_dict()
    d["id"] = doc.id
    return d


def _is_participant(conv: dict, user_id: str) -> bool:
    return conv.get("studentId") == user_id or conv.get("landlordId") == user_id


# ── REST endpoints ────────────────────────────────────────────────────────────

@messages_bp.route("/conversations", methods=["GET"])
@require_auth
def list_conversations():
    """GET /messages/conversations — list own conversations."""
    user_id   = g.user["sub"]
    user_role = g.user.get("role", "")

    if user_role in (ROLE_STUDENT, ROLE_TENANT, "student"):
        q = _db().collection(CONVS_COL).where("studentId", "==", user_id)
    elif user_role == ROLE_LANDLORD:
        q = _db().collection(CONVS_COL).where("landlordId", "==", user_id)
    else:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    docs = list(q.order_by("lastActivity", direction="DESCENDING").limit(50).stream())
    convs = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        convs.append(d)

    return success_response(data=convs)


@messages_bp.route("/conversations", methods=["POST"])
@require_role_active(ROLE_STUDENT, ROLE_TENANT)
def initiate_conversation():
    """POST /messages/conversations — student initiates conversation on a listing."""
    student_id = g.user["sub"]
    body       = request.get_json(silent=True) or {}
    listing_id = body.get("listingId", "").strip()

    if not listing_id:
        return error_response(VALIDATION_ERROR, "listingId is required.", field="listingId", status_code=422)

    # Verify listing exists
    listing_doc = _db().collection("listings").document(listing_id).get()
    if not listing_doc.exists:
        return error_response(LISTING_NOT_FOUND, "Listing not found.", status_code=404)

    listing    = listing_doc.to_dict()
    landlord_id = listing.get("landlordId")

    # Check if conversation already exists for (student, listing) pair
    existing = list(
        _db().collection(CONVS_COL)
        .where("studentId", "==", student_id)
        .where("listingId", "==", listing_id)
        .limit(1)
        .stream()
    )
    if existing:
        d = existing[0].to_dict()
        d["id"] = existing[0].id
        return success_response(data=d)

    now = datetime.now(timezone.utc)
    doc_ref = _db().collection(CONVS_COL).document()
    conv_data = {
        "listingId":            listing_id,
        "studentId":            student_id,
        "landlordId":           landlord_id,
        "lastMessage":          "",
        "lastActivity":         now,
        "studentUnreadCount":   0,
        "landlordUnreadCount":  0,
        "createdAt":            now,
    }
    doc_ref.set(conv_data)
    conv_data["id"] = doc_ref.id
    logger.info("Conversation created id=%s student=%s listing=%s", doc_ref.id, student_id, listing_id)
    return success_response(data=conv_data, status_code=201)


@messages_bp.route("/conversations/<conv_id>", methods=["GET"])
@require_auth
def get_messages(conv_id: str):
    """GET /messages/conversations/:id — paginated message history."""
    user_id = g.user["sub"]
    conv    = _conv_doc(conv_id)

    if not conv:
        return error_response(CONVERSATION_NOT_FOUND, "Conversation not found.", status_code=404)
    if not _is_participant(conv, user_id):
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    page  = max(1, int(request.args.get("page", 1)))
    limit = min(50, int(request.args.get("limit", 20)))

    docs = list(
        _db().collection(MSGS_COL)
        .where("conversationId", "==", conv_id)
        .order_by("createdAt", direction="DESCENDING")
        .limit(limit)
        .offset((page - 1) * limit)
        .stream()
    )
    messages = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        messages.append(d)

    messages.reverse()  # Return in chronological order

    # Count total for pagination
    try:
        total_docs = list(
            _db().collection(MSGS_COL).where("conversationId", "==", conv_id).stream()
        )
        total = len(total_docs)
    except Exception:
        total = len(messages)

    return paginated_response(messages, page=page, limit=limit, total=total)
