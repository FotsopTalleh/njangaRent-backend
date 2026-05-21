# ---------------------------------------------------------------------------
# services/notification_service.py — FCM push + Firestore notification docs
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone
from typing import Optional

from firebase_admin import messaging

from app.extensions import get_db
from app.services.user_service import UserService
from app.utils.constants import (
    NOTIF_PAYMENT_APPROVED,
    NOTIF_PAYMENT_REJECTED,
    NOTIF_PAYMENT_SUBMITTED,
    NOTIF_RENT_REMINDER,
)

logger = logging.getLogger(__name__)

NOTIFICATIONS_COLLECTION = "notifications"


class NotificationService:
    """Handles FCM push notifications and in-app notification documents."""

    @staticmethod
    def _db():
        return get_db()

    # ── Push + notification doc ──────────────────────────────────────────────

    @classmethod
    def send_push(
        cls,
        user_id: str,
        title: str,
        body: str,
        data: Optional[dict] = None,
        notification_type: Optional[str] = None,
    ) -> None:
        """Send FCM push to all registered devices for a user.

        Stale tokens (UnregisteredError / SenderIdMismatchError) are silently removed.
        Never raises — push failure must not break the calling flow.
        """
        if data is None:
            data = {}

        # FCM data payload values must be strings
        str_data = {k: str(v) for k, v in data.items()}

        user = UserService.get_by_id(user_id)
        if not user:
            logger.warning("send_push: user not found user_id=%s", user_id)
            return

        fcm_tokens: list = user.get("fcmTokens", [])
        if not fcm_tokens:
            logger.debug("send_push: no FCM tokens for user_id=%s", user_id)
        else:
            for token_entry in fcm_tokens:
                token = token_entry.get("token")
                if not token:
                    continue
                try:
                    message = messaging.Message(
                        notification=messaging.Notification(title=title, body=body),
                        data=str_data,
                        token=token,
                        android=messaging.AndroidConfig(priority="high"),
                        apns=messaging.APNSConfig(
                            headers={"apns-priority": "10"}
                        ),
                    )
                    messaging.send(message)
                    logger.debug("FCM push sent: user_id=%s token=...%s", user_id, token[-6:])
                except messaging.UnregisteredError:
                    logger.info("Removing stale FCM token for user_id=%s", user_id)
                    UserService.remove_stale_fcm_token(user_id, token)
                except messaging.SenderIdMismatchError:
                    logger.warning("SenderIdMismatch — removing token for user_id=%s", user_id)
                    UserService.remove_stale_fcm_token(user_id, token)
                except Exception as exc:
                    logger.error("FCM send failed for user_id=%s: %s", user_id, exc)

        # Always create the in-app notification document
        cls.create_notification_doc(user_id, notification_type, title, body, data)

    @classmethod
    def create_notification_doc(
        cls,
        user_id: str,
        notification_type: Optional[str],
        title: str,
        body: str,
        data: Optional[dict] = None,
    ) -> str:
        """Persist a notification document in Firestore.

        Returns:
            The new notification document ID.
        """
        if data is None:
            data = {}

        now = datetime.now(timezone.utc)
        doc_ref = cls._db().collection(NOTIFICATIONS_COLLECTION).document()
        doc_ref.set({
            "userId":    user_id,
            "type":      notification_type or "",
            "title":     title,
            "body":      body,
            "data":      {k: str(v) for k, v in data.items()},
            "read":      False,
            "createdAt": now,
        })
        logger.debug(
            "Notification doc created: id=%s user_id=%s type=%s",
            doc_ref.id, user_id, notification_type,
        )
        return doc_ref.id

    # ── Convenience wrappers ──────────────────────────────────────────────────

    @classmethod
    def notify_payment_submitted(cls, landlord_id: str, payment_id: str, tenant_name: str) -> None:
        cls.send_push(
            user_id=landlord_id,
            title="New Payment Submitted",
            body=f"{tenant_name} has submitted a payment. Please review it.",
            data={"paymentId": payment_id},
            notification_type=NOTIF_PAYMENT_SUBMITTED,
        )

    @classmethod
    def notify_payment_approved(
        cls,
        tenant_id: str,
        payment_id: str,
        property_name: str,
        receipt_number: str,
        receipt_id: str,
    ) -> None:
        cls.send_push(
            user_id=tenant_id,
            title="Payment Approved",
            body=(
                f"Your payment for {property_name} has been approved. "
                f"Receipt #{receipt_number} is ready."
            ),
            data={"paymentId": payment_id, "receiptId": receipt_id},
            notification_type=NOTIF_PAYMENT_APPROVED,
        )

    @classmethod
    def notify_payment_rejected(
        cls, tenant_id: str, payment_id: str, reason: Optional[str] = None
    ) -> None:
        body = "Your payment has been rejected."
        if reason:
            body += f" Reason: {reason}"
        cls.send_push(
            user_id=tenant_id,
            title="Payment Rejected",
            body=body,
            data={"paymentId": payment_id},
            notification_type=NOTIF_PAYMENT_REJECTED,
        )

    @classmethod
    def notify_rent_reminder(
        cls,
        tenant_user_id: str,
        property_name: str,
        monthly_rent: float,
        property_id: str,
        landlord_id: str,
        currency: str = "",
    ) -> None:
        cls.send_push(
            user_id=tenant_user_id,
            title="Rent Due Today",
            body=f"Your rent of {currency}{monthly_rent} for {property_name} is due today.",
            data={"propertyId": property_id, "landlordId": landlord_id},
            notification_type=NOTIF_RENT_REMINDER,
        )
