# ---------------------------------------------------------------------------
# blueprints/properties/routes.py — /properties/* endpoints
# ---------------------------------------------------------------------------
import logging

from flask import Blueprint, g, request
from marshmallow import ValidationError as MarshmallowValidationError

from app.blueprints.properties.schemas import CreatePropertySchema, UpdatePropertySchema
from app.middleware.auth_middleware import require_role
from app.services.property_service import PropertyService
from app.utils.constants import (
    AUTH_FORBIDDEN,
    CONFLICT,
    PROPERTY_NOT_FOUND,
    VALIDATION_ERROR,
)
from app.utils.pagination import paginate_query, parse_pagination_args
from app.utils.response import error_response, paginated_response, success_response

logger = logging.getLogger(__name__)
properties_bp = Blueprint("properties", __name__, url_prefix="/properties")


def _validate(schema_cls, data: dict):
    try:
        return schema_cls().load(data)
    except MarshmallowValidationError as exc:
        field = next(iter(exc.messages), None)
        msg   = exc.messages[field][0] if isinstance(exc.messages.get(field), list) else str(exc.messages)
        raise _Fail(field, msg)


class _Fail(Exception):
    def __init__(self, field, message):
        self.field, self.message = field, message


def _own_property(property_id: str) -> dict:
    """Fetch property and assert ownership. Returns property dict."""
    prop = PropertyService.get_by_id(property_id)
    if not prop:
        return None
    if prop["landlordId"] != g.user["sub"]:
        return False   # forbidden
    return prop


# ── Endpoints ─────────────────────────────────────────────────────────────────


@properties_bp.route("", methods=["GET"])
@require_role("landlord")
def list_properties():
    page, limit = parse_pagination_args(request.args)
    query = PropertyService.list_for_landlord(g.user["sub"])
    docs, total = paginate_query(query, page, limit)
    return paginated_response(docs, page, limit, total)


@properties_bp.route("", methods=["POST"])
@require_role("landlord")
def create_property():
    try:
        data = _validate(CreatePropertySchema, request.get_json(silent=True) or {})
    except _Fail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    prop = PropertyService.create(g.user["sub"], data)
    return success_response(data=prop, status_code=201)


@properties_bp.route("/<property_id>", methods=["GET"])
@require_role("landlord")
def get_property(property_id: str):
    result = _own_property(property_id)
    if result is None:
        return error_response(PROPERTY_NOT_FOUND, "Property not found.", status_code=404)
    if result is False:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    tenants = PropertyService.get_active_tenants(property_id)
    result["tenants"] = tenants
    return success_response(data=result)


@properties_bp.route("/<property_id>", methods=["PUT"])
@require_role("landlord")
def update_property(property_id: str):
    result = _own_property(property_id)
    if result is None:
        return error_response(PROPERTY_NOT_FOUND, "Property not found.", status_code=404)
    if result is False:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    try:
        data = _validate(UpdatePropertySchema, request.get_json(silent=True) or {})
    except _Fail as e:
        return error_response(VALIDATION_ERROR, e.message, field=e.field, status_code=422)

    if not data:
        return error_response(VALIDATION_ERROR, "No valid fields provided for update.", status_code=422)

    PropertyService.update(property_id, data)
    updated = PropertyService.get_by_id(property_id)
    return success_response(data=updated)


@properties_bp.route("/<property_id>", methods=["DELETE"])
@require_role("landlord")
def delete_property(property_id: str):
    result = _own_property(property_id)
    if result is None:
        return error_response(PROPERTY_NOT_FOUND, "Property not found.", status_code=404)
    if result is False:
        return error_response(AUTH_FORBIDDEN, "Access denied.", status_code=403)

    if PropertyService.has_active_tenants(property_id):
        return error_response(
            CONFLICT,
            "Cannot delete a property with active tenants. Remove all tenants first.",
            status_code=409,
        )

    PropertyService.delete(property_id)
    return success_response(data=None, message="Property deleted successfully.")
