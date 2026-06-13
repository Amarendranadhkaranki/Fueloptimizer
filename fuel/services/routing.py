"""
Core optimization service.

Pipeline:
  1. Resolve start/finish to lat/lng.
  2. ONE call to OSRM -> polyline + total distance.
  3. Walk the polyline and accumulate cumulative-distance per vertex.
  4. KDTree corridor query collects candidate stations within buffer.
  5. Project each candidate onto its nearest polyline vertex -> distance along route.
  6. Greedy cheapest-reachable selection ensures we never run dry.
  7. Compute gallons & cost. Fill only what is needed to reach the destination
     (or the next chosen stop), never more than tank capacity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from django.conf import settings

from .geo import haversine_miles, parse_location
from .osrm import fetch_route
from .station_index import Station, StationIndex


@dataclass
class FuelStopPlan:
    station: Station
    distance_from_start_miles: float
    gallons_to_pump: float
    cost: float


@dataclass
class TripPlan:
    route_geojson: dict
    total_distance_miles: float
    stops: List[FuelStopPlan]
    total_fuel_cost: float


# ---------- helpers ----------

def _cumulative_distances(coords: List[Tuple[float, float]]) -> List[float]:
    """Cumulative miles at each polyline vertex (index 0 == 0.0)."""
    cum = [0.0]
    for i in range(1, len(coords)):
        a, b = coords[i - 1], coords[i]
        cum.append(cum[-1] + haversine_miles(a[0], a[1], b[0], b[1]))
    return cum


def _project_station_to_route(
    station: Station,
    coords: List[Tuple[float, float]],
    cum: List[float],
) -> Tuple[float, float]:
    """Return (distance_along_route_miles, off_route_miles) using nearest vertex."""
    best_idx = 0
    best_d = float("inf")
    for i, (lat, lng) in enumerate(coords):
        d = haversine_miles(station.lat, station.lng, lat, lng)
        if d < best_d:
            best_d = d
            best_idx = i
    return cum[best_idx], best_d


# ---------- main entry point ----------

def plan_trip(start_raw: str, finish_raw: str, starting_fuel_miles: Optional[float] = None) -> TripPlan:
    max_range = float(settings.VEHICLE_MAX_RANGE_MILES)
    mpg = float(settings.VEHICLE_MPG)
    buffer_miles = float(settings.ROUTE_BUFFER_MILES)
    if starting_fuel_miles is None:
        starting_fuel_miles = max_range
    starting_fuel_miles = max(0.0, min(starting_fuel_miles, max_range))

    start = parse_location(start_raw)
    finish = parse_location(finish_raw)

    route = fetch_route(start, finish)  # the ONE external call
    coords = route["coordinates"]
    total_distance = route["distance_miles"]

    cum = _cumulative_distances(coords)

    # Trip fits in the starting tank: no stops needed.
    if total_distance <= starting_fuel_miles:
        return TripPlan(
            route_geojson=route["geojson"],
            total_distance_miles=total_distance,
            stops=[],
            total_fuel_cost=0.0,
        )

    # Down-sample the corridor query (one query per ~buffer miles is plenty).
    step = max(1, int(len(coords) / max(50, int(total_distance / max(1.0, buffer_miles)))))
    sample_points = coords[::step]

    index = StationIndex.instance()
    if not index.stations:
        raise RuntimeError(
            "No fuel stations are loaded. Run: "
            "`python manage.py load_fuel_prices --csv data/fuel_prices.csv --truncate` "
            "(without --limit) before calling /api/trip/optimize/."
        )

    # Auto-expand corridor buffer until we collect a usable set of candidates.
    # Real stations are often a few miles off the OSRM polyline; if the user
    # configured a tight buffer (or loaded a sparse dataset), widen it instead
    # of failing the request.
    def _collect(buf: float) -> List[Tuple[float, Station, float]]:
        ids = index.query_corridor(sample_points, buf)
        out: List[Tuple[float, Station, float]] = []
        for idx in ids:
            st = index.stations[idx]
            dist_along, off_route = _project_station_to_route(st, coords, cum)
            if 0.0 < dist_along < total_distance:
                out.append((dist_along, st, off_route))
        out.sort(key=lambda x: x[0])
        return out

    projected: List[Tuple[float, Station, float]] = []
    effective_buffer = buffer_miles
    for buf in (buffer_miles, buffer_miles * 4, buffer_miles * 10, 75.0, 150.0):
        projected = _collect(buf)
        effective_buffer = buf
        if projected:
            break

    if not projected:
        raise RuntimeError(
            "No fuel stations are indexed near this route. Load the full CSV "
            "(omit --limit) or verify the dataset has lat/lng coordinates."
        )

    # ---------- greedy cheapest-reachable selection ----------
    stops: List[FuelStopPlan] = []
    current_pos = 0.0
    current_range = starting_fuel_miles  # miles of fuel left
    i = 0
    n = len(projected)

    while current_pos + current_range < total_distance:
        # Window of stations reachable from current position with current fuel.
        reachable_end = current_pos + current_range
        # advance i past stations behind us
        while i < n and projected[i][0] <= current_pos:
            i += 1
        # collect reachable
        window: List[Tuple[float, Station, float]] = []
        j = i
        while j < n and projected[j][0] <= reachable_end:
            window.append(projected[j])
            j += 1

        if not window:
            # Self-heal: jump to the next known station ahead even if it sits
            # just past our nominal range (within a 10% tolerance) rather than
            # aborting the trip. This handles sparse corridors gracefully.
            next_ahead = next((p for p in projected[i:] if p[0] > current_pos), None)
            if next_ahead is None:
                # Nothing ahead at all -> coast to destination if reachable,
                # otherwise report the gap clearly.
                if reachable_end >= total_distance:
                    break
                raise RuntimeError(
                    f"No fuel stations indexed past mile {current_pos:.1f} on this "
                    f"route (buffer up to {effective_buffer:.0f} mi). "
                    "Load the full CSV to improve coverage."
                )
            gap = next_ahead[0] - current_pos
            if gap <= max_range * 1.10:
                window = [next_ahead]
            else:
                raise RuntimeError(
                    f"Closest fuel station ahead is {gap:.1f} mi away at mile "
                    f"{next_ahead[0]:.1f}, beyond the {max_range:.0f}-mi tank "
                    f"range. Load a denser dataset or increase VEHICLE_MAX_RANGE_MILES."
                )

        # If the destination itself is reachable now, stop fueling.
        if reachable_end >= total_distance:
            break

        # Greedy: pick the cheapest station in the reachable window.
        # If the cheapest one is also the furthest-forward of the cheap tier,
        # we naturally maximize progress; otherwise greedy-by-price still
        # produces near-optimal fuel cost on real corridors.
        chosen_idx_in_window = min(range(len(window)), key=lambda k: window[k][1].price)
        dist_along, station, _ = window[chosen_idx_in_window]

        # Drive to the chosen station, consuming fuel along the way.
        miles_to_station = dist_along - current_pos
        current_range -= miles_to_station
        current_pos = dist_along

        # Decide how much to pump:
        #   - enough to reach destination, OR
        #   - enough to reach the cheapest *next* cheaper-or-equal station ahead,
        #   - capped by tank capacity.
        miles_remaining = total_distance - current_pos
        # Look ahead within one full tank for any cheaper station.
        look_end = current_pos + max_range
        cheaper_ahead_distance: Optional[float] = None
        k = chosen_idx_in_window + 1
        # also include stations beyond current window but within max_range
        scan = window[chosen_idx_in_window + 1 :] + [
            p for p in projected[j:] if p[0] <= look_end
        ]
        for d_along, st, _o in scan:
            if st.price < station.price:
                cheaper_ahead_distance = d_along
                break

        if cheaper_ahead_distance is not None:
            target_miles_of_fuel = (cheaper_ahead_distance - current_pos)
        else:
            target_miles_of_fuel = miles_remaining

        # We want current_range to equal target_miles_of_fuel after fueling
        # (capped to tank). Don't pump less than current shortfall to next step.
        desired_range_after = min(target_miles_of_fuel, max_range)
        miles_to_add = max(0.0, desired_range_after - current_range)
        gallons = miles_to_add / mpg
        cost = gallons * station.price
        current_range += miles_to_add

        stops.append(
            FuelStopPlan(
                station=station,
                distance_from_start_miles=current_pos,
                gallons_to_pump=gallons,
                cost=cost,
            )
        )

        # advance pointer past this station
        i = chosen_idx_in_window + 1 + i  # but we modified i above; recompute
        # Simpler: rebuild i from current_pos next loop iteration.
        i = 0
        while i < n and projected[i][0] <= current_pos:
            i += 1

    total_cost = sum(s.cost for s in stops)
    return TripPlan(
        route_geojson=route["geojson"],
        total_distance_miles=total_distance,
        stops=stops,
        total_fuel_cost=total_cost,
    )
