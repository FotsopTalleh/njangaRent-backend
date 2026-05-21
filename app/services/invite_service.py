# ---------------------------------------------------------------------------
# services/invite_service.py — Invite token creation, verification, expiry
# ---------------------------------------------------------------------------
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from app.extensions import get_db
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

INVITATIONS_COLLECTION = "invitations"
_auth_service = AuthService()


class InviteService:
    """Manages invitation lifecycle: create → send → verify → complete."""

    @staticmethod
    def _db():
        return get_db()

    # ── Create invitation ────────────────────────────────────────────────────

    @staticmethod
    def create_invitation(
        email: str,
        landlord_id: str,
        property_id: str,
        monthly_rent: float,
        rent_due_day: int,
    ) -> tuple[str, str]:
        """Create a JWT invite token and persist its hash in Firestore.

        Returns:
            Tuple of (raw_token, invitation_doc_id)

        Raises:
            ValueError — if a pending/accepted invitation already exists for
                         this email + propertyId combination.
        """
        db = InviteService._db()

        # Guard: check for existing pending/accepted invitation
        existing = (
            db.collection(INVITATIONS_COLLECTION)
            .where("email", "==", email.lower().strip())
            .where("propertyId", "==", property_id)
            .where("status", "in", ["pending", "accepted"])
            .limit(1)
            .stream()
        )
        for _ in existing:
            raise ValueError("An active invitation already exists for this email and property.")

        raw_token, token_hash = _auth_service.create_invite_token(
            email=email.lower().strip(),
            property_id=property_id,
            landlord_id=landlord_id,
            monthly_rent=monthly_rent,
            rent_due_day=rent_due_day,
            expiry_hours=72,
        )

        from datetime import timedelta
        now = datetime.now(timezone.utc)
        doc_ref = db.collection(INVITATIONS_COLLECTION).document()
        doc_ref.set({
            "tokenHash":   token_hash,
            "email":       email.lower().strip(),
            "landlordId":  landlord_id,
            "propertyId":  property_id,
            "monthlyRent": float(monthly_rent),
            "rentDueDay":  int(rent_due_day),
            "status":      "pending",
            "expiresAt":   now + timedelta(hours=72),
            "createdAt":   now,
        })

        logger.info(
            "Invitation created: id=%s email=%s property_id=%s",
            doc_ref.id, email, property_id,
        )
        return raw_token, doc_ref.id

    # ── Verify invitation ─────────────────────────────────────────────────────

    @staticmethod
    def verify_invitation(raw_token: str) -> tuple[dict, dict]:
        """Verify a raw invite token string.

        Returns:
            Tuple of (jwt_payload, invitation_doc_dict)

        Raises:
            AuthService.TokenExpiredError
            AuthService.TokenInvalidError
            ValueError — if invitation not found or already used
        """
        from app.utils.constants import AUTH_INVITE_EXPIRED, AUTH_INVITE_INVALID, AUTH_INVITE_USED

        # 1. Verify JWT signature & expiry
        payload = _auth_service.verify_invite_token(raw_token)

        # 2. Look up by token hash
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        db = InviteService._db()
        docs = (
            db.collection(INVITATIONS_COLLECTION)
            .where("tokenHash", "==", token_hash)
            .limit(1)
            .stream()
        )
        invitation = None
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            invitation = data
            break

        if not invitation:
            raise ValueError("Invitation not found.")

        if invitation["status"] == "accepted":
            raise ValueError("Invitation has already been used.")

        if invitation["status"] == "expired":
            raise ValueError("Invitation has expired.")

        # Check Firestore-level expiry
        expires_at = invitation.get("expiresAt")
        if expires_at:
            exp_dt = expires_at if hasattr(expires_at, "tzinfo") else expires_at.replace(tzinfo=timezone.utc)
            if exp_dt < datetime.now(timezone.utc):
                # Mark as expired in DB
                db.collection(INVITATIONS_COLLECTION).document(invitation["id"]).update(
                    {"status": "expired"}
                )
                raise ValueError("Invitation has expired.")

        return payload, invitation

    # ── Mark invitation accepted ──────────────────────────────────────────────

    @staticmethod
    def accept_invitation(invitation_id: str) -> None:
        now = datetime.now(timezone.utc)
        InviteService._db().collection(INVITATIONS_COLLECTION).document(invitation_id).update({
            "status":     "accepted",
            "acceptedAt": now,
        })
        logger.info("Invitation accepted: id=%s", invitation_id)
