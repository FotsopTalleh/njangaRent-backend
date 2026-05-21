# ---------------------------------------------------------------------------
# services/user_service.py — Firestore user CRUD
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

    # ── Create ────────────────────────────────────────────────────────────────

    @staticmethod
    def create(
        email: str,
        full_name: str,
        role: str,
        password_hash: Optional[str] = None,
        phone: Optional[str] = None,
        google_id: Optional[str] = None,
    ) -> dict:
        db = UserService._db()
        now = datetime.now(timezone.utc)
        doc_ref = db.collection(USERS_COLLECTION).document()
        user_data = {
            "email":      email.lower().strip(),
            "fullName":   full_name.strip(),
            "role":       role,
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

        doc_ref.set(user_data)
        user_data["id"] = doc_ref.id
        logger.info("Created user id=%s email=%s role=%s", doc_ref.id, email, role)
        return user_data

    # ── Update ────────────────────────────────────────────────────────────────

    @staticmethod
    def update(user_id: str, updates: dict) -> None:
        updates["updatedAt"] = datetime.now(timezone.utc)
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
        # Remove existing entry for the same token (if any)
        tokens = [t for t in tokens if t.get("token") != token]
        tokens.append({
            "token":      token,
            "deviceType": device_type,
            "createdAt":  datetime.now(timezone.utc),
        })
        user_ref.update({"fcmTokens": tokens, "updatedAt": datetime.now(timezone.utc)})

    @staticmethod
    def remove_fcm_token(user_id: str, token: str) -> None:
        """Remove a single FCM token from the user's fcmTokens array."""
        user_ref = UserService._db().collection(USERS_COLLECTION).document(user_id)
        user = user_ref.get()
        if not user.exists:
            return
        tokens: list = user.to_dict().get("fcmTokens", [])
        tokens = [t for t in tokens if t.get("token") != token]
        user_ref.update({"fcmTokens": tokens, "updatedAt": datetime.now(timezone.utc)})

    @staticmethod
    def remove_stale_fcm_token(user_id: str, stale_token: str) -> None:
        """Silently remove a token that FCM reported as unregistered."""
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
        excluded = {"passwordHash", "resetTokenHash", "resetTokenExp"}
        return {k: v for k, v in user.items() if k not in excluded}
