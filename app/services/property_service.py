# ---------------------------------------------------------------------------
# services/property_service.py — Property CRUD
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone
from typing import Optional

from app.extensions import get_db

logger = logging.getLogger(__name__)

PROPERTIES_COLLECTION = "properties"
TENANTS_COLLECTION    = "tenants"


class PropertyService:

    @staticmethod
    def _db():
        return get_db()

    @staticmethod
    def get_by_id(property_id: str) -> Optional[dict]:
        doc = PropertyService._db().collection(PROPERTIES_COLLECTION).document(property_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    @staticmethod
    def list_for_landlord(landlord_id: str):
        # NOTE: Combining .where() + .order_by() on different fields requires a
        # Firestore composite index. Until that index is deployed, we filter only
        # and sort the results in Python inside paginate_query.
        return (
            PropertyService._db()
            .collection(PROPERTIES_COLLECTION)
            .where("landlordId", "==", landlord_id)
        )

    @staticmethod
    def create(landlord_id: str, data: dict) -> dict:
        db = PropertyService._db()
        now = datetime.now(timezone.utc)
        doc_ref = db.collection(PROPERTIES_COLLECTION).document()
        doc_data = {
            "landlordId":   landlord_id,
            "name":         data["name"].strip(),
            "address":      data["address"].strip(),
            "description":  data.get("description", "").strip(),
            "propertyType": data["propertyType"],
            "monthlyRent":  float(data["monthlyRent"]),
            "tenantCount":  0,
            "createdAt":    now,
            "updatedAt":    now,
        }
        doc_ref.set(doc_data)
        doc_data["id"] = doc_ref.id
        return doc_data

    @staticmethod
    def update(property_id: str, updates: dict) -> None:
        allowed = {"name", "address", "description", "propertyType", "monthlyRent"}
        clean = {k: v for k, v in updates.items() if k in allowed}
        if "name" in clean:
            clean["name"] = clean["name"].strip()
        if "address" in clean:
            clean["address"] = clean["address"].strip()
        if "monthlyRent" in clean:
            clean["monthlyRent"] = float(clean["monthlyRent"])
        clean["updatedAt"] = datetime.now(timezone.utc)
        PropertyService._db().collection(PROPERTIES_COLLECTION).document(property_id).update(clean)

    @staticmethod
    def delete(property_id: str) -> None:
        PropertyService._db().collection(PROPERTIES_COLLECTION).document(property_id).delete()

    @staticmethod
    def has_active_tenants(property_id: str) -> bool:
        docs = (
            PropertyService._db()
            .collection(TENANTS_COLLECTION)
            .where("propertyId", "==", property_id)
            .where("status", "==", "active")
            .limit(1)
            .stream()
        )
        return any(True for _ in docs)

    @staticmethod
    def increment_tenant_count(property_id: str, delta: int = 1) -> None:
        from google.cloud.firestore import Increment
        PropertyService._db().collection(PROPERTIES_COLLECTION).document(property_id).update(
            {"tenantCount": Increment(delta), "updatedAt": datetime.now(timezone.utc)}
        )

    @staticmethod
    def get_active_tenants(property_id: str) -> list:
        docs = (
            PropertyService._db()
            .collection(TENANTS_COLLECTION)
            .where("propertyId", "==", property_id)
            .where("status", "==", "active")
            .stream()
        )
        results = []
        for doc in docs:
            d = doc.to_dict()
            d["id"] = doc.id
            results.append(d)
        return results
