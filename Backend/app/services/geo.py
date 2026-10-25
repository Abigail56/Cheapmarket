import math

from app.core.config import settings

EARTH_RADIUS_M = 6_371_000


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line (great-circle) distance in metres between two (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def eta_minutes(a: tuple[float, float], b: tuple[float, float]) -> int:
    """A plain estimate shown as "about N min": roads are ~1.3x the straight line,
    at RIDER_SPEED_KMH through city traffic."""
    km = distance_m(a, b) / 1000 * 1.3
    return max(1, math.ceil(km / max(settings.RIDER_SPEED_KMH, 5) * 60))
