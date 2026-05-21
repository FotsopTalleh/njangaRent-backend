# ---------------------------------------------------------------------------
# services/tenant_service.py — Tenant CRUD
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone
from typing import Optional

from app.extensions import get_db

logger = logging.getLogger(__name__)

TENANTS_COLLECTION = "tenants"


class TenantService:

    @staticmethod
    def _db():
        return get_db()

    @staticmethod
    def get_by_id(tenant_id: str) -> Optional[dict]:
        doc = TenantService._db().collection(TENANTS_COLLECTION).document(tenant_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    @staticmethod
    def get_by_user_and_landlord(user_id: str, landlord_id: str) -> Optional[dict]:
        docs = (
            TenantService._db()
            .collection(TENANTS_COLLECTION)
            .where("userId", "==", user_id)
            .where("landlordId", "==", landlord_id)
            .limit(1)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    @staticmethod
    def get_by_user_id(user_id: str) -> Optional[dict]:
        docs = (
            TenantService._db()
            .collection(TENANTS_COLLECTION)
            .where("userId", "==", user_id)
            .where("status", "==", "active")
            .limit(1)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    @staticmethod
    def list_for_landlord(landlord_id: str, property_id: Optional[str] = None, status: Optional[str] = None):
        query = (
            TenantService._db()
            .collection(TENANTS_COLLECTION)
            .where("landlordId", "==", landlord_id)
        )
        if property_id:
            query = query.where("propertyId", "==", property_id)
        if status:
            query = query.where("status", "==", status)
        # Sorting is done in Python by paginate_query to avoid composite-index requirement.
        return query

    @staticmethod
    def create(
        user_id: str,
        landlord_id: str,
        property_id: str,
        monthly_rent: float,
        rent_due_day: int,
    ) -> dict:
        db = TenantService._db()
        now = datetime.now(timezone.utc)
        doc_ref = db.collection(TENANTS_COLLECTION).document()
        tenant_data = {
            "userId":      user_id,
            "landlordId":  landlord_id,
            "propertyId":  property_id,
            "monthlyRent": float(monthly_rent),
            "rentDueDay":  int(rent_due_day),
            "status":      "active",
            "createdAt":   now,
            "updatedAt":   now,
        }
        doc_ref.set(tenant_data)
        tenant_data["id"] = doc_ref.id
        logger.info(
            "Created tenant id=%s user_id=%s property_id=%s",
            doc_ref.id, user_id, property_id,
        )
        return tenant_data

    @staticmethod
    def remove(tenant_id: str) -> None:
        TenantService._db().collection(TENANTS_COLLECTION).document(tenant_id).update({
            "status":    "removed",
            "updatedAt": datetime.now(timezone.utc),
        })
        logger.info("Tenant removed: id=%s", tenant_id)

    @staticmethod
    def get_due_today(day_of_month: int) -> list:
        """Return all active tenants whose rentDueDay matches today's day."""
        docs = (
            TenantService._db()
            .collection(TENANTS_COLLECTION)
            .where("rentDueDay", "==", day_of_month)
            .where("status", "==", "active")
            .stream()
        )
        results = []
        for doc in docs:
            d = doc.to_dict()
            d["id"] = doc.id
            results.append(d)
        return results
