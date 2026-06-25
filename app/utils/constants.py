# ---------------------------------------------------------------------------
# constants.py — All application-wide constants (extended for NjangaRent)
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

# ── NjangaRent new resource error codes ──────────────────────────────────────
LISTING_NOT_FOUND        = "LISTING_NOT_FOUND"
APPOINTMENT_NOT_FOUND    = "APPOINTMENT_NOT_FOUND"
CONVERSATION_NOT_FOUND   = "CONVERSATION_NOT_FOUND"
MESSAGE_NOT_FOUND        = "MESSAGE_NOT_FOUND"
NKWA_PAYMENT_NOT_FOUND   = "NKWA_PAYMENT_NOT_FOUND"

# ── Payment error codes ──────────────────────────────────────────────────────
PAYMENT_ALREADY_REVIEWED = "PAYMENT_ALREADY_REVIEWED"
PAYMENT_UPLOAD_INVALID   = "PAYMENT_UPLOAD_INVALID"
PAYMENT_UPLOAD_TOO_LARGE = "PAYMENT_UPLOAD_TOO_LARGE"

# ── Listing error codes ───────────────────────────────────────────────────────
LISTING_FORBIDDEN        = "LISTING_FORBIDDEN"
LISTING_IMAGE_REQUIRED   = "LISTING_IMAGE_REQUIRED"
LISTING_IMAGE_TOO_LARGE  = "LISTING_IMAGE_TOO_LARGE"
LISTING_IMAGE_INVALID    = "LISTING_IMAGE_INVALID"

# ── Appointment error codes ───────────────────────────────────────────────────
APPOINTMENT_LIMIT        = "APPOINTMENT_LIMIT"
APPOINTMENT_INVALID_DATE = "APPOINTMENT_INVALID_DATE"
APPOINTMENT_FORBIDDEN    = "APPOINTMENT_FORBIDDEN"

# ── Nkwa payment error codes ──────────────────────────────────────────────────
NKWA_INITIATE_FAILED     = "NKWA_INITIATE_FAILED"
NKWA_WEBHOOK_INVALID     = "NKWA_WEBHOOK_INVALID"

# ── General error codes ──────────────────────────────────────────────────────
VALIDATION_ERROR         = "VALIDATION_ERROR"
RATE_LIMIT_EXCEEDED      = "RATE_LIMIT_EXCEEDED"
SERVER_ERROR             = "SERVER_ERROR"
NOT_FOUND                = "NOT_FOUND"
METHOD_NOT_ALLOWED       = "METHOD_NOT_ALLOWED"
CONFLICT                 = "CONFLICT"
ACCOUNT_NOT_ACTIVE       = "ACCOUNT_NOT_ACTIVE"

# ── User roles ───────────────────────────────────────────────────────────────
ROLE_LANDLORD = "landlord"
ROLE_TENANT   = "tenant"
ROLE_STUDENT  = "student"
ROLE_ADMIN    = "admin"

# ── User statuses ─────────────────────────────────────────────────────────────
STATUS_PENDING  = "PENDING"
STATUS_ACTIVE   = "ACTIVE"
STATUS_REJECTED = "REJECTED"
STATUS_BANNED   = "BANNED"

# ── Property types (original) ────────────────────────────────────────────────
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

# ── NjangaRent listing property types ────────────────────────────────────────
LISTING_TYPE_STUDIO         = "studio"
LISTING_TYPE_SINGLE_ROOM    = "single_room"
LISTING_TYPE_SELF_CONTAINED = "self_contained"
LISTING_TYPE_APARTMENT      = "apartment"
LISTING_TYPE_HOSTEL_BLOCK   = "hostel_block"
LISTING_TYPES = [
    LISTING_TYPE_STUDIO,
    LISTING_TYPE_SINGLE_ROOM,
    LISTING_TYPE_SELF_CONTAINED,
    LISTING_TYPE_APARTMENT,
    LISTING_TYPE_HOSTEL_BLOCK,
]

# ── Listing statuses ──────────────────────────────────────────────────────────
LISTING_STATUS_DRAFT                = "draft"
LISTING_STATUS_PENDING_ADMIN_REVIEW = "pending_admin_review"
LISTING_STATUS_ACTIVE               = "active"
LISTING_STATUS_REJECTED             = "rejected"
LISTING_STATUS_DEACTIVATED          = "deactivated"
LISTING_STATUS_FLAGGED              = "flagged"
LISTING_STATUSES = [
    LISTING_STATUS_DRAFT,
    LISTING_STATUS_PENDING_ADMIN_REVIEW,
    LISTING_STATUS_ACTIVE,
    LISTING_STATUS_REJECTED,
    LISTING_STATUS_DEACTIVATED,
    LISTING_STATUS_FLAGGED,
]

