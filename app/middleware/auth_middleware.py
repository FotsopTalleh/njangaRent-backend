# ---------------------------------------------------------------------------
# middleware/auth_middleware.py — JWT auth decorators (NjangaRent extended)
# ---------------------------------------------------------------------------
import logging
from functools import wraps

from flask import g, request

from app.services.auth_service import AuthService
from app.utils.constants import AUTH_FORBIDDEN, AUTH_TOKEN_EXPIRED, AUTH_TOKEN_INVALID, ACCOUNT_NOT_ACTIVE
from app.utils.response import error_response

logger = logging.getLogger(__name__)
_auth_service = AuthService()


def require_auth(f):
    """Decorator: verify JWT access token from Authorization: Bearer <token> header.

    On success, attaches decoded payload dict to ``g.user``::

        {
          "sub":   "<user_id>",
          "role":  "landlord" | "student" | "tenant" | "admin",
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


def require_active(f):
    """Decorator: require_auth + check that user account status is ACTIVE.

    Fetches user from Firestore to get live status (not from JWT, since
    JWT does not embed status to avoid stale token issues).
    """

    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        from app.services.user_service import UserService
        user_id = g.user.get("sub")
        user = UserService.get_by_id(user_id)
        if not user:
            return error_response(AUTH_TOKEN_INVALID, "User account not found.", status_code=401)
        if user.get("status") != "ACTIVE":
            return error_response(
                ACCOUNT_NOT_ACTIVE,
                "Your account is not yet active. Please wait for admin verification.",
                status_code=403,
            )
        g.db_user = user
        return f(*args, **kwargs)

    return decorated


def require_role(*roles: str):
    """Decorator factory: apply @require_auth then enforce one of the given roles.

    Usage::

        @bp.route("/listings", methods=["POST"])
        @require_role("landlord")
        def create_listing():
            ...

        @bp.route("/appointments", methods=["POST"])
        @require_role("student", "tenant")
        def create_appointment():
            ...
    """

    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated(*args, **kwargs):
            user_role = getattr(g, "user", {}).get("role")
            # "tenant" is treated as alias for "student" in NjangaRent
            effective_role = "student" if user_role == "tenant" else user_role
            allowed = list(roles) + (["student"] if "tenant" in roles else [])
            if effective_role not in roles and user_role not in allowed:
                return error_response(
                    AUTH_FORBIDDEN,
                    f"Access denied. Required role(s): {', '.join(roles)}.",
                    status_code=403,
                )
            return f(*args, **kwargs)

        return decorated

    return decorator


def require_role_active(*roles: str):
    """Combination: require_role + require_active in one decorator.

    Use this for endpoints that need BOTH a specific role AND active account.
    """

    def decorator(f):
        @wraps(f)
        @require_role(*roles)
        def decorated(*args, **kwargs):
            from app.services.user_service import UserService
            user_id = g.user.get("sub")
            user = UserService.get_by_id(user_id)
            if not user:
                return error_response(AUTH_TOKEN_INVALID, "User account not found.", status_code=401)
            if user.get("status") != "ACTIVE":
                return error_response(
                    ACCOUNT_NOT_ACTIVE,
                    "Your account is not yet active.",
                    status_code=403,
                )
            g.db_user = user
            return f(*args, **kwargs)

        return decorated

    return decorator
