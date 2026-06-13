# Fuel Optimizer API (Django + DRF)

Production-ready REST API that computes the cheapest fueling strategy for a
US road trip given a vehicle with a 500-mile tank @ 10 MPG.

- Exactly **one** external API call per request (OSRM for route geometry).
- Gas-price lookups are 100% local, served from an in-memory **SciPy KDTree**
  built on top of the imported CSV dataset.
- Greedy cheapest-reachable algorithm with look-ahead: at each station the
  truck pumps just enough fuel to reach the next cheaper station (or the
  destination), capped by tank capacity.

## Project layout

```
fuel_optimizer/
├── manage.py
├── requirements.txt
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── data/
│   ├── fuel_prices.csv         # provided dataset
│   └── us_cities.csv           # bundled offline coordinates for fast import
└── fuel/
    ├── models.py               # FuelStation (lat/lng indexed)
    ├── serializers.py
    ├── views.py                # /api/trip/optimize, /api/health
    ├── urls.py
    ├── services/
    │   ├── geo.py              # parsing + geocoding helpers
    │   ├── osrm.py             # the single external call
    │   ├── station_index.py    # SciPy KDTree singleton
    │   └── routing.py          # the optimization algorithm
    └── management/commands/
        └── load_fuel_prices.py # CSV importer with geocoding cache
```

## Setup

```bash
cd backend/fuel_optimizer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
```

## Load the dataset

The provided CSV has no coordinates, so the importer resolves each unique
`(City, State)` pair from bundled offline city coordinates. This completes in
seconds and avoids long-running online geocoding.

```bash
python manage.py load_fuel_prices --csv data/fuel_prices.csv --truncate
# Quick smoke test (first 200 rows):
python manage.py load_fuel_prices --csv data/fuel_prices.csv --truncate --limit 200
# Optional only if you want slow online fallback for unmatched cities:
python manage.py load_fuel_prices --csv data/fuel_prices.csv --truncate --online-geocode-missing
```

## Run

```bash
python manage.py runserver 0.0.0.0:8000
```

Health check (also reports stations loaded):

```bash
curl http://localhost:8000/api/health/
```

## Test with Postman / curl

`POST /api/trip/optimize/`

```json
{
  "start": "Dallas, TX, USA",
  "finish": "Atlanta, GA, USA",
  "starting_fuel_miles": 500
}
```

You may also pass coordinates: `"start": "32.7767,-96.7970"`.

Response shape:

```json
{
  "route_map": { "type": "LineString", "coordinates": [[lng, lat], ...] },
  "fuel_stops": [
    {
      "name": "...",
      "address": "...",
      "city": "...",
      "state": "...",
      "price_per_gallon": 3.099,
      "latitude": 32.77,
      "longitude": -96.79,
      "distance_from_start_miles": 412.3,
      "gallons_to_pump": 28.5,
      "cost": 88.32
    }
  ],
  "total_fuel_cost": 184.21,
  "total_distance": 781.42
}
```

## Tunables (env vars)

| Variable | Default | Description |
| --- | --- | --- |
| `VEHICLE_MAX_RANGE_MILES` | 500 | Tank capacity in miles |
| `VEHICLE_MPG` | 10 | Fuel economy |
| `ROUTE_BUFFER_MILES` | 5 | Corridor radius around the polyline |
| `OSRM_BASE_URL` | `https://router.project-osrm.org/route/v1/driving` | Routing API base |

## Algorithm summary

1. Parse `start` / `finish` (lat-lng or address).
2. **Single** GET to OSRM → full GeoJSON polyline + total distance in meters.
3. Compute cumulative mileage at every polyline vertex.
4. Sample the polyline every ~buffer-miles and run a single KDTree
   `query_ball_point` to collect all candidate stations within the corridor.
5. Project each candidate onto its nearest polyline vertex to obtain its
   distance-along-route.
6. Greedy: at each refueling decision, pick the cheapest station within the
   currently reachable window; pump only as many gallons as needed to reach
   the next cheaper station (or destination), capped to tank size.
7. Sum gallons × price → `total_fuel_cost`.