# ── Listing rent periods ──────────────────────────────────────────────────────
RENT_PERIOD_MONTHLY = "monthly"
RENT_PERIOD_TERMLY  = "termly"
RENT_PERIOD_YEARLY  = "yearly"
RENT_PERIODS = [RENT_PERIOD_MONTHLY, RENT_PERIOD_TERMLY, RENT_PERIOD_YEARLY]

# ── Listing amenities ─────────────────────────────────────────────────────────
AMENITIES_LIST = [
    "water", "electricity", "wifi", "security", "furnished",
    "parking", "borehole", "kitchen", "bathroom_en_suite", "generator",
]

# ── Appointment statuses ──────────────────────────────────────────────────────
APPT_STATUS_PENDING     = "pending"
APPT_STATUS_CONFIRMED   = "confirmed"
APPT_STATUS_RESCHEDULED = "rescheduled"
APPT_STATUS_DECLINED    = "declined"
APPT_STATUS_COMPLETED   = "completed"
APPT_STATUS_CANCELLED   = "cancelled"
APPT_STATUS_EXPIRED     = "expired"
APPOINTMENT_STATUSES = [
    APPT_STATUS_PENDING, APPT_STATUS_CONFIRMED, APPT_STATUS_RESCHEDULED,
    APPT_STATUS_DECLINED, APPT_STATUS_COMPLETED, APPT_STATUS_CANCELLED,
    APPT_STATUS_EXPIRED,
]

# ── Appointment slots ─────────────────────────────────────────────────────────
APPT_SLOT_MORNING   = "morning"
APPT_SLOT_AFTERNOON = "afternoon"
APPT_SLOT_EVENING   = "evening"
APPOINTMENT_SLOTS   = [APPT_SLOT_MORNING, APPT_SLOT_AFTERNOON, APPT_SLOT_EVENING]

# ── Nkwa payment statuses ─────────────────────────────────────────────────────
NKWA_STATUS_INITIATED = "initiated"
NKWA_STATUS_CONFIRMED = "confirmed"
NKWA_STATUS_FAILED    = "failed"

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
NOTIF_PAYMENT_SUBMITTED       = "PAYMENT_SUBMITTED"
NOTIF_PAYMENT_APPROVED        = "PAYMENT_APPROVED"
NOTIF_PAYMENT_REJECTED        = "PAYMENT_REJECTED"
NOTIF_RENT_REMINDER           = "RENT_REMINDER"
NOTIF_LISTING_APPROVED        = "LISTING_APPROVED"
NOTIF_LISTING_REJECTED        = "LISTING_REJECTED"
NOTIF_LISTING_FLAGGED         = "LISTING_FLAGGED"
NOTIF_ACCOUNT_APPROVED        = "ACCOUNT_APPROVED"
NOTIF_ACCOUNT_REJECTED        = "ACCOUNT_REJECTED"
NOTIF_APPOINTMENT_CONFIRMED   = "APPOINTMENT_CONFIRMED"
NOTIF_APPOINTMENT_DECLINED    = "APPOINTMENT_DECLINED"
NOTIF_APPOINTMENT_RESCHEDULED = "APPOINTMENT_RESCHEDULED"
NOTIF_NKWA_PAYMENT_CONFIRMED  = "NKWA_PAYMENT_CONFIRMED"
NOTIF_NKWA_PAYMENT_FAILED     = "NKWA_PAYMENT_FAILED"
NOTIFICATION_TYPES = [
    NOTIF_PAYMENT_SUBMITTED, NOTIF_PAYMENT_APPROVED, NOTIF_PAYMENT_REJECTED,
    NOTIF_RENT_REMINDER, NOTIF_LISTING_APPROVED, NOTIF_LISTING_REJECTED,
    NOTIF_LISTING_FLAGGED, NOTIF_ACCOUNT_APPROVED, NOTIF_ACCOUNT_REJECTED,
    NOTIF_APPOINTMENT_CONFIRMED, NOTIF_APPOINTMENT_DECLINED,
    NOTIF_APPOINTMENT_RESCHEDULED, NOTIF_NKWA_PAYMENT_CONFIRMED,
    NOTIF_NKWA_PAYMENT_FAILED,
]

# ── File upload ───────────────────────────────────────────────────────────────
ALLOWED_MIMES = [
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
]
ALLOWED_IMAGE_MIMES = ["image/jpeg", "image/png", "image/webp"]
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_IMAGE_SIZE_BYTES  = 5  * 1024 * 1024   # 5 MB (listing images)

# ── Receipt ───────────────────────────────────────────────────────────────────
RECEIPT_NUMBER_PREFIX = "RCT"

# ── UB Main Gate coordinates (Haversine origin) ───────────────────────────────
UB_MAIN_GATE_LAT = 4.1537
UB_MAIN_GATE_LNG = 9.2443
