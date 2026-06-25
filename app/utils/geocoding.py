# ---------------------------------------------------------------------------
# utils/geocoding.py — Reverse geocode lat/lng to a display address
# ---------------------------------------------------------------------------
import logging
import os

logger = logging.getLogger(__name__)


def reverse_geocode(lat: float, lng: float) -> str:
    """Reverse-geocode coordinates to a human-readable address string.

    Uses the Google Maps Geocoding API. Falls back to a coordinate string
    if the API key is missing or the request fails.

    Args:
        lat: Latitude in decimal degrees.
        lng: Longitude in decimal degrees.

    Returns:
        A formatted address string, e.g. "Molyko, Buea, South West Region, Cameroon"
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.warning("GOOGLE_MAPS_API_KEY not set — returning coordinate fallback")
        return f"{lat:.6f}, {lng:.6f}"

    try:
        import googlemaps
        gmaps = googlemaps.Client(key=api_key)
        results = gmaps.reverse_geocode((lat, lng))

        if results:
            # Prefer the first result's formatted address
            formatted = results[0].get("formatted_address", "")
            if formatted:
                return formatted

        return f"{lat:.6f}, {lng:.6f}"

    except Exception as exc:
        logger.error("Reverse geocode failed for (%s, %s): %s", lat, lng, exc)
        return f"{lat:.6f}, {lng:.6f}"
