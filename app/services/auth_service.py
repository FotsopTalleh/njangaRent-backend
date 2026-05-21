# ---------------------------------------------------------------------------
# services/auth_service.py — JWT creation/verification + token rotation
# ---------------------------------------------------------------------------
import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import redis

logger = logging.getLogger(__name__)


class AuthService:
    """Handles JWT lifecycle: creation, verification, rotation, and blacklisting."""

    # ── Custom exceptions ────────────────────────────────────────────────────
    class TokenExpiredError(Exception):
        pass

    class TokenInvalidError(Exception):
        pass

    def __init__(self):
        self._access_secret: str  = os.environ.get("ACCESS_TOKEN_SECRET", "access_secret")
        self._refresh_secret: str = os.environ.get("REFRESH_TOKEN_SECRET", "refresh_secret")
        self._access_expiry_min: int  = int(os.environ.get("ACCESS_TOKEN_EXPIRY_MINUTES", 15))
        self._refresh_expiry_days: int = int(os.environ.get("REFRESH_TOKEN_EXPIRY_DAYS", 7))

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._redis: redis.Redis = redis.Redis.from_url(redis_url, decode_responses=True)

    # ── Access token ─────────────────────────────────────────────────────────

    def create_access_token(self, user_id: str, role: str, email: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub":   user_id,
            "role":  role,
            "email": email,
            "jti":   str(uuid.uuid4()),
            "iat":   now,
            "exp":   now + timedelta(minutes=self._access_expiry_min),
        }
        return jwt.encode(payload, self._access_secret, algorithm="HS256")

    def verify_access_token(self, token: str) -> dict:
        try:
            return jwt.decode(token, self._access_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise self.TokenExpiredError("Access token has expired.")
        except jwt.InvalidTokenError as exc:
            raise self.TokenInvalidError(str(exc))

    # ── Refresh token ─────────────────────────────────────────────────────────

    def create_refresh_token(self, user_id: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(days=self._refresh_expiry_days),
        }
        return jwt.encode(payload, self._refresh_secret, algorithm="HS256")

    def verify_refresh_token(self, token: str) -> dict:
        """Decode + validate a refresh token.

        Raises:
            TokenExpiredError — if the token is past its exp.
            TokenInvalidError — if the token is malformed or blacklisted.
        """
        try:
            payload = jwt.decode(token, self._refresh_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise self.TokenExpiredError("Refresh token has expired.")
        except jwt.InvalidTokenError as exc:
            raise self.TokenInvalidError(str(exc))

        # Check Redis blacklist
        jti = payload.get("jti")
        if jti and self._is_blacklisted(jti):
            raise self.TokenInvalidError("Refresh token has been invalidated.")

        return payload

    # ── Token rotation ────────────────────────────────────────────────────────

    def rotate_refresh_token(self, old_token: str) -> tuple[str, dict]:
        """Verify old token, blacklist it, issue a new refresh token.

        Returns:
            Tuple of (new_refresh_token, old_payload)
        """
        payload = self.verify_refresh_token(old_token)
        self._blacklist_token(payload)
        user_id = payload["sub"]
        new_token = self.create_refresh_token(user_id)
        return new_token, payload

    # ── Blacklist helpers ────────────────────────────────────────────────────

    def _blacklist_token(self, payload: dict) -> None:
        """Add a token's JTI to the Redis blacklist with TTL = remaining lifetime."""
        jti = payload.get("jti")
        if not jti:
            return
        exp = payload.get("exp", 0)
        now_ts = datetime.now(timezone.utc).timestamp()
        ttl = max(1, int(exp - now_ts))
        try:
            self._redis.setex(f"blacklist:{jti}", ttl, "1")
        except redis.RedisError as exc:
            logger.error("Redis blacklist write failed for jti=%s: %s", jti, exc)

    def _is_blacklisted(self, jti: str) -> bool:
        try:
            return self._redis.exists(f"blacklist:{jti}") == 1
        except redis.RedisError as exc:
            logger.error("Redis blacklist read failed for jti=%s: %s", jti, exc)
            return False

    def blacklist_from_token_string(self, token: str) -> None:
        """Blacklist a refresh token given its raw string (used on logout)."""
        try:
            payload = jwt.decode(
                token, self._refresh_secret, algorithms=["HS256"],
                options={"verify_exp": False},  # allow blacklisting expired tokens
            )
            self._blacklist_token(payload)
        except jwt.InvalidTokenError as exc:
            logger.warning("Could not decode refresh token for blacklisting: %s", exc)

    # ── Invite token (short-lived JWT for tenant invite) ──────────────────────

    def create_invite_token(
        self,
        email: str,
        property_id: str,
        landlord_id: str,
        monthly_rent: float,
        rent_due_day: int,
        expiry_hours: int = 72,
    ) -> tuple[str, str]:
        """Create a signed invite token.

        Returns:
            Tuple of (raw_token_string, sha256_hex_hash)
        """
        import hashlib
        now = datetime.now(timezone.utc)
        payload = {
            "email":        email,
            "propertyId":   property_id,
            "landlordId":   landlord_id,
            "monthlyRent":  monthly_rent,
            "rentDueDay":   rent_due_day,
            "jti":          str(uuid.uuid4()),
            "iat":          now,
            "exp":          now + timedelta(hours=expiry_hours),
        }
        token = jwt.encode(payload, self._access_secret, algorithm="HS256")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return token, token_hash

    def verify_invite_token(self, token: str) -> dict:
        try:
            return jwt.decode(token, self._access_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise self.TokenExpiredError("Invite token has expired.")
        except jwt.InvalidTokenError as exc:
            raise self.TokenInvalidError(str(exc))

    # ── Password reset token ───────────────────────────────────────────────

    def create_reset_token(self, user_id: str, expiry_minutes: int = 15) -> tuple[str, str]:
        """Create a short-lived password reset token.

        Returns:
            Tuple of (raw_token_string, sha256_hex_hash)
        """
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=expiry_minutes),
        }
        token = jwt.encode(payload, self._access_secret, algorithm="HS256")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return token, token_hash

    def verify_reset_token(self, token: str) -> dict:
        try:
            return jwt.decode(token, self._access_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise self.TokenExpiredError("Reset token has expired.")
        except jwt.InvalidTokenError as exc:
            raise self.TokenInvalidError(str(exc))

    # ── Cookie helpers ─────────────────────────────────────────────────────

    @property
    def refresh_expiry_seconds(self) -> int:
        return self._refresh_expiry_days * 86400

    @staticmethod
    def get_cookie_kwargs(secure: bool = True, same_site: str = "Strict") -> dict:
        return {
            "httponly":  True,
            "secure":    secure,
            "samesite":  same_site,
            "path":      "/",
        }
