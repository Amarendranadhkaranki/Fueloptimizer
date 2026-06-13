"""Single-call OSRM client: fetch route geometry + distance."""
from __future__ import annotations

from typing import List, Tuple, TypedDict

import requests
from django.conf import settings


class RouteResult(TypedDict):
    coordinates: List[Tuple[float, float]]  # [(lat, lng), ...]
    distance_miles: float
    geojson: dict


def fetch_route(
    start: Tuple[float, float], finish: Tuple[float, float], timeout: float = 20.0
) -> RouteResult:
    """
    Make EXACTLY ONE call to OSRM and return route geometry + total distance.
    OSRM uses (lng, lat) order in its URL and GeoJSON output.
    """
    s_lat, s_lng = start
    f_lat, f_lng = finish
    url = (
        f"{settings.OSRM_BASE_URL}/"
        f"{s_lng},{s_lat};{f_lng},{f_lat}"
    )
    params = {"overview": "full", "geometries": "geojson", "steps": "false"}
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise RuntimeError(f"OSRM returned no route: {payload.get('code')}")

    route = payload["routes"][0]
    geometry = route["geometry"]  # GeoJSON LineString in [lng, lat]
    meters = float(route["distance"])
    distance_miles = meters / 1609.344

    coords_lnglat = geometry["coordinates"]
    coords_latlng: List[Tuple[float, float]] = [(c[1], c[0]) for c in coords_lnglat]
    return {
        "coordinates": coords_latlng,
        "distance_miles": distance_miles,
        "geojson": geometry,
    }
