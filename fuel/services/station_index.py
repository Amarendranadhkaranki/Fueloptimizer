"""
In-memory KDTree index of fuel stations for O(log n) nearest-neighbor /
radius queries against the loaded dataset. Built once per process.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
from scipy.spatial import cKDTree

from fuel.models import FuelStation

EARTH_RADIUS_MI = 3958.7613


@dataclass(frozen=True)
class Station:
    id: int
    name: str
    address: str
    city: str
    state: str
    price: float
    lat: float
    lng: float


class StationIndex:
    """
    KDTree over unit-sphere XYZ projections of station lat/lng.
    Chord distance can be converted to great-circle miles, so we can
    query by an angular radius and translate it to miles.
    """

    _instance: "StationIndex | None" = None
    _lock = threading.Lock()

    def __init__(self, stations: List[Station]):
        self.stations = stations
        if not stations:
            self.tree = None
            self.xyz = np.empty((0, 3))
            return
        lats = np.radians([s.lat for s in stations])
        lngs = np.radians([s.lng for s in stations])
        xyz = np.column_stack(
            [np.cos(lats) * np.cos(lngs), np.cos(lats) * np.sin(lngs), np.sin(lats)]
        )
        self.xyz = xyz
        self.tree = cKDTree(xyz)

    # ---- singleton helpers ----
    @classmethod
    def instance(cls) -> "StationIndex":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls._build_from_db()
            return cls._instance

    @classmethod
    def invalidate(cls) -> None:
        with cls._lock:
            cls._instance = None

    @classmethod
    def _build_from_db(cls) -> "StationIndex":
        rows = FuelStation.objects.all().values_list(
            "id", "name", "address", "city", "state", "retail_price", "latitude", "longitude"
        )
        stations = [Station(*r) for r in rows]
        return cls(stations)

    # ---- queries ----
    @staticmethod
    def _miles_to_chord(miles: float) -> float:
        # chord = 2 * R * sin(theta / 2) where theta = miles / R
        theta = miles / EARTH_RADIUS_MI
        return 2.0 * math.sin(theta / 2.0)

    def query_radius(self, lat: float, lng: float, radius_miles: float) -> List[int]:
        if self.tree is None:
            return []
        latr, lngr = math.radians(lat), math.radians(lng)
        p = np.array([math.cos(latr) * math.cos(lngr), math.cos(latr) * math.sin(lngr), math.sin(latr)])
        return list(self.tree.query_ball_point(p, r=self._miles_to_chord(radius_miles)))

    def query_corridor(
        self, points: List[Tuple[float, float]], radius_miles: float
    ) -> List[int]:
        """Union of stations within radius_miles of ANY sample point."""
        if self.tree is None or not points:
            return []
        lats = np.radians([p[0] for p in points])
        lngs = np.radians([p[1] for p in points])
        xyz = np.column_stack(
            [np.cos(lats) * np.cos(lngs), np.cos(lats) * np.sin(lngs), np.sin(lats)]
        )
        result_sets = self.tree.query_ball_point(xyz, r=self._miles_to_chord(radius_miles))
        seen: set[int] = set()
        for rs in result_sets:
            seen.update(rs)
        return list(seen)
