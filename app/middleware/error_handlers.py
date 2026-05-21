# ---------------------------------------------------------------------------
# middleware/error_handlers.py — Global Flask error handlers
# ---------------------------------------------------------------------------
import logging
import traceback

from flask import Flask, jsonify
from marshmallow import ValidationError as MarshmallowValidationError
from werkzeug.exceptions import MethodNotAllowed, NotFound

from app.utils.constants import (
    METHOD_NOT_ALLOWED,
    NOT_FOUND,
    RATE_LIMIT_EXCEEDED,
    SERVER_ERROR,
    VALIDATION_ERROR,
)

logger = logging.getLogger(__name__)


def _err(code: str, message: str, field: str = None, status: int = 400):
    payload = {
        "success": False,
        "error": {"code": code, "message": message, "field": field},
    }
    return jsonify(payload), status


def register_error_handlers(app: Flask) -> None:
    """Attach all global error handlers to the Flask application."""

    # ── 404 Not Found ──────────────────────────────────────────────────────
    @app.errorhandler(404)
    @app.errorhandler(NotFound)
    def handle_404(err):
        return _err(NOT_FOUND, "Resource not found.", status=404)

    # ── 405 Method Not Allowed ─────────────────────────────────────────────
    @app.errorhandler(405)
    @app.errorhandler(MethodNotAllowed)
    def handle_405(err):
        return _err(METHOD_NOT_ALLOWED, "HTTP method not allowed.", status=405)

    # ── 422 Unprocessable Entity (Marshmallow) ─────────────────────────────
    @app.errorhandler(MarshmallowValidationError)
    def handle_marshmallow_validation(err):
        # Grab first offending field name for the 'field' property.
        first_field = next(iter(err.messages), None)
        first_msg = (
            err.messages[first_field][0]
            if isinstance(err.messages.get(first_field), list)
            else str(err.messages.get(first_field, "Validation failed."))
        )
        return _err(
            VALIDATION_ERROR,
            first_msg,
            field=first_field,
            status=422,
        )

    # ── 429 Rate Limit Exceeded (Flask-Limiter) ────────────────────────────
    @app.errorhandler(429)
    def handle_rate_limit(err):
        return _err(RATE_LIMIT_EXCEEDED, "Too many requests. Please try again later.", status=429)

    # ── 500 Internal Server Error ──────────────────────────────────────────
    @app.errorhandler(500)
    def handle_500(err):
        logger.error("Unhandled 500 error:\n%s", traceback.format_exc())
        return _err(SERVER_ERROR, "An unexpected error occurred.", status=500)

    # ── Catch-all for unhandled exceptions ────────────────────────────────
    @app.errorhandler(Exception)
    def handle_exception(err):
        # Let HTTP exceptions (Werkzeug) propagate normally.
        from werkzeug.exceptions import HTTPException
        if isinstance(err, HTTPException):
            return err
        logger.exception("Unhandled exception: %s", err)
        return _err(SERVER_ERROR, "An unexpected error occurred.", status=500)
