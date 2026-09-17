"""Named coarse locations.

SCADS never handles a device coordinate. A scan reports a *named bucket* whose
centroid is used for distance arithmetic, which keeps the impossible-travel rule
working while collecting nothing that identifies a person
(``docs/SECURITY_PRIVACY.md`` section 2).

The ``_DEMO`` suffix is load-bearing: these are simulation inputs chosen in the
UI, and every surface that shows one must label it as simulated so a viewer is
never misled into thinking a real position was observed.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class NamedLocation:
    key: str
    display_name: str
    lat: float
    lon: float
    simulated: bool = True

    def to_public(self) -> Dict[str, object]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "simulated": self.simulated,
        }


# City centroids, rounded to two decimals (~1 km). Deliberately coarse: the
# rule needs inter-city distance, not a street.
DEMO_LOCATIONS: Dict[str, NamedLocation] = {
    "BENGALURU_DEMO": NamedLocation("BENGALURU_DEMO", "Bengaluru (simulated)", 12.97, 77.59),
    "DELHI_DEMO": NamedLocation("DELHI_DEMO", "Delhi (simulated)", 28.61, 77.21),
    "MUMBAI_DEMO": NamedLocation("MUMBAI_DEMO", "Mumbai (simulated)", 19.08, 72.88),
    "CHENNAI_DEMO": NamedLocation("CHENNAI_DEMO", "Chennai (simulated)", 13.08, 80.27),
    "KOLKATA_DEMO": NamedLocation("KOLKATA_DEMO", "Kolkata (simulated)", 22.57, 88.36),
    "PHARMACY_DEMO": NamedLocation("PHARMACY_DEMO", "Local pharmacy (simulated)", 12.98, 77.61),
}


def get_location(key: Optional[str]) -> Optional[NamedLocation]:
    if not key:
        return None
    return DEMO_LOCATIONS.get(key.strip().upper())


def list_locations() -> List[NamedLocation]:
    return sorted(DEMO_LOCATIONS.values(), key=lambda loc: loc.display_name)


def resolve_coordinates(label: Optional[str], lat: Optional[float], lon: Optional[float]):
    """Resolve a location to coordinates.

    A known named bucket wins over client-supplied coordinates, so a client
    cannot move a named location by sending different numbers with it. Raw
    coordinates are accepted only when they carry no recognised name, and are
    rounded to a ~1 km cell before use.
    """
    known = get_location(label)
    if known is not None:
        return known.lat, known.lon
    if lat is None or lon is None:
        return None, None
    try:
        latitude, longitude = float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        return None, None
    return round(latitude, 2), round(longitude, 2)
