# ---------------------------------------------------------------------------
# middleware/auth_middleware.py — JWT auth decorators
# ---------------------------------------------------------------------------
import logging
from functools import wraps

from flask import g, request

from app.services.auth_service import AuthService
from app.utils.constants import AUTH_FORBIDDEN, AUTH_TOKEN_EXPIRED, AUTH_TOKEN_INVALID
from app.utils.response import error_response

logger = logging.getLogger(__name__)
_auth_service = AuthService()


def require_auth(f):
    """Decorator: verify JWT access token from Authorization: Bearer <token> header.

    On success, attaches decoded payload dict to ``g.user``::

        {
          "sub":   "<user_id>",
          "role":  "landlord" | "tenant",
          "email": "<email>",
          "jti":   "<uuid4>",
          "iat":   <int>,
          "exp":   <int>,
        }

    On failure, returns a standardised 401 JSON error.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return error_response(
                AUTH_TOKEN_INVALID,
                "Authorization header missing or malformed. Expected: Bearer <token>.",
                status_code=401,
            )

        token = auth_header[len("Bearer ") :]

        try:
            payload = _auth_service.verify_access_token(token)
        except AuthService.TokenExpiredError:
            return error_response(AUTH_TOKEN_EXPIRED, "Access token has expired.", status_code=401)
        except AuthService.TokenInvalidError as exc:
            return error_response(AUTH_TOKEN_INVALID, str(exc), status_code=401)

        g.user = payload
        return f(*args, **kwargs)

    return decorated


def require_role(*roles: str):
    """Decorator factory: apply @require_auth then enforce one of the given roles.

    Usage::

        @bp.route("/properties", methods=["GET"])
        @require_role("landlord")
        def list_properties():
            ...

        @bp.route("/payments", methods=["POST"])
        @require_role("tenant")
        def submit_payment():
            ...
    """

    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated(*args, **kwargs):
            user_role = getattr(g, "user", {}).get("role")
            if user_role not in roles:
                return error_response(
                    AUTH_FORBIDDEN,
                    f"Access denied. Required role(s): {', '.join(roles)}.",
                    status_code=403,
                )
            return f(*args, **kwargs)

        return decorated

    return decorator
