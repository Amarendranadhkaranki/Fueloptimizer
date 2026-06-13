"""Geo helpers: parsing input, distance math, and offline city lookup."""
from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path
from typing import Tuple

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

EARTH_RADIUS_MI = 3958.7613
BASE_DIR = Path(__file__).resolve().parents[2]
CITY_COORDS_CSV = BASE_DIR / "data" / "us_cities.csv"


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in miles."""
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(a))


def parse_location(value: str) -> Tuple[float, float]:
    """Parse 'lat,lng', resolve 'City, ST', or geocode free text."""
    value = (value or "").strip()
    if "," in value:
        try:
            lat_s, lng_s = value.split(",", 1)
            return float(lat_s), float(lng_s)
        except ValueError:
            pass
    offline = resolve_city_state(value)
    if offline:
        return offline
    return geocode_address(value)


def _clean_token(value: str) -> str:
    return " ".join((value or "").strip().lower().replace(".", "").split())


@lru_cache(maxsize=1)
def load_city_coordinates() -> dict[tuple[str, str], tuple[float, float]]:
    """Load bundled city centroids for fast, offline CSV imports."""
    coords: dict[tuple[str, str], tuple[float, float]] = {}
    if not CITY_COORDS_CSV.exists():
        return coords
    with CITY_COORDS_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            city = _clean_token(row.get("CITY") or "")
            state_code = _clean_token(row.get("STATE_CODE") or "")
            state_name = _clean_token(row.get("STATE_NAME") or "")
            try:
                latlng = (float(row["LATITUDE"]), float(row["LONGITUDE"]))
            except (KeyError, TypeError, ValueError):
                continue
            if city and state_code:
                coords[(city, state_code)] = latlng
            if city and state_name:
                coords[(city, state_name)] = latlng
    return coords


def resolve_city_state(query: str, state: str | None = None) -> Tuple[float, float] | None:
    """Resolve a City/State pair from the bundled CSV without network calls."""
    if state is None:
        parts = [p.strip() for p in (query or "").split(",") if p.strip()]
        if len(parts) < 2:
            return None
        city = parts[0]
        state = parts[1]
    else:
        city = query

    state = state.replace("USA", "").replace("US", "").strip()
    return load_city_coordinates().get((_clean_token(city), _clean_token(state)))


@lru_cache(maxsize=2048)
def geocode_address(query: str) -> Tuple[float, float]:
    """Cached Nominatim geocoding. Caller must respect 1 req/sec policy."""
    geocoder = Nominatim(user_agent="fuel-optimizer/1.0")
    geocode = RateLimiter(geocoder.geocode, min_delay_seconds=1.0)
    location = geocode(query)
    if not location:
        raise ValueError(f"Could not geocode location: {query!r}")
    return float(location.latitude), float(location.longitude)
