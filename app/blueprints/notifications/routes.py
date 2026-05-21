# ---------------------------------------------------------------------------
# blueprints/notifications/routes.py — /notifications/* endpoints
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request
from marshmallow import ValidationError as MarshmallowValidationError

from app.blueprints.notifications.schemas import SubscribeFcmSchema, UnsubscribeFcmSchema
from app.extensions import get_db
from app.middleware.auth_middleware import require_auth
from app.services.user_service import UserService
from app.utils.constants import AUTH_FORBIDDEN, NOTIFICATION_NOT_FOUND, VALIDATION_ERROR
from app.utils.pagination import paginate_query, parse_pagination_args
from app.utils.response import error_response, paginated_response, success_response

logger = logging.getLogger(__name__)
notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")

NOTIFICATIONS_COLLECTION = "notifications"


def _db():
    return get_db()


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


@notifications_bp.route("", methods=["GET"])
@require_auth
def list_notifications():
    page, limit = parse_pagination_args(request.args)
    read_filter  = request.args.get("read")

    query = _db().collection(NOTIFICATIONS_COLLECTION).where("userId", "==", g.user["sub"])
    if read_filter is not None:
        query = query.where("read", "==", read_filter.lower() == "true")
    # Sorting handled in Python by paginate_query — no composite index needed.

    docs, total = paginate_query(query, page, limit)
    return paginated_response(docs, page, limit, total)


@notifications_bp.route("/<notification_id>/read", methods=["PATCH"])
@require_auth
def mark_read(notification_id: str):
    doc_ref = _db().collection(NOTIFICATIONS_COLLECTION).document(notification_id)
    doc     = doc_ref.get()
    if not doc.exists:
        return error_response(NOTIFICATION_NOT_FOUND, "Notification not found.", status_code=404)

    notif = doc.to_dict()
    if notif.get("userId") != g.user["sub"]:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    doc_ref.update({"read": True})
    return success_response(data={"id": notification_id, "read": True})


@notifications_bp.route("/read-all", methods=["PATCH"])
@require_auth
def mark_all_read():
    db     = _db()
    user_id = g.user["sub"]
    docs   = (
        db.collection(NOTIFICATIONS_COLLECTION)
        .where("userId", "==", user_id)
        .where("read", "==", False)
        .stream()
    )

    batch = db.batch()
    count = 0
    for doc in docs:
        batch.update(doc.reference, {"read": True})
        count += 1
        if count % 500 == 0:   # Firestore batch limit
            batch.commit()
            batch = db.batch()

    if count % 500 != 0:
        batch.commit()

    return success_response(data={"updatedCount": count})


@notifications_bp.route("/subscribe", methods=["POST"])
@require_auth
def subscribe_fcm():
    try:
        data = _validate(SubscribeFcmSchema, request.get_json(silent=True) or {})
    except _Fail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    UserService.upsert_fcm_token(g.user["sub"], data["fcmToken"], data["deviceType"])
    return success_response(data=None, message="FCM token registered.")


@notifications_bp.route("/subscribe", methods=["DELETE"])
@require_auth
def unsubscribe_fcm():
    try:
        data = _validate(UnsubscribeFcmSchema, request.get_json(silent=True) or {})
    except _Fail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    UserService.remove_fcm_token(g.user["sub"], data["fcmToken"])
    return success_response(data=None, message="FCM token removed.")
