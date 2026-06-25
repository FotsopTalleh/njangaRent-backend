#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# scripts/seed_admin.py — Create or verify the NjangaRent admin account
#
# Usage:
#   python scripts/seed_admin.py
#
# Required env vars:
#   ADMIN_EMAIL    — admin account email
#   ADMIN_PASSWORD — admin account password (min 8 chars)
#   (plus all Firebase / Firestore vars)
# ---------------------------------------------------------------------------
import os
import sys
import logging

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ADMIN_EMAIL    = os.environ.get("ADMIN_EMAIL", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

if not ADMIN_EMAIL or not ADMIN_PASSWORD:
    logger.error("ADMIN_EMAIL and ADMIN_PASSWORD must be set in your .env file.")
    sys.exit(1)

if len(ADMIN_PASSWORD) < 8:
    logger.error("ADMIN_PASSWORD must be at least 8 characters.")
    sys.exit(1)

import bcrypt
from app.services.user_service import UserService

existing = UserService.get_by_email(ADMIN_EMAIL)
if existing:
    logger.info("Admin already exists: id=%s email=%s status=%s",
                existing["id"], ADMIN_EMAIL, existing.get("status"))
    # Ensure status is ACTIVE
    if existing.get("status") != "ACTIVE":
        UserService.set_status(existing["id"], "ACTIVE")
        logger.info("Set existing admin status to ACTIVE.")
    sys.exit(0)

pw_hash = bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode()

admin = UserService.create(
    email         = ADMIN_EMAIL,
    full_name     = "NjangaRent Admin",
    role          = "admin",
    password_hash = pw_hash,
    status        = "ACTIVE",
)

logger.info("Admin created: id=%s email=%s", admin["id"], ADMIN_EMAIL)
logger.info("Log in at /login with role admin.")
