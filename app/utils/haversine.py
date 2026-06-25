# ---------------------------------------------------------------------------
# utils/haversine.py — Great-circle distance between two lat/lng coordinates
# ---------------------------------------------------------------------------
import math

# ── UB Main Gate ─────────────────────────────────────────────────────────────
UB_MAIN_GATE_LAT = 4.1537
UB_MAIN_GATE_LNG = 9.2443


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in kilometres between two points.

    Args:
        lat1, lng1: Origin coordinates in decimal degrees.
        lat2, lng2: Destination coordinates in decimal degrees.

    Returns:
        Distance in kilometres, rounded to 2 decimal places.
    """
    R = 6371.0  # Earth radius in km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(R * c, 2)


def distance_from_ub(lat: float, lng: float) -> float:
    """Return distance in km from the given coordinates to UB Main Gate."""
    return haversine(UB_MAIN_GATE_LAT, UB_MAIN_GATE_LNG, lat, lng)
