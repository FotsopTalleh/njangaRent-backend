# ---------------------------------------------------------------------------
# validators.py — File upload validation (MIME type + magic bytes + size)
# ---------------------------------------------------------------------------
import logging
import os

logger = logging.getLogger(__name__)

# python-magic requires the native libmagic library.
# On Windows this is not automatically available; install python-magic-bin
# (pip install python-magic-bin) or run in Docker to get full MIME checking.
try:
    import magic as _magic_lib
    _MAGIC_AVAILABLE = True
except (ImportError, OSError):
    _magic_lib = None
    _MAGIC_AVAILABLE = False
    logger.warning(
        "python-magic / libmagic not available on this platform. "
        "Magic-byte MIME verification is DISABLED — only declared Content-Type "
        "will be checked. Install python-magic-bin for full validation on Windows."
    )

from app.utils.constants import (
    ALLOWED_MIMES,
    MAX_UPLOAD_SIZE_BYTES,
    PAYMENT_UPLOAD_INVALID,
    PAYMENT_UPLOAD_TOO_LARGE,
)


class ValidationError(Exception):
    """Raised when file validation fails."""

    def __init__(self, code: str, message: str, field: str = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


def validate_upload_file(file) -> None:
    """Validate a werkzeug FileStorage object for safe upload.

    Checks (in order):
        1. File is present and has a non-empty filename.
        2. File size does not exceed MAX_UPLOAD_SIZE_BYTES (10 MB).
        3. Declared Content-Type is within ALLOWED_MIMES.
        4. Magic-byte check confirms the actual file type matches the declared type.

    Raises:
        ValidationError — with an appropriate error code on any failure.
    """
    # ── 1. Presence check ────────────────────────────────────────────────────
    if file is None or not getattr(file, "filename", None):
        raise ValidationError(
            code=PAYMENT_UPLOAD_INVALID,
            message="No file provided or filename is empty.",
            field="proofFile",
        )

    # ── 2. Size check ────────────────────────────────────────────────────────
    # Read the whole stream to a buffer so we can inspect it.
    # werkzeug resets the stream position after reading up to content_length,
    # but content_length may not always be set, so we read directly.
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # reset for later upload

    if file_size > MAX_UPLOAD_SIZE_BYTES:
        raise ValidationError(
            code=PAYMENT_UPLOAD_TOO_LARGE,
            message=f"File size exceeds the maximum allowed size of {MAX_UPLOAD_SIZE_BYTES // (1024*1024)} MB.",
            field="proofFile",
        )

    # ── 3. Declared MIME check ────────────────────────────────────────────────
    declared_mime = (file.content_type or "").split(";")[0].strip().lower()
    if declared_mime not in ALLOWED_MIMES:
        raise ValidationError(
            code=PAYMENT_UPLOAD_INVALID,
            message=(
                f"File type '{declared_mime}' is not allowed. "
                f"Accepted types: {', '.join(ALLOWED_MIMES)}."
            ),
            field="proofFile",
        )

    # ── 4. Magic-byte check (MIME spoofing guard) ────────────────────────────
    # Skipped when libmagic is not installed (e.g. Windows without python-magic-bin).
    if _MAGIC_AVAILABLE:
        header = file.read(2048)
        file.seek(0)  # reset for later upload

        detected_mime = _magic_lib.from_buffer(header, mime=True)

        # Normalise: python-magic may return "image/x-png" → "image/png"
        detected_mime = _normalise_mime(detected_mime)

        if detected_mime != declared_mime:
            raise ValidationError(
                code=PAYMENT_UPLOAD_INVALID,
                message=(
                    f"File content does not match declared type. "
                    f"Declared: '{declared_mime}', detected: '{detected_mime}'."
                ),
                field="proofFile",
            )

        if detected_mime not in ALLOWED_MIMES:
            raise ValidationError(
                code=PAYMENT_UPLOAD_INVALID,
                message=f"Detected file type '{detected_mime}' is not permitted.",
                field="proofFile",
            )


# ── Helpers ──────────────────────────────────────────────────────────────────

_MIME_NORMALISE_MAP = {
    "image/x-png": "image/png",
    "image/jpg":   "image/jpeg",
}


def _normalise_mime(mime: str) -> str:
    return _MIME_NORMALISE_MAP.get(mime, mime)
