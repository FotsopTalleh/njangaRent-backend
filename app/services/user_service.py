# ---------------------------------------------------------------------------
# services/user_service.py — Firestore user CRUD (extended for NjangaRent)
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone
from typing import Optional

from app.extensions import get_db

logger = logging.getLogger(__name__)

USERS_COLLECTION = "users"


class UserService:
    """CRUD operations on the ``users`` Firestore collection."""

    @staticmethod
    def _db():
        return get_db()

    # ── Read ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_by_id(user_id: str) -> Optional[dict]:
        doc = UserService._db().collection(USERS_COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    @staticmethod
    def get_by_email(email: str) -> Optional[dict]:
        docs = (
            UserService._db()
            .collection(USERS_COLLECTION)
            .where("email", "==", email.lower().strip())
            .limit(1)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    @staticmethod
    def get_by_google_id(google_id: str) -> Optional[dict]:
        docs = (
            UserService._db()
            .collection(USERS_COLLECTION)
            .where("googleId", "==", google_id)
            .limit(1)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    @staticmethod
    def list_by_role_and_status(role: str, status: str, limit: int = 50, offset: int = 0) -> list:
        """List users by role + status, with basic pagination via offset (Firestore offset)."""
        docs = (
            UserService._db()
            .collection(USERS_COLLECTION)
            .where("role", "==", role)
            .where("status", "==", status)
            .order_by("createdAt")
            .limit(limit)
            .offset(offset)
            .stream()
        )
        result = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            result.append(data)
        return result

    @staticmethod
    def count_by_role_and_status(role: str, status: str) -> int:
        """Count users matching role + status (uses aggregation if available, else stream)."""
        try:
            from google.cloud.firestore_v1.aggregation import AggregationQuery  # noqa
            q = (
                UserService._db()
                .collection(USERS_COLLECTION)
                .where("role", "==", role)
                .where("status", "==", status)
            )
            result = q.count(alias="total").get()
            return result[0][0].value if result else 0
        except Exception:
            docs = (
                UserService._db()
                .collection(USERS_COLLECTION)
                .where("role", "==", role)
                .where("status", "==", status)
                .stream()
            )
            return sum(1 for _ in docs)

    @staticmethod
    def search_users(query: str, limit: int = 30) -> list:
        """Approximate search by email prefix. Firestore has limited text search."""
        # Email prefix search
        end_query = query.lower() + "\uf8ff"
        docs = (
            UserService._db()
            .collection(USERS_COLLECTION)
            .where("email", ">=", query.lower())
            .where("email", "<=", end_query)
            .limit(limit)
            .stream()
        )
        result = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            result.append(data)
        return result

    # ── Create ────────────────────────────────────────────────────────────────

    @staticmethod
    def create(
        email: str,
        full_name: str,
        role: str,
        password_hash: Optional[str] = None,
        phone: Optional[str] = None,
        google_id: Optional[str] = None,
        status: str = "ACTIVE",
        # Student-specific
        university: Optional[str] = None,
        program: Optional[str] = None,
        matric_number: Optional[str] = None,
        verification: Optional[dict] = None,
    ) -> dict:
        db = UserService._db()
        now = datetime.now(timezone.utc)
        doc_ref = db.collection(USERS_COLLECTION).document()
        user_data = {
            "email":      email.lower().strip(),
            "fullName":   full_name.strip(),
            "role":       role,
            "status":     status,
            "fcmTokens":  [],
            "createdAt":  now,
            "updatedAt":  now,
        }
        if password_hash:
            user_data["passwordHash"] = password_hash
        if phone:
            user_data["phone"] = phone.strip()
        if google_id:
            user_data["googleId"] = google_id
        # Student fields
        if university:
            user_data["university"] = university
        if program:
            user_data["program"] = program
        if matric_number:
            user_data["matricNumber"] = matric_number
        # Verification documents dict (URLs)
        if verification:
            user_data["verification"] = verification

        doc_ref.set(user_data)
        user_data["id"] = doc_ref.id
        logger.info("Created user id=%s email=%s role=%s status=%s", doc_ref.id, email, role, status)
        return user_data

    # ── Update ────────────────────────────────────────────────────────────────

    @staticmethod
    def update(user_id: str, updates: dict) -> None:
        updates["updatedAt"] = datetime.now(timezone.utc)
        UserService._db().collection(USERS_COLLECTION).document(user_id).update(updates)

    @staticmethod
    def set_status(user_id: str, status: str, reason: Optional[str] = None, admin_note: Optional[str] = None) -> None:
        updates: dict = {"status": status, "updatedAt": datetime.now(timezone.utc)}
        if reason:
            updates["bannedReason"] = reason
        if admin_note:
            updates["adminNote"] = admin_note
        UserService._db().collection(USERS_COLLECTION).document(user_id).update(updates)

    # ── FCM token management ─────────────────────────────────────────────────

    @staticmethod
    def upsert_fcm_token(user_id: str, token: str, device_type: str) -> None:
        """Add token to fcmTokens array (no duplicates)."""
        from google.cloud import firestore as gc_firestore  # type: ignore

        user_ref = UserService._db().collection(USERS_COLLECTION).document(user_id)
        user = user_ref.get()
        if not user.exists:
            return

        tokens: list = user.to_dict().get("fcmTokens", [])
        tokens = [t for t in tokens if t.get("token") != token]
        tokens.append({
            "token":      token,
            "deviceType": device_type,
            "createdAt":  datetime.now(timezone.utc),
        })
        user_ref.update({"fcmTokens": tokens, "updatedAt": datetime.now(timezone.utc)})

    @staticmethod
    def remove_fcm_token(user_id: str, token: str) -> None:
        user_ref = UserService._db().collection(USERS_COLLECTION).document(user_id)
        user = user_ref.get()
        if not user.exists:
            return
        tokens: list = user.to_dict().get("fcmTokens", [])
        tokens = [t for t in tokens if t.get("token") != token]
        user_ref.update({"fcmTokens": tokens, "updatedAt": datetime.now(timezone.utc)})

    @staticmethod
    def remove_stale_fcm_token(user_id: str, stale_token: str) -> None:
        UserService.remove_fcm_token(user_id, stale_token)

    # ── Password reset ─────────────────────────────────────────────────────

    @staticmethod
    def set_reset_token(user_id: str, token_hash: str, token_exp) -> None:
        UserService._db().collection(USERS_COLLECTION).document(user_id).update({
            "resetTokenHash": token_hash,
            "resetTokenExp":  token_exp,
            "updatedAt":      datetime.now(timezone.utc),
        })

    @staticmethod
    def clear_reset_token(user_id: str) -> None:
        from google.cloud.firestore import DELETE_FIELD
        UserService._db().collection(USERS_COLLECTION).document(user_id).update({
            "resetTokenHash": DELETE_FIELD,
            "resetTokenExp":  DELETE_FIELD,
            "updatedAt":      datetime.now(timezone.utc),
        })

    # ── Serialisation ─────────────────────────────────────────────────────────

    @staticmethod
    def safe_dict(user: dict) -> dict:
        """Return a public-safe version of the user dict (no passwordHash, etc.)."""
        excluded = {"passwordHash", "resetTokenHash", "resetTokenExp", "refreshTokens"}
        return {k: v for k, v in user.items() if k not in excluded}
