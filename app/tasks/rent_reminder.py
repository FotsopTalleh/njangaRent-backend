# ---------------------------------------------------------------------------
# tasks/rent_reminder.py — Celery task: daily rent reminders
# ---------------------------------------------------------------------------
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# We must import celery_app from the tasks package (not app.tasks to avoid
# circular imports with the Flask app factory).
from tasks.celery_app import celery_app  # noqa: E402

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.rent_reminder.send_rent_reminders", bind=True, max_retries=3)
def send_rent_reminders(self):
    """Daily task: send FCM rent reminders to tenants whose rent is due today.

    Logic:
        1. Get today's day-of-month.
        2. Query active tenants with rentDueDay == today.
        3. For each tenant, check if they have an approved payment this month.
        4. If not → send push reminder.
    """
    # Bootstrap Firebase Admin + Firestore for Celery worker context
    _bootstrap_firebase()

    from app.services.notification_service import NotificationService
    from app.services.payment_service import PaymentService
    from app.services.property_service import PropertyService
    from app.services.tenant_service import TenantService

    now         = datetime.now(timezone.utc)
    today_day   = now.day
    year_month  = now.strftime("%Y-%m")

    logger.info("Rent reminder task started: day=%d month=%s", today_day, year_month)

    tenants = TenantService.get_due_today(today_day)
    logger.info("Tenants due today: %d", len(tenants))

    sent_count = 0
    for tenant in tenants:
        try:
            # Skip if already paid this month
            already_paid = PaymentService.has_approved_payment_this_month(
                tenant_id=tenant["id"],
                year_month=year_month,
            )
            if already_paid:
                logger.debug("Tenant %s already paid for %s — skipping", tenant["id"], year_month)
                continue

            # Fetch property name
            prop = PropertyService.get_by_id(tenant.get("propertyId", ""))
            property_name = prop["name"] if prop else "your property"

            NotificationService.notify_rent_reminder(
                tenant_user_id = tenant["userId"],
                property_name  = property_name,
                monthly_rent   = tenant.get("monthlyRent", 0),
                property_id    = tenant.get("propertyId", ""),
                landlord_id    = tenant.get("landlordId", ""),
            )
            sent_count += 1
        except Exception as exc:
            logger.error("Failed to send reminder for tenant %s: %s", tenant.get("id"), exc)

    logger.info("Rent reminder task complete: sent=%d / total=%d", sent_count, len(tenants))
    return {"sent": sent_count, "total": len(tenants)}


def _bootstrap_firebase():
    """Initialise Firebase Admin SDK for the Celery worker process.

    The Celery workers run outside of the Flask app context, so we must
    initialise Firebase Admin here if it hasn't been initialised yet.
    """
    try:
        import firebase_admin
        if not firebase_admin._apps:
            from firebase_admin import credentials
            sa_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "./firebase-service-account.json")
            cred = credentials.Certificate(sa_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin initialised in Celery worker.")
    except Exception as exc:
        logger.exception("Failed to initialise Firebase Admin in Celery worker: %s", exc)
        raise
