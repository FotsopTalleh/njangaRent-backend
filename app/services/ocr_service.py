# ---------------------------------------------------------------------------
# services/ocr_service.py — Triggers n8n webhook (fire-and-forget)
# ---------------------------------------------------------------------------
import logging
import os
import threading
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class OcrService:
    """Triggers the n8n OCR + messaging webhook in a background thread (fire-and-forget).

    n8n workflow responsibilities:
      1. Download the proof image from proofImageUrl.
      2. OCR-extract the amount and any other relevant data.
      3. Send a message to the landlord (WhatsApp / email) summarising what was extracted.
      4. POST back to callbackUrl with { paymentId, extractedAmount, ocrSuccess, ocrError }.

    Flask stores the extracted amount on the payment doc.
    When the landlord approves, the receipt uses that OCR-verified amount as amountPaid.
    """

    @staticmethod
    def trigger_ocr(
        payment_id: str,
        proof_image_url: str,
        landlord_id: str,
        tenant_id: str,
        # Enrichment fields — fetched by caller so n8n needs no extra API calls
        landlord_name: str = "",
        landlord_phone: str = "",
        landlord_email: str = "",
        tenant_name: str = "",
        amount_claimed: float = 0.0,
        payment_date: str = "",
        payment_method: str = "",
        property_name: str = "",
        callback_url: Optional[str] = None,
    ) -> None:
        """Send OCR + messaging trigger to n8n in a daemon background thread.

        Args:
            payment_id:      Firestore payment doc ID.
            proof_image_url: Cloudinary URL of the payment proof image.
            landlord_id:     Landlord user ID (for n8n cross-reference).
            tenant_id:       Tenant doc ID (for n8n cross-reference).
            landlord_name:   Landlord's full name — used in the message n8n sends.
            landlord_phone:  Landlord's phone number — n8n sends WhatsApp/SMS here.
            landlord_email:  Landlord's email — n8n sends email here if no phone.
            tenant_name:     Tenant's full name — included in the message body.
            amount_claimed:  Amount the tenant says they paid — shown alongside OCR result.
            payment_date:    Payment date string (YYYY-MM-DD).
            payment_method:  E.g. "bank_transfer", "mobile_money", etc.
            property_name:   Property name — for message context.
            callback_url:    URL n8n should POST results to (defaults to env var).
        """
        n8n_url    = os.environ.get("N8N_OCR_TRIGGER_URL", "http://n8n:5678/webhook/ocr-trigger")
        secret     = os.environ.get("N8N_WEBHOOK_SECRET", "")
        flask_host = os.environ.get("FLASK_INTERNAL_URL", "http://flask:5000")
        cb_url     = callback_url or f"{flask_host}/webhooks/n8n/ocr-result"

        payload = {
            # ── Core identifiers ─────────────────────────────────────────────
            "paymentId":     payment_id,
            "proofImageUrl": proof_image_url,
            "landlordId":    landlord_id,
            "tenantId":      tenant_id,
            "callbackUrl":   cb_url,

            # ── Contact info — n8n sends a message to the landlord ────────────
            "landlordName":  landlord_name,
            "landlordPhone": landlord_phone,
            "landlordEmail": landlord_email,

            # ── Payment context — shown in the landlord's message ─────────────
            "tenantName":    tenant_name,
            "amountClaimed": amount_claimed,
            "paymentDate":   payment_date,
            "paymentMethod": payment_method,
            "propertyName":  property_name,
        }
        headers = {
            "Content-Type": "application/json",
            "X-N8N-Secret": secret,
        }

        def _send():
            try:
                resp = requests.post(n8n_url, json=payload, headers=headers, timeout=10)
                logger.info(
                    "n8n OCR trigger sent: payment_id=%s status=%s",
                    payment_id, resp.status_code,
                )
            except requests.RequestException as exc:
                logger.error(
                    "Failed to trigger n8n OCR webhook for payment_id=%s: %s",
                    payment_id, exc,
                )

        thread = threading.Thread(target=_send, daemon=True)
        thread.start()
