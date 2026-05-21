# ---------------------------------------------------------------------------
# constants.py — All application-wide constants
# ---------------------------------------------------------------------------

# ── Auth error codes ────────────────────────────────────────────────────────
AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
AUTH_TOKEN_EXPIRED       = "AUTH_TOKEN_EXPIRED"
AUTH_TOKEN_INVALID       = "AUTH_TOKEN_INVALID"
AUTH_FORBIDDEN           = "AUTH_FORBIDDEN"
AUTH_EMAIL_EXISTS        = "AUTH_EMAIL_EXISTS"
AUTH_INVITE_INVALID      = "AUTH_INVITE_INVALID"
AUTH_INVITE_EXPIRED      = "AUTH_INVITE_EXPIRED"
AUTH_INVITE_USED         = "AUTH_INVITE_USED"

# ── Resource error codes ─────────────────────────────────────────────────────
USER_NOT_FOUND           = "USER_NOT_FOUND"
PROPERTY_NOT_FOUND       = "PROPERTY_NOT_FOUND"
TENANT_NOT_FOUND         = "TENANT_NOT_FOUND"
PAYMENT_NOT_FOUND        = "PAYMENT_NOT_FOUND"
RECEIPT_NOT_FOUND        = "RECEIPT_NOT_FOUND"
NOTIFICATION_NOT_FOUND   = "NOTIFICATION_NOT_FOUND"

# ── Payment error codes ──────────────────────────────────────────────────────
PAYMENT_ALREADY_REVIEWED = "PAYMENT_ALREADY_REVIEWED"
PAYMENT_UPLOAD_INVALID   = "PAYMENT_UPLOAD_INVALID"
PAYMENT_UPLOAD_TOO_LARGE = "PAYMENT_UPLOAD_TOO_LARGE"

# ── General error codes ──────────────────────────────────────────────────────
VALIDATION_ERROR         = "VALIDATION_ERROR"
RATE_LIMIT_EXCEEDED      = "RATE_LIMIT_EXCEEDED"
SERVER_ERROR             = "SERVER_ERROR"
NOT_FOUND                = "NOT_FOUND"
METHOD_NOT_ALLOWED       = "METHOD_NOT_ALLOWED"
CONFLICT                 = "CONFLICT"

# ── User roles ───────────────────────────────────────────────────────────────
ROLE_LANDLORD = "landlord"
ROLE_TENANT   = "tenant"

# ── Property types ───────────────────────────────────────────────────────────
PROPERTY_TYPE_APARTMENT  = "apartment"
PROPERTY_TYPE_HOUSE      = "house"
PROPERTY_TYPE_COMMERCIAL = "commercial"
PROPERTY_TYPE_OTHER      = "other"
PROPERTY_TYPES = [
    PROPERTY_TYPE_APARTMENT,
    PROPERTY_TYPE_HOUSE,
    PROPERTY_TYPE_COMMERCIAL,
    PROPERTY_TYPE_OTHER,
]

# ── Payment methods ───────────────────────────────────────────────────────────
PAYMENT_METHOD_MOBILE_MONEY  = "mobile_money"
PAYMENT_METHOD_BANK_TRANSFER = "bank_transfer"
PAYMENT_METHOD_CASH          = "cash"
PAYMENT_METHOD_OTHER         = "other"
PAYMENT_METHODS = [
    PAYMENT_METHOD_MOBILE_MONEY,
    PAYMENT_METHOD_BANK_TRANSFER,
    PAYMENT_METHOD_CASH,
    PAYMENT_METHOD_OTHER,
]

# ── Payment statuses ─────────────────────────────────────────────────────────
PAYMENT_STATUS_PENDING  = "pending"
PAYMENT_STATUS_APPROVED = "approved"
PAYMENT_STATUS_REJECTED = "rejected"
PAYMENT_STATUSES = [
    PAYMENT_STATUS_PENDING,
    PAYMENT_STATUS_APPROVED,
    PAYMENT_STATUS_REJECTED,
]

# ── Tenant statuses ──────────────────────────────────────────────────────────
TENANT_STATUS_ACTIVE  = "active"
TENANT_STATUS_REMOVED = "removed"

# ── Invitation statuses ──────────────────────────────────────────────────────
INVITATION_STATUS_PENDING  = "pending"
INVITATION_STATUS_ACCEPTED = "accepted"
INVITATION_STATUS_EXPIRED  = "expired"

# ── Notification types ────────────────────────────────────────────────────────
NOTIF_PAYMENT_SUBMITTED = "PAYMENT_SUBMITTED"
NOTIF_PAYMENT_APPROVED  = "PAYMENT_APPROVED"
NOTIF_PAYMENT_REJECTED  = "PAYMENT_REJECTED"
NOTIF_RENT_REMINDER     = "RENT_REMINDER"
NOTIFICATION_TYPES = [
    NOTIF_PAYMENT_SUBMITTED,
    NOTIF_PAYMENT_APPROVED,
    NOTIF_PAYMENT_REJECTED,
    NOTIF_RENT_REMINDER,
]

# ── File upload ───────────────────────────────────────────────────────────────
ALLOWED_MIMES = [
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
]
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# ── Receipt ───────────────────────────────────────────────────────────────────
RECEIPT_NUMBER_PREFIX = "RCT"
