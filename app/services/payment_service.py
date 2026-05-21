# ---------------------------------------------------------------------------
# services/payment_service.py — Payment CRUD
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone
from typing import Optional

from app.extensions import get_db

logger = logging.getLogger(__name__)

PAYMENTS_COLLECTION = "payments"


class PaymentService:

    @staticmethod
    def _db():
        return get_db()

    @staticmethod
    def get_by_id(payment_id: str) -> Optional[dict]:
        doc = PaymentService._db().collection(PAYMENTS_COLLECTION).document(payment_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    @staticmethod
    def create(
        tenant_id: str,
        user_id: str,
        landlord_id: str,
        property_id: str,
        amount_claimed: float,
        payment_date: str,
        payment_method: str,
        proof_image_url: str,
        proof_public_id: str,
        reference_number: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        db = PaymentService._db()
        now = datetime.now(timezone.utc)
        doc_ref = db.collection(PAYMENTS_COLLECTION).document()
        payment_data = {
            "tenantId":       tenant_id,
            "userId":         user_id,
            "landlordId":     landlord_id,
            "propertyId":     property_id,
            "amountClaimed":  float(amount_claimed),
            "paymentDate":    payment_date,
            "paymentMethod":  payment_method,
            "proofImageUrl":  proof_image_url,
            "proofPublicId":  proof_public_id,
            "status":         "pending",
            "submittedAt":    now,
            "createdAt":      now,
            "updatedAt":      now,
        }
        if reference_number:
            payment_data["referenceNumber"] = reference_number.strip()
        if notes:
            payment_data["notes"] = notes.strip()

        doc_ref.set(payment_data)
        payment_data["id"] = doc_ref.id
        logger.info(
            "Payment created: id=%s tenant_id=%s amount=%s",
            doc_ref.id, tenant_id, amount_claimed,
        )
        return payment_data

    @staticmethod
    def list_query(landlord_id: Optional[str] = None, user_id: Optional[str] = None,
                   status: Optional[str] = None, property_id: Optional[str] = None):
        query = PaymentService._db().collection(PAYMENTS_COLLECTION)
        if landlord_id:
            query = query.where("landlordId", "==", landlord_id)
        if user_id:
            query = query.where("userId", "==", user_id)
        if status:
            query = query.where("status", "==", status)
        if property_id:
            query = query.where("propertyId", "==", property_id)
        # Sorting is done in Python by paginate_query to avoid composite-index requirement.
        return query

    @staticmethod
    def approve(payment_id: str, landlord_note: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc)
        updates = {
            "status":     "approved",
            "reviewedAt": now,
            "updatedAt":  now,
        }
        if landlord_note:
            updates["landlordNote"] = landlord_note.strip()
        PaymentService._db().collection(PAYMENTS_COLLECTION).document(payment_id).update(updates)

    @staticmethod
    def reject(payment_id: str, rejection_reason: str) -> None:
        now = datetime.now(timezone.utc)
        PaymentService._db().collection(PAYMENTS_COLLECTION).document(payment_id).update({
            "status":          "rejected",
            "rejectionReason": rejection_reason.strip(),
            "reviewedAt":      now,
            "updatedAt":       now,
        })

    @staticmethod
    def set_ocr_data(payment_id: str, amount_extracted: Optional[float]) -> None:
        updates: dict = {"updatedAt": datetime.now(timezone.utc)}
        if amount_extracted is not None:
            updates["amountExtracted"] = float(amount_extracted)
        PaymentService._db().collection(PAYMENTS_COLLECTION).document(payment_id).update(updates)

    @staticmethod
    def set_receipt_id(payment_id: str, receipt_id: str) -> None:
        PaymentService._db().collection(PAYMENTS_COLLECTION).document(payment_id).update({
            "receiptId": receipt_id,
            "updatedAt": datetime.now(timezone.utc),
        })

    @staticmethod
    def has_approved_payment_this_month(tenant_id: str, year_month: str) -> bool:
        """Check if a tenant already has an approved payment for a given YYYY-MM."""
        docs = (
            PaymentService._db()
            .collection(PAYMENTS_COLLECTION)
            .where("tenantId", "==", tenant_id)
            .where("status", "==", "approved")
            .stream()
        )
        for doc in docs:
            d = doc.to_dict()
            if str(d.get("paymentDate", "")).startswith(year_month):
                return True
        return False
