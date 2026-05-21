# ---------------------------------------------------------------------------
# extensions.py — Initialise Flask extensions (limiter, Firestore, Cloudinary, Firebase Admin)
# ---------------------------------------------------------------------------
import os
import logging

import cloudinary
import firebase_admin
from firebase_admin import credentials, firestore, messaging  # noqa: F401
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

logger = logging.getLogger(__name__)

# ── Flask-Limiter ─────────────────────────────────────────────────────────────
# storage_uri is read lazily via lambda so it always picks up REDIS_URL *after*
# load_dotenv() has run in app/__init__.py — even if extensions.py is imported first.
# swallow_errors=True means a Redis outage degrades gracefully (no rate limiting)
# rather than crashing every request.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    swallow_errors=True,
)

# ── Firestore client (module-level singleton) ─────────────────────────────────
_firebase_app = None
_db = None


def get_db():
    """Return the Firestore client, initialising Firebase Admin on first call."""
    global _firebase_app, _db

    if _db is not None:
        return _db

    if not firebase_admin._apps:
        sa_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "./firebase-service-account.json")
        try:
            cred = credentials.Certificate(sa_path)
            _firebase_app = firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK initialised from service account: %s", sa_path)
        except Exception as exc:
            logger.exception("Failed to initialise Firebase Admin SDK: %s", exc)
            raise

    _db = firestore.client()
    return _db


def init_cloudinary(app):
    """Configure the Cloudinary SDK from Flask app config."""
    cloudinary.config(
        cloud_name=app.config["CLOUDINARY_CLOUD_NAME"],
        api_key=app.config["CLOUDINARY_API_KEY"],
        api_secret=app.config["CLOUDINARY_API_SECRET"],
        secure=True,
    )
    logger.info("Cloudinary configured for cloud: %s", app.config["CLOUDINARY_CLOUD_NAME"])
