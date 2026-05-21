# ---------------------------------------------------------------------------
# config.py — Flask configuration classes
# ---------------------------------------------------------------------------
import os
from datetime import timedelta


class BaseConfig:
    """Base configuration shared by all environments."""

    # ── Flask core ───────────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "CHANGE_ME_IN_ENV")
    JSON_SORT_KEYS: bool = False

    # ── JWT ──────────────────────────────────────────────────────────────────
    ACCESS_TOKEN_SECRET: str = os.environ.get("ACCESS_TOKEN_SECRET", "access_secret_change_me")
    REFRESH_TOKEN_SECRET: str = os.environ.get("REFRESH_TOKEN_SECRET", "refresh_secret_change_me")
    ACCESS_TOKEN_EXPIRY_MINUTES: int = int(os.environ.get("ACCESS_TOKEN_EXPIRY_MINUTES", 15))
    REFRESH_TOKEN_EXPIRY_DAYS: int = int(os.environ.get("REFRESH_TOKEN_EXPIRY_DAYS", 7))

    # ── Firebase / Firestore ─────────────────────────────────────────────────
    FIREBASE_SERVICE_ACCOUNT_PATH: str = os.environ.get(
        "FIREBASE_SERVICE_ACCOUNT_PATH", "./firebase-service-account.json"
    )
    FCM_PROJECT_ID: str = os.environ.get("FCM_PROJECT_ID", "")

    # ── Cloudinary ───────────────────────────────────────────────────────────
    CLOUDINARY_CLOUD_NAME: str = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str    = os.environ.get("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.environ.get("CLOUDINARY_API_SECRET", "")

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # ── n8n ──────────────────────────────────────────────────────────────────
    N8N_WEBHOOK_SECRET: str    = os.environ.get("N8N_WEBHOOK_SECRET", "n8n_secret_change_me")
    N8N_OCR_TRIGGER_URL: str   = os.environ.get(
        "N8N_OCR_TRIGGER_URL", "http://n8n:5678/webhook/ocr-trigger"
    )

    # ── Email ────────────────────────────────────────────────────────────────
    EMAIL_PROVIDER: str     = os.environ.get("EMAIL_PROVIDER", "sendgrid")
    SENDGRID_API_KEY: str   = os.environ.get("SENDGRID_API_KEY", "")
    MAIL_FROM_ADDRESS: str  = os.environ.get("MAIL_FROM_ADDRESS", "noreply@mytenant.app")
    MAIL_FROM_NAME: str     = os.environ.get("MAIL_FROM_NAME", "MyTenant")
    # SMTP fallback settings (used when EMAIL_PROVIDER=smtp)
    MAIL_SERVER: str        = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT: int          = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS: bool      = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME: str      = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD: str      = os.environ.get("MAIL_PASSWORD", "")

    # ── Frontend ─────────────────────────────────────────────────────────────
    FRONTEND_URL: str = os.environ.get("FRONTEND_URL", "http://localhost:3000")

    # ── Upload limits ────────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = int(os.environ.get("MAX_UPLOAD_SIZE_MB", 10))

    # ── Receipt ──────────────────────────────────────────────────────────────
    RECEIPT_NUMBER_PREFIX: str = os.environ.get("RECEIPT_NUMBER_PREFIX", "RCT")


class DevelopmentConfig(BaseConfig):
    """Development-specific configuration."""

    DEBUG: bool = True
    TESTING: bool = False

    # Relaxed cookie settings for local development (no HTTPS)
    SESSION_COOKIE_SECURE: bool    = False
    SESSION_COOKIE_SAMESITE: str   = "None"
    REFRESH_COOKIE_SECURE: bool    = False
    REFRESH_COOKIE_SAMESITE: str   = "None"


class ProductionConfig(BaseConfig):
    """Production-specific configuration.

    Tighten cookie security and disable debug mode.
    """

    DEBUG: bool   = False
    TESTING: bool = False

    SESSION_COOKIE_SECURE: bool   = True
    SESSION_COOKIE_SAMESITE: str  = "Strict"
    REFRESH_COOKIE_SECURE: bool   = True
    REFRESH_COOKIE_SAMESITE: str  = "Strict"


# ── Config map ───────────────────────────────────────────────────────────────
config_map = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development").lower()
    return config_map.get(env, DevelopmentConfig)
