# ---------------------------------------------------------------------------
# blueprints/listings/routes.py — Public & landlord listing endpoints
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request

from app.extensions import get_db, limiter
from app.middleware.auth_middleware import require_auth, require_role, require_role_active
from app.services.cloudinary_service import CloudinaryService
from app.utils.constants import (
    AUTH_FORBIDDEN, LISTING_NOT_FOUND, LISTING_TYPES, LISTING_IMAGE_REQUIRED,
    LISTING_STATUS_PENDING_ADMIN_REVIEW, LISTING_STATUS_ACTIVE,
    LISTING_STATUS_DEACTIVATED, LISTING_STATUS_FLAGGED, LISTING_STATUSES,
    RENT_PERIODS, ROLE_LANDLORD, SERVER_ERROR, VALIDATION_ERROR,
)
from app.utils.haversine import distance_from_ub
from app.utils.geocoding import reverse_geocode
from app.utils.pagination import paginate_query
from app.utils.response import error_response, success_response, paginated_response
from app.utils.validators import validate_file_upload

logger = logging.getLogger(__name__)
listings_bp = Blueprint("listings", __name__, url_prefix="/listings")
LISTINGS_COL = "listings"
_cs = CloudinaryService()


def _db():
    return get_db()


def _listing_doc(listing_id: str):
    doc = _db().collection(LISTINGS_COL).document(listing_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["id"] = doc.id
    return data


def _safe_listing(data: dict) -> dict:
    """Remove internal fields not suitable for public API."""
    return data


# ── Public routes ─────────────────────────────────────────────────────────────

@listings_bp.route("", methods=["GET"])
def browse_listings():
    """GET /listings — public browse with filters and pagination."""
    try:
        page        = max(1, int(request.args.get("page", 1)))
        limit       = min(50, max(1, int(request.args.get("limit", 20))))
        prop_type   = request.args.get("propertyType")
        min_rent    = request.args.get("minRent", type=float)
        max_rent    = request.args.get("maxRent", type=float)
        amenities   = request.args.get("amenities", "")
        max_dist_km = request.args.get("maxDistanceKm", type=float)
        sort_by     = request.args.get("sort", "newest")  # newest | price_asc | price_desc | closest
    except (ValueError, TypeError):
        return error_response(VALIDATION_ERROR, "Invalid query parameter.", status_code=422)

    q = _db().collection(LISTINGS_COL).where("status", "==", LISTING_STATUS_ACTIVE)

    if prop_type and prop_type in LISTING_TYPES:
        q = q.where("propertyType", "==", prop_type)

    # Fetch all matching active listings then filter in Python for complex predicates
    # (Firestore doesn't support arbitrary range + array-contains combinations without indexes)
    docs = list(q.stream())
    listings = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id

        if min_rent is not None and d.get("rentAmount", 0) < min_rent:
            continue
        if max_rent is not None and d.get("rentAmount", 0) > max_rent:
            continue
        if amenities:
            required = [a.strip() for a in amenities.split(",") if a.strip()]
            listing_amenities = d.get("amenities", [])
            if not all(a in listing_amenities for a in required):
                continue
        if max_dist_km is not None:
            dist = d.get("distanceFromUbKm", 999)
            if dist > max_dist_km:
                continue

        listings.append(d)

    # Sort
    if sort_by == "price_asc":
        listings.sort(key=lambda x: x.get("rentAmount", 0))
    elif sort_by == "price_desc":
        listings.sort(key=lambda x: x.get("rentAmount", 0), reverse=True)
    elif sort_by == "closest":
        listings.sort(key=lambda x: x.get("distanceFromUbKm", 999))
    else:  # newest
        listings.sort(key=lambda x: x.get("createdAt", datetime.min), reverse=True)

    total = len(listings)
    start = (page - 1) * limit
    page_items = listings[start : start + limit]

    return paginated_response(page_items, page=page, limit=limit, total=total)


@listings_bp.route("/<listing_id>", methods=["GET"])
def get_listing(listing_id: str):
    """GET /listings/:id — public detail. Increments viewsCount."""
    listing = _listing_doc(listing_id)
    if not listing:
        return error_response(LISTING_NOT_FOUND, "Listing not found.", status_code=404)

    # Increment view count (best-effort, non-blocking)
    try:
        from google.cloud.firestore import Increment
        _db().collection(LISTINGS_COL).document(listing_id).update({
            "viewsCount": Increment(1)
        })
    except Exception:
        pass

    return success_response(data=listing)


# ── Landlord routes ───────────────────────────────────────────────────────────

@listings_bp.route("/my", methods=["GET"])
@require_role_active(ROLE_LANDLORD)
def my_listings():
    """GET /listings/my — landlord's own listings regardless of status."""
    landlord_id = g.user["sub"]
    status_filter = request.args.get("status")

    q = _db().collection(LISTINGS_COL).where("landlordId", "==", landlord_id)
    if status_filter and status_filter in LISTING_STATUSES:
        q = q.where("status", "==", status_filter)

    docs = list(q.order_by("createdAt").stream())
    listings = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        listings.append(d)

    return success_response(data=listings)


@listings_bp.route("", methods=["POST"])
@require_role_active(ROLE_LANDLORD)
def create_listing():
    """POST /listings — create a new listing (multipart/form-data)."""
    landlord_id = g.user["sub"]

    if request.content_type and "multipart" in request.content_type:
        form = request.form
        files = request.files
    else:
        return error_response(VALIDATION_ERROR, "Multipart form data required for image uploads.", status_code=422)

    # Required fields
    title        = form.get("title", "").strip()
    description  = form.get("description", "").strip()
    prop_type    = form.get("propertyType", "")
    rent_amount  = form.get("rentAmount", type=float)
    rent_period  = form.get("rentPeriod", "monthly")
    avail_from   = form.get("availableFrom", "")
    rules        = form.get("rules", "")
    max_occ      = form.get("maxOccupants", type=int, default=1)
    amenities    = [a.strip() for a in form.get("amenities", "").split(",") if a.strip()]
    lat          = form.get("lat", type=float)
    lng          = form.get("lng", type=float)

    if not title:
        return error_response(VALIDATION_ERROR, "Title is required.", field="title", status_code=422)
    if prop_type not in LISTING_TYPES:
        return error_response(VALIDATION_ERROR, f"propertyType must be one of: {', '.join(LISTING_TYPES)}", field="propertyType", status_code=422)
    if rent_amount is None or rent_amount <= 0:
        return error_response(VALIDATION_ERROR, "Valid rentAmount is required.", field="rentAmount", status_code=422)
    if rent_period not in RENT_PERIODS:
        return error_response(VALIDATION_ERROR, f"rentPeriod must be one of: {', '.join(RENT_PERIODS)}", field="rentPeriod", status_code=422)

    # Require at least one exterior image
    exterior_files = request.files.getlist("exteriorImages")
    room_files     = request.files.getlist("roomImages")

    if not exterior_files or not any(f.filename for f in exterior_files):
        return error_response(LISTING_IMAGE_REQUIRED, "At least one exterior image is required.", field="exteriorImages", status_code=422)

    # Upload images to Cloudinary
    # Create listing doc first to get the ID for folder naming
    now = datetime.now(timezone.utc)
    doc_ref = _db().collection(LISTINGS_COL).document()
    listing_id = doc_ref.id

    exterior_urls = []
    room_urls = []

    try:
        for f in exterior_files[:8]:
            if f and f.filename:
                result = _cs.upload_image(f, folder=f"njangrent/listings/{listing_id}/exterior")
                exterior_urls.append(result["secure_url"])

        for f in room_files[:8]:
            if f and f.filename:
                result = _cs.upload_image(f, folder=f"njangrent/listings/{listing_id}/room")
                room_urls.append(result["secure_url"])
    except Exception as exc:
        logger.error("Image upload failed for listing %s: %s", listing_id, exc)
        return error_response(SERVER_ERROR, "Image upload failed. Please try again.", status_code=500)

    # Compute location data
    location = {}
    dist_km  = None
    if lat is not None and lng is not None:
        display_address = reverse_geocode(lat, lng)
        dist_km = distance_from_ub(lat, lng)
        location = {
            "lat":            lat,
            "lng":            lng,
            "displayAddress": display_address,
        }

    listing_data = {
        "landlordId":        landlord_id,
        "title":             title,
        "description":       description,
        "propertyType":      prop_type,
        "rentAmount":        rent_amount,
        "rentPeriod":        rent_period,
        "availableFrom":     avail_from,
        "amenities":         amenities,
        "rules":             rules,
        "maxOccupants":      max_occ,
        "exteriorImages":    exterior_urls,
        "roomImages":        room_urls,
        "location":          location,
        "distanceFromUbKm":  dist_km,
        "status":            LISTING_STATUS_PENDING_ADMIN_REVIEW,
        "viewsCount":        0,
        "createdAt":         now,
        "updatedAt":         now,
    }

    doc_ref.set(listing_data)
    listing_data["id"] = listing_id
    logger.info("Listing created id=%s landlord=%s status=pending_admin_review", listing_id, landlord_id)

    return success_response(data=listing_data, status_code=201)


@listings_bp.route("/<listing_id>", methods=["PUT"])
@require_role_active(ROLE_LANDLORD)
def update_listing(listing_id: str):
    """PUT /listings/:id — landlord updates own listing."""
    landlord_id = g.user["sub"]
    listing = _listing_doc(listing_id)

    if not listing:
        return error_response(LISTING_NOT_FOUND, "Listing not found.", status_code=404)
    if listing["landlordId"] != landlord_id:
        return error_response(AUTH_FORBIDDEN, "You do not own this listing.", status_code=403)

    if request.content_type and "multipart" in request.content_type:
        form = request.form
        files = request.files
    else:
        form = request.get_json(silent=True) or {}
        files = {}

    updates = {"updatedAt": datetime.now(timezone.utc)}

    updatable = ["title", "description", "rentAmount", "rentPeriod", "availableFrom",
                 "rules", "maxOccupants", "amenities"]
    for field in updatable:
        val = form.get(field) if hasattr(form, "get") else form.get(field)
        if val is not None:
            updates[field] = val

    lat = (form.get("lat") or form.get("lat")) if hasattr(form, "get") else None
    lng = (form.get("lng") or form.get("lng")) if hasattr(form, "get") else None
    if lat and lng:
        try:
            lat, lng = float(lat), float(lng)
            display_address = reverse_geocode(lat, lng)
            dist_km = distance_from_ub(lat, lng)
            updates["location"] = {"lat": lat, "lng": lng, "displayAddress": display_address}
            updates["distanceFromUbKm"] = dist_km
        except (ValueError, TypeError):
            pass

    # Upload additional images
    new_exterior = request.files.getlist("exteriorImages") if files else []
    new_room     = request.files.getlist("roomImages") if files else []
    if new_exterior:
        extra_urls = []
        for f in new_exterior[:8]:
            if f and f.filename:
                result = _cs.upload_image(f, folder=f"njangrent/listings/{listing_id}/exterior")
                extra_urls.append(result["secure_url"])
        if extra_urls:
            existing = listing.get("exteriorImages", [])
            updates["exteriorImages"] = (existing + extra_urls)[:8]

    if new_room:
        extra_urls = []
        for f in new_room[:8]:
            if f and f.filename:
                result = _cs.upload_image(f, folder=f"njangrent/listings/{listing_id}/room")
                extra_urls.append(result["secure_url"])
        if extra_urls:
            existing = listing.get("roomImages", [])
            updates["roomImages"] = (existing + extra_urls)[:8]

    _db().collection(LISTINGS_COL).document(listing_id).update(updates)
    listing.update(updates)
    return success_response(data=listing)


@listings_bp.route("/<listing_id>", methods=["DELETE"])
@require_role_active(ROLE_LANDLORD)
def deactivate_listing(listing_id: str):
    """DELETE /listings/:id — landlord deactivates own listing."""
    landlord_id = g.user["sub"]
    listing = _listing_doc(listing_id)

    if not listing:
        return error_response(LISTING_NOT_FOUND, "Listing not found.", status_code=404)
    if listing["landlordId"] != landlord_id:
        return error_response(AUTH_FORBIDDEN, "You do not own this listing.", status_code=403)

    _db().collection(LISTINGS_COL).document(listing_id).update({
        "status":    LISTING_STATUS_DEACTIVATED,
        "updatedAt": datetime.now(timezone.utc),
    })
    return success_response(data=None, message="Listing deactivated.")
