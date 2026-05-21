
# ---------------------------------------------------------------------------
# middleware/rate_limit_middleware.py — Rate limit key functions & helpers
# ---------------------------------------------------------------------------
"""
Rate limit configuration is applied directly on blueprint routes using the
Flask-Limiter `limiter` instance from app.extensions.  This module provides
reusable key functions and shared limit strings for consistency.
"""
from flask import g, request


def key_by_ip() -> str:
    """Limit key: remote IP address (default Flask-Limiter behaviour)."""
    return request.remote_addr or "unknown"


def key_by_jwt_sub() -> str:
    """Limit key: authenticated user's JWT `sub` claim.

    Falls back to IP if the request is unauthenticated (e.g. pre-auth routes).
    """
    user = getattr(g, "user", None)
    if user and user.get("sub"):
        return f"user:{user['sub']}"
    return request.remote_addr or "unknown"


# ── Pre-defined limit strings ────────────────────────────────────────────────
LIMIT_DEFAULT         = "200 per minute"
LIMIT_AUTH_ENDPOINTS  = "10 per minute"
LIMIT_UPLOAD_ENDPOINT = "20 per hour"
LIMIT_WEBHOOK         = "60 per minute"
