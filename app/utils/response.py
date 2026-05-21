# ---------------------------------------------------------------------------
# response.py — Standardised JSON envelope helpers
# ---------------------------------------------------------------------------
from flask import jsonify


def success_response(data=None, message: str = None, status_code: int = 200):
    """Return a standard success envelope.

    Shape:
        { "success": true, "data": {...}, "message": "optional string" }
    """
    payload = {"success": True, "data": data}
    if message:
        payload["message"] = message
    return jsonify(payload), status_code


def paginated_response(data: list, page: int, limit: int, total: int, status_code: int = 200):
    """Return a standard paginated success envelope.

    Shape:
        {
          "success": true,
          "data": [...],
          "pagination": { "page": 1, "limit": 20, "total": 84, "hasNext": true }
        }
    """
    payload = {
        "success": True,
        "data": data,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "hasNext": (page * limit) < total,
        },
    }
    return jsonify(payload), status_code


def error_response(
    code: str,
    message: str,
    field: str = None,
    status_code: int = 400,
):
    """Return a standard error envelope.

    Shape:
        { "success": false, "error": { "code": "...", "message": "...", "field": null } }
    """
    payload = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "field": field,
        },
    }
    return jsonify(payload), status_code
