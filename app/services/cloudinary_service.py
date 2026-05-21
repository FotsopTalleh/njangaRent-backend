# ---------------------------------------------------------------------------
# services/cloudinary_service.py — All Cloudinary upload/delete operations
# ---------------------------------------------------------------------------
import logging
from typing import Optional

import cloudinary.uploader

logger = logging.getLogger(__name__)


class CloudinaryService:
    """Wraps all Cloudinary interactions — uploads and deletes."""

    # ── Payment proof upload ─────────────────────────────────────────────────

    @staticmethod
    def upload_payment_proof(
        file,
        landlord_id: str,
        tenant_id: str,
    ) -> dict:
        """Upload a payment proof image/PDF to Cloudinary.

        Args:
            file:        A werkzeug FileStorage (or any file-like object).
            landlord_id: Used to build the Cloudinary folder path.
            tenant_id:   Used to build the Cloudinary folder path.

        Returns:
            dict with keys: secure_url, public_id
        """
        folder = f"mytenant/payments/{landlord_id}/{tenant_id}"
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            resource_type="auto",  # handles images and PDFs
            use_filename=False,
            unique_filename=True,
        )
        logger.info(
            "Uploaded payment proof: public_id=%s url=%s",
            result["public_id"],
            result["secure_url"],
        )
        return {
            "secure_url": result["secure_url"],
            "public_id":  result["public_id"],
        }

    # ── Receipt PDF upload ────────────────────────────────────────────────────

    @staticmethod
    def upload_receipt_pdf(
        pdf_bytes: bytes,
        landlord_id: str,
        tenant_id: str,
        receipt_number: str,
    ) -> dict:
        """Upload a generated receipt PDF (as raw bytes) to Cloudinary.

        Args:
            pdf_bytes:      Raw PDF bytes from WeasyPrint.
            landlord_id:    Used to build the Cloudinary folder path.
            tenant_id:      Used to build the Cloudinary folder path.
            receipt_number: Human-readable receipt number used as the public_id suffix.

        Returns:
            dict with keys: secure_url, public_id
        """
        folder     = f"mytenant/receipts/{landlord_id}/{tenant_id}"
        public_id  = f"{folder}/receipt-{receipt_number}"

        result = cloudinary.uploader.upload(
            pdf_bytes,
            public_id=public_id,
            resource_type="raw",   # PDFs must be uploaded as raw
            overwrite=True,
        )
        logger.info(
            "Uploaded receipt PDF: public_id=%s url=%s",
            result["public_id"],
            result["secure_url"],
        )
        return {
            "secure_url": result["secure_url"],
            "public_id":  result["public_id"],
        }

    # ── Delete ────────────────────────────────────────────────────────────────

    @staticmethod
    def delete_resource(public_id: str, resource_type: str = "image") -> None:
        """Delete a Cloudinary resource by public_id.

        Args:
            public_id:     The Cloudinary public_id.
            resource_type: "image" | "raw" | "video"
        """
        try:
            result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
            logger.info("Deleted Cloudinary resource: public_id=%s result=%s", public_id, result)
        except Exception as exc:
            logger.error("Failed to delete Cloudinary resource %s: %s", public_id, exc)
