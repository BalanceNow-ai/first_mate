"""Great-circle distance in nautical miles (commerce / Helm Dash quotes)."""

from __future__ import annotations

import math

EARTH_RADIUS_NM = 3440.065  # mean Earth radius in nautical miles


def haversine_nm(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS84 points in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))
