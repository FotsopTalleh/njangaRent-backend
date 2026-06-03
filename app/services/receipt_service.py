# ---------------------------------------------------------------------------
# services/receipt_service.py — WeasyPrint PDF generation + Cloudinary upload
# ---------------------------------------------------------------------------
import logging
import os
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader, select_autoescape

# WeasyPrint requires native GTK + Cairo libraries.
# On Windows: install GTK3 runtime from https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer
# Or run the backend inside Docker where dependencies are pre-installed.
try:
    from weasyprint import HTML as _WeasyHTML
    _WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    _WeasyHTML = None
    _WEASYPRINT_AVAILABLE = False

from app.extensions import get_db
from app.services.cloudinary_service import CloudinaryService
from app.services.payment_service import PaymentService
from app.services.property_service import PropertyService
from app.services.tenant_service import TenantService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

RECEIPTS_COLLECTION = "receipts"


class ReceiptService:
    """Generate a PDF receipt from an approved payment and store it."""

    # Jinja2 environment pointing at templates/receipts/
    _TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates", "receipts")
    _jinja_env = None

    @classmethod
    def _get_jinja_env(cls) -> Environment:
        if cls._jinja_env is None:
            cls._jinja_env = Environment(
                loader=FileSystemLoader(cls._TEMPLATE_DIR),
                autoescape=select_autoescape(["html"]),
            )
        return cls._jinja_env

    @staticmethod
    def _db():
        return get_db()

    # ── Receipt number generator ──────────────────────────────────────────────

    @staticmethod
    def _generate_receipt_number() -> str:
        """Generate a human-readable receipt number: RCT-YYYYMM-XXXX.

        The sequence is based on the count of receipts already created this month.
        """
        from app.utils.constants import RECEIPT_NUMBER_PREFIX

        prefix = os.environ.get("RECEIPT_NUMBER_PREFIX", RECEIPT_NUMBER_PREFIX)
        now = datetime.now(timezone.utc)
        year_month = now.strftime("%Y%m")

        # Count existing receipts this month to derive sequence number
        db = get_db()
        docs = (
            db.collection(RECEIPTS_COLLECTION)
            .where("receiptNumber", ">=", f"{prefix}-{year_month}-")
            .where("receiptNumber", "<", f"{prefix}-{year_month}-9999")
            .stream()
        )
        count = sum(1 for _ in docs)
        sequence = str(count + 1).zfill(4)
        return f"{prefix}-{year_month}-{sequence}"

    # ── Main entry point ──────────────────────────────────────────────────────

    @classmethod
    def generate_receipt(cls, payment_id: str) -> dict:
        """Full receipt generation pipeline.

        Flow:
            1. Fetch payment, tenant, landlord, property documents.
            2. Generate receipt number.
            3. Render HTML via Jinja2 template.
            4. Convert HTML → PDF bytes via WeasyPrint.
            5. Upload PDF to Cloudinary.
            6. Create receipt Firestore document.
            7. Update payment with receiptId.

        Args:
            payment_id: Firestore payment document ID.

        Returns:
            Receipt document dict (includes id, pdfUrl, receiptNumber).
        """
        # ── 1. Fetch related documents ────────────────────────────────────────
        payment = PaymentService.get_by_id(payment_id)
        if not payment:
            raise ValueError(f"Payment not found: {payment_id}")

        tenant = TenantService.get_by_id(payment["tenantId"])
        if not tenant:
            raise ValueError(f"Tenant not found: {payment['tenantId']}")

        tenant_user = UserService.get_by_id(tenant["userId"])
        if not tenant_user:
            raise ValueError(f"Tenant user not found: {tenant['userId']}")

        landlord_user = UserService.get_by_id(payment["landlordId"])
        if not landlord_user:
            raise ValueError(f"Landlord user not found: {payment['landlordId']}")

        property_doc = PropertyService.get_by_id(payment["propertyId"])
        if not property_doc:
            raise ValueError(f"Property not found: {payment['propertyId']}")

        # ── 2. Generate receipt number ────────────────────────────────────────
        receipt_number = cls._generate_receipt_number()

        # ── 2b. Resolve the amount to print on the receipt ────────────────────
        # Use the OCR-extracted amount (from n8n callback) when available —
        # this is the independently verified figure, not the tenant's self-report.
        # Fall back to amountClaimed only if OCR hasn't completed yet.
        ocr_amount    = payment.get("amountExtracted")
        amount_to_use = float(ocr_amount) if ocr_amount is not None else float(payment.get("amountClaimed", 0))
        logger.info(
            "Receipt amount resolved: payment_id=%s ocr=%s claimed=%s using=%s",
            payment_id, ocr_amount, payment.get("amountClaimed"), amount_to_use,
        )

        # ── 3. Render HTML ────────────────────────────────────────────────────
        template = cls._get_jinja_env().get_template("receipt.html")
        generated_at = datetime.now(timezone.utc)
        html_content = template.render(
            tenantName      = tenant_user.get("fullName", ""),
            landlordName    = landlord_user.get("fullName", ""),
            propertyName    = property_doc.get("name", ""),
            propertyAddress = property_doc.get("address", ""),
            amountPaid      = amount_to_use,
            amountClaimed   = payment.get("amountClaimed"),
            amountExtracted = ocr_amount,
            paymentDate     = payment.get("paymentDate"),
            paymentMethod   = payment.get("paymentMethod", ""),
            referenceNumber = payment.get("referenceNumber", ""),
            receiptNumber   = receipt_number,
            generatedAt     = generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        )

        # ── 4. Convert to PDF ─────────────────────────────────────────────────
        # WeasyPrint may import successfully on Windows but still fail at
        # runtime with an OSError if GTK3 is not in PATH.  Wrap write_pdf()
        # in its own guard so the receipt record is always created.
        pdf_bytes = None
        if _WEASYPRINT_AVAILABLE:
            try:
                pdf_bytes = _WeasyHTML(string=html_content).write_pdf()
            except Exception as wp_exc:
                logger.warning(
                    "WeasyPrint write_pdf() failed (likely missing GTK on Windows) "
                    "— receipt will be created without a PDF download link. Error: %s",
                    wp_exc,
                )
        else:
            logger.warning(
                "WeasyPrint not installed — receipt created without PDF. "
                "Run in Docker or install the GTK3 runtime for PDF support."
            )

        # ── 5. Upload PDF to Cloudinary (skip if no PDF bytes) ────────────────
        if pdf_bytes is not None:
            upload_result = CloudinaryService.upload_receipt_pdf(
                pdf_bytes      = pdf_bytes,
                landlord_id    = payment["landlordId"],
                tenant_id      = payment["tenantId"],
                receipt_number = receipt_number,
            )
            pdf_url       = upload_result["secure_url"]
            pdf_public_id = upload_result["public_id"]
        else:
            pdf_url       = ""
            pdf_public_id = ""

        # ── 6. Create receipt document ────────────────────────────────────────
        db = cls._db()
        now = datetime.now(timezone.utc)
        doc_ref = db.collection(RECEIPTS_COLLECTION).document()
        receipt_data = {
            "paymentId":       payment_id,
            "tenantId":        payment["tenantId"],
            "landlordId":      payment["landlordId"],
            "propertyId":      payment["propertyId"],
            "tenantName":      tenant_user.get("fullName", ""),
            "landlordName":    landlord_user.get("fullName", ""),
            "propertyName":    property_doc.get("name", ""),
            "propertyAddress": property_doc.get("address", ""),
            "amountPaid":      amount_to_use,
            "amountClaimed":   payment.get("amountClaimed"),
            "amountExtracted": ocr_amount,
            "paymentDate":     payment.get("paymentDate"),
            "paymentMethod":   payment.get("paymentMethod", ""),
            "referenceNumber": payment.get("referenceNumber", ""),
            "notes":           payment.get("notes", ""),
            "receiptNumber":   receipt_number,
            "pdfUrl":          pdf_url,
            "pdfPublicId":     pdf_public_id,
            "generatedAt":     generated_at,
            "status":          "disbursed",  # auto-generated receipts are immediately final
            "createdAt":       now,
        }
        doc_ref.set(receipt_data)
        receipt_data["id"] = doc_ref.id

        # ── 7. Update payment with receiptId ──────────────────────────────────
        PaymentService.set_receipt_id(payment_id, doc_ref.id)

        logger.info(
            "Receipt generated: id=%s number=%s payment_id=%s",
            doc_ref.id, receipt_number, payment_id,
        )
        return receipt_data

    # ── Draft receipt (created immediately after approve) ─────────────────────

    @classmethod
    def create_draft_receipt(cls, payment_id: str) -> dict:
        """Create a draft receipt with pre-filled data from the payment.

        The draft is not sent to the tenant and has no PDF yet.
        The landlord reviews and edits it, then calls disburse_receipt().

        Returns:
            Draft receipt document dict (includes id, status="draft").
        """
        payment = PaymentService.get_by_id(payment_id)
        if not payment:
            raise ValueError(f"Payment not found: {payment_id}")

        tenant = TenantService.get_by_id(payment["tenantId"])
        if not tenant:
            raise ValueError(f"Tenant not found: {payment['tenantId']}")

        tenant_user = UserService.get_by_id(tenant["userId"])
        landlord_user = UserService.get_by_id(payment["landlordId"])
        property_doc = PropertyService.get_by_id(payment["propertyId"])

        receipt_number = cls._generate_receipt_number()

        ocr_amount = payment.get("amountExtracted")
        amount_to_use = float(ocr_amount) if ocr_amount is not None else float(payment.get("amountClaimed", 0))

        db = cls._db()
        now = datetime.now(timezone.utc)
        doc_ref = db.collection(RECEIPTS_COLLECTION).document()
        receipt_data = {
            "paymentId":       payment_id,
            "tenantId":        payment["tenantId"],
            "landlordId":      payment["landlordId"],
            "propertyId":      payment["propertyId"],
            "tenantName":      tenant_user.get("fullName", "") if tenant_user else "",
            "landlordName":    landlord_user.get("fullName", "") if landlord_user else "",
            "propertyName":    property_doc.get("name", "") if property_doc else "",
            "propertyAddress": property_doc.get("address", "") if property_doc else "",
            "amountPaid":      amount_to_use,
            "amountClaimed":   payment.get("amountClaimed"),
            "amountExtracted": ocr_amount,
            "paymentDate":     payment.get("paymentDate", ""),
            "paymentMethod":   payment.get("paymentMethod", ""),
            "referenceNumber": payment.get("referenceNumber", ""),
            "notes":           payment.get("notes", ""),
            "periodLabel":     "",   # landlord fills this in (e.g. "January 2025")
            "receiptNumber":   receipt_number,
            "pdfUrl":          "",
            "pdfPublicId":     "",
            "generatedAt":     now,
            "status":          "draft",
            "createdAt":       now,
        }
        doc_ref.set(receipt_data)
        receipt_data["id"] = doc_ref.id
        PaymentService.set_receipt_id(payment_id, doc_ref.id)

        logger.info(
            "Draft receipt created: id=%s number=%s payment_id=%s",
            doc_ref.id, receipt_number, payment_id,
        )
        return receipt_data

    # ── Disburse (landlord finalises + sends to tenant) ───────────────────────

    @classmethod
    def disburse_receipt(cls, receipt_id: str, edits: dict) -> dict:
        """Apply landlord edits, generate PDF, mark as disbursed.

        Args:
            receipt_id: Firestore receipt document ID.
            edits: Dict of overrideable fields (tenantName, amountPaid,
                   paymentDate, paymentMethod, notes, periodLabel, referenceNumber).

        Returns:
            Updated receipt dict.
        """
        db = cls._db()
        doc = db.collection(RECEIPTS_COLLECTION).document(receipt_id).get()
        if not doc.exists:
            raise ValueError(f"Receipt not found: {receipt_id}")

        receipt = doc.to_dict()
        receipt["id"] = receipt_id

        if receipt.get("status") == "disbursed":
            raise ValueError("Receipt has already been disbursed.")

        # Apply edits (only override fields the landlord explicitly provided)
        allowed_edits = {
            "tenantName", "amountPaid", "paymentDate",
            "paymentMethod", "notes", "periodLabel", "referenceNumber",
        }
        for field, value in edits.items():
            if field in allowed_edits and value is not None:
                receipt[field] = value

        # ── Render HTML + generate PDF ────────────────────────────────────────
        amount_paid = receipt.get("amountPaid") or 0
        try:
            amount_paid = float(amount_paid)
        except (TypeError, ValueError):
            amount_paid = 0.0

        template = cls._get_jinja_env().get_template("receipt.html")
        generated_at = datetime.now(timezone.utc)
        html_content = template.render(
            tenantName      = receipt.get("tenantName", ""),
            landlordName    = receipt.get("landlordName", ""),
            propertyName    = receipt.get("propertyName", ""),
            propertyAddress = receipt.get("propertyAddress", ""),
            amountPaid      = amount_paid,
            amountClaimed   = receipt.get("amountClaimed"),
            amountExtracted = receipt.get("amountExtracted"),
            paymentDate     = receipt.get("paymentDate", ""),
            paymentMethod   = receipt.get("paymentMethod", ""),
            referenceNumber = receipt.get("referenceNumber", ""),
            receiptNumber   = receipt.get("receiptNumber", ""),
            periodLabel     = receipt.get("periodLabel", ""),
            notes           = receipt.get("notes", ""),
            generatedAt     = generated_at.strftime("%Y-%m-%d %H:%M UTC"),
            isManual        = receipt.get("isManual", False),
        )

        pdf_bytes = None
        if _WEASYPRINT_AVAILABLE:
            try:
                pdf_bytes = _WeasyHTML(string=html_content).write_pdf()
            except Exception as wp_exc:
                logger.warning("WeasyPrint write_pdf() failed: %s", wp_exc)

        pdf_url, pdf_public_id = "", ""
        if pdf_bytes is not None:
            upload_result = CloudinaryService.upload_receipt_pdf(
                pdf_bytes      = pdf_bytes,
                landlord_id    = receipt["landlordId"],
                tenant_id      = receipt["tenantId"],
                receipt_number = receipt["receiptNumber"],
            )
            pdf_url       = upload_result["secure_url"]
            pdf_public_id = upload_result["public_id"]

        # ── Persist final state ───────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        updates = {
            **{k: receipt[k] for k in allowed_edits if k in receipt},
            "pdfUrl":      pdf_url,
            "pdfPublicId": pdf_public_id,
            "generatedAt": generated_at,
            "status":      "disbursed",
            "updatedAt":   now,
        }
        db.collection(RECEIPTS_COLLECTION).document(receipt_id).update(updates)
        receipt.update(updates)

        logger.info(
            "Receipt disbursed: id=%s number=%s",
            receipt_id, receipt.get("receiptNumber"),
        )
        return receipt

    # ── Manual / hand-payment receipt ─────────────────────────────────────────

    @classmethod
    def generate_manual_receipt(
        cls,
        landlord_id:      str,
        tenant_id:        str,
        amount_paid:      float,
        payment_date:     str,
        payment_method:   str,
        reference_number: str = None,
        notes:            str = None,
    ) -> dict:
        """Generate a receipt for a cash / in-person payment (no proof image).

        Flow:
            1. Validate tenant + landlord ownership.
            2. Create an *approved* payment record (isManual=True, no proofImageUrl).
            3. Delegate to generate_receipt() for numbering, HTML rendering,
               optional PDF upload, and Firestore persistence.

        Returns:
            Receipt document dict (same shape as generate_receipt).
        """
        from datetime import datetime, timezone

        tenant = TenantService.get_by_id(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant not found: {tenant_id}")
        if tenant.get("landlordId") != landlord_id:
            raise ValueError("Tenant does not belong to this landlord.")

        # Create an approved payment record for the hand/cash payment.
        db  = cls._db()
        now = datetime.now(timezone.utc)
        pref = db.collection("payments").document()
        payment_doc = {
            "tenantId":      tenant_id,
            "userId":        tenant["userId"],   # Firebase Auth UID of tenant
            "landlordId":    landlord_id,
            "propertyId":    tenant["propertyId"],
            "amountClaimed": float(amount_paid),
            "paymentDate":   payment_date,
            "paymentMethod": payment_method,
            "proofImageUrl": "",
            "proofPublicId": "",
            "status":        "approved",
            "isManual":      True,
            "submittedAt":   now,
            "reviewedAt":    now,
            "createdAt":     now,
            "updatedAt":     now,
        }
        if reference_number:
            payment_doc["referenceNumber"] = reference_number.strip()
        if notes:
            payment_doc["notes"] = notes.strip()

        pref.set(payment_doc)
        payment_id = pref.id
        logger.info(
            "Manual payment record created: id=%s tenant_id=%s amount=%s",
            payment_id, tenant_id, amount_paid,
        )

        # Reuse the full receipt pipeline — reads the payment doc we just wrote.
        receipt = cls.generate_receipt(payment_id)

        # Tag the receipt doc as manual so the template renders the right badge.
        db.collection(RECEIPTS_COLLECTION).document(receipt["id"]).update(
            {"isManual": True}
        )
        receipt["isManual"] = True
        return receipt
