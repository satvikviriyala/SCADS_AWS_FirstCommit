"""Great-circle distance for the impossible-travel rule.

SCADS compares *bucket centroids* — named coarse locations — not device
coordinates. The privacy design in ``docs/SECURITY_PRIVACY.md`` section 2 means
this module never sees a precise position.
"""

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two lat/lon points."""
    for name, value in (("lat1", lat1), ("lat2", lat2)):
        if not -90.0 <= float(value) <= 90.0:
            raise ValueError(name + " out of range: " + repr(value))
    for name, value in (("lon1", lon1), ("lon2", lon2)):
        if not -180.0 <= float(value) <= 180.0:
            raise ValueError(name + " out of range: " + repr(value))

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def implied_speed_kmh(distance_km: float, hours: float, floor_hours: float = 1.0 / 60.0) -> float:
    """Speed implied by covering ``distance_km`` in ``hours``.

    ``hours`` is floored at one minute. Two scans of the same serial seconds
    apart in different cities would otherwise imply an infinite speed, and the
    rule should report a very large finite number instead of producing ``inf``
    that then has to be special-cased downstream.
    """
    return float(distance_km) / max(float(floor_hours), float(hours))
