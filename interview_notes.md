# Fuel Optimizer Project - Interview Notes

## 1. Project overview

This project is a Django REST API that calculates the cheapest refueling strategy for a road trip in the US.

The app takes:
- start location
- finish location
- optional fuel remaining in the tank

Then it:
- fetches the route using OSRM
- finds nearby gas stations along the route
- selects fuel stops based on price and distance
- returns the route, stops, total cost, and total distance

This is a backend project that combines:
- Django
- REST API
- database design
- geospatial logic
- optimization algorithm
- performance-focused data structures

---

## 2. High-level project structure

### config/
This is the Django project configuration.

- settings.py
  - project settings
  - installed apps
  - database config
  - secret key
  - custom tuning variables

- urls.py
  - root URL routing
  - includes app routes

- wsgi.py
  - WSGI config for deployment

### fuel/
This is the main app where project logic lives.

- models.py
  - database schema

- serializers.py
  - request and response validation

- views.py
  - API endpoints

- urls.py
  - app-level URL mappings

- services/
  - geo.py: geographic parsing and geocoding
  - osrm.py: route fetcher from OSRM
  - station_index.py: KDTree search index
  - routing.py: optimization algorithm

- management/commands/
  - load_fuel_prices.py: import CSV fuel data into database

### data/
This folder stores data files.

- fuel_prices.csv
  - raw fuel station data

- us_cities.csv
  - offline city coordinate data used for geocoding

### manage.py
This starts Django and runs all management commands.

### requirements.txt
Contains all project dependencies.

---

## 3. Django settings explanation

File: config/settings.py

Important parts:

```python
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-insecure-key-change-me-in-production",
)
```

This is the Django secret key.
- If `DJANGO_SECRET_KEY` exists in environment variables, Django uses it.
- Otherwise, it uses a default development value.

This is not a secure production secret; it is just a fallback for local development.

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
```

This means the project uses SQLite and stores data in a file named `db.sqlite3` in the project folder.

This explains why we did not see the database immediately:
- SQLite database file is created only after initialization/migration
- `dbshell` failed because DB was not created yet

Then there are tunable variables:

```python
VEHICLE_MAX_RANGE_MILES = float(os.environ.get("VEHICLE_MAX_RANGE_MILES", 500))
VEHICLE_MPG = float(os.environ.get("VEHICLE_MPG", 10))
ROUTE_BUFFER_MILES = float(os.environ.get("ROUTE_BUFFER_MILES", 5))
OSRM_BASE_URL = os.environ.get(
    "OSRM_BASE_URL",
    "https://router.project-osrm.org/route/v1/driving",
)
```

These are runtime configuration values for:
- tank range
- fuel efficiency
- corridor width around route
- routing service URL

---

## 4. What the project does step by step

1. User sends trip request
2. Input is validated by DRF serializer
3. Start and finish are converted to coordinates
4. Route is fetched once from OSRM
5. Nearby stations are found near that route
6. Stations are projected to the route distance
7. Greedy fueling strategy is applied
8. Total gallons and cost are calculated
9. Response is returned in JSON

---

## 5. Main app files

### manage.py
This file bootstraps Django.

It sets the Django settings module and executes management commands like:
- runserver
- migrate
- makemigrations
- dbshell
- load_fuel_prices

---

### fuel/models.py
This is the database schema.

```python
class FuelStation(models.Model):
    opis_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=128, db_index=True)
    state = models.CharField(max_length=8, db_index=True)
    rack_id = models.IntegerField(null=True, blank=True)
    retail_price = models.FloatField()
    latitude = models.FloatField(db_index=True)
    longitude = models.FloatField(db_index=True)
```

This table stores each gas station with:
- name
- city and state
- address
- fuel price
- coordinates

Indexes are created for faster querying.

---

### fuel/serializers.py
This file validates requests and prepares responses.

`TripRequestSerializer` validates:
- start
- finish
- starting_fuel_miles (optional)

`FuelStopSerializer` validates each output stop.

`TripResponseSerializer` validates the final JSON response.

This ensures the API input is clean before running optimization logic.

---

### fuel/views.py
This file contains the API endpoints.

Main endpoints:
- `POST /api/trip/optimize/`
- `GET /api/health/`

`TripOptimizeView`:
- receives POST data
- validates JSON
- calls `plan_trip(...)`
- returns route map and stop details

`HealthView`:
- checks app status
- returns count of loaded stations

---

### fuel/urls.py
This file defines routes for the app.

```python
urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("trip/optimize/", TripOptimizeView.as_view(), name="trip-optimize"),
]
```

This is app-level URL mapping.

---

## 6. Core services

### fuel/services/geo.py
This is the geospatial helper module.

Important functions:

#### haversine_miles(lat1, lon1, lat2, lon2)
Computes great-circle distance in miles between two points on Earth.

#### parse_location(value)
Accepts values like:
- "32.7767,-96.7970"
- "Dallas, TX, USA"
- full address text

It resolves input to coordinates.

#### load_city_coordinates()
Reads data/us_cities.csv and stores city-state to lat/lng mappings.

#### resolve_city_state(query, state=None)
Checks the bundled city dataset first instead of geocoding every time.

#### geocode_address(query)
Uses Nominatim geocoder as a fallback if offline city data does not have a match.

Important: geocoding is cached to avoid repeated network calls.

---

### fuel/services/osrm.py
This module connects to the route engine.

It makes a single call to the OSRM API and gets:
- route coordinates
- route distance
- GeoJSON geometry

It uses:

```python
url = f"{settings.OSRM_BASE_URL}/{s_lng},{s_lat};{f_lng},{f_lat}"
```

This is because OSRM expects longitude, latitude order, not latitude, longitude.

The project is designed to perform exactly one route lookup per trip request.

---

### fuel/services/station_index.py
This is the in-memory spatial index.

It uses SciPy KDTree to store station positions.

Why it matters:
- scanning all stations for every request is slow
- KDTree gives fast radius and corridor searches

The `Station` dataclass stores lightweight station data such as:
- name
- city
- state
- price
- latitude
- longitude

`query_corridor(points, radius_miles)` finds all stations within a route corridor.

This is a strong performance optimization feature of the project.

---

### fuel/services/routing.py
This is the most important file in the project.

It contains the trip optimization algorithm.

Key steps:

1. Resolve start and finish to coordinates
2. Call OSRM for route geometry
3. Build cumulative distance along polyline
4. Query route corridor for nearby stations
5. Project stations onto the route
6. Select cheapest reachable station
7. Decide how much fuel to buy
8. Continue until destination is reached
9. Return total cost and stops

The key function is:

```python
def plan_trip(start_raw: str, finish_raw: str, starting_fuel_miles: Optional[float] = None)
```

This function decides the fueling plan.

It checks:
- if the whole trip fits in the starting tank, no stops needed
- otherwise, find stations near the route
- choose cheapest reachable station
- buy enough fuel to reach next cheaper station or destination

This is a greedy algorithm because it picks the best local option instead of solving a fully global optimization problem.

---

## 7. The dataset loading process

File: fuel/management/commands/load_fuel_prices.py

This command reads the CSV and loads data into the database.

It does:
- read CSV
- parse fuel price fields
- resolve city/state to coordinates
- skip invalid entries
- bulk insert station records
- invalidate station index after insertion

Important command example:

```bash
python manage.py load_fuel_prices --csv data/fuel_prices.csv --truncate
```

This loads the main dataset and clears existing station rows before inserting.

Without this, the app has no station data to search.

---

## 8. Data folder details

### data/fuel_prices.csv
This contains station-level fuel price dataset.

Typical records include:
- station name
- address
- city
- state
- retail price

It may not include coordinates, so the project resolves them during load.

### data/us_cities.csv
This is a bundled offline city coordinate file.

It helps map city/state to lat/lng quickly.

This improves performance and reduces geocoding network traffic.

---

## 9. Why the project is efficient

This project is designed to be practical and high-performance.

It uses:
- offline city lookup
- cached geocoding
- single OSRM route call
- in-memory KDTree index
- bulk CSV import
- greedy optimization logic

These decisions make the app faster and more reliable than naive station scanning.

---

## 10. Why we did not see the database at first

The database is configured in settings.py as SQLite:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
```

This means the file `db.sqlite3` is created only after running the database setup or migrations.

So when `python manage.py dbshell` failed, it meant the database file had not yet been created.

Correct command to create it:

```bash
python manage.py migrate
```

Then the database file should appear in the project folder.

---

## 11. Secret key and API configuration

The project reads values from environment variables.

### Django secret key
```python
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-insecure-key-change-me-in-production",
)
```

### OSRM URL
```python
OSRM_BASE_URL = os.environ.get(
    "OSRM_BASE_URL",
    "https://router.project-osrm.org/route/v1/driving",
)
```

Important: there is no private API key used here for OSRM because the base URL is a public service.

For local use, you can set them as environment variables in Windows PowerShell:

```powershell
$env:DJANGO_SECRET_KEY="your_super_secret_value"
$env:OSRM_BASE_URL="https://router.project-osrm.org/route/v1/driving"
```

---

## 12. Main interview explanation

“This project is a Django REST API for optimizing fuel stops on a road trip. It loads station price data from CSV, resolves locations using offline city data, fetches the route once from OSRM, and searches nearby stations using a KDTree for speed. The backend applies a greedy cheapest-reachable algorithm to decide where to refuel and returns the route map, stop details, and total fuel cost in JSON. It is a strong example of combining backend APIs, geospatial logic, optimization, and performance engineering.”

---

## 13. Most likely interview questions and answers

### Q1. What is this project about?
It calculates the cheapest fuel plan for a trip by combining route data, gas prices, and station locations.

### Q2. What is the tech stack?
Python, Django, Django REST Framework, SQLite, NumPy, SciPy, requests, geopy.

### Q3. Why use Django?
Because it is ideal for building a structured backend API with models, routes, and database support.

### Q4. What is the purpose of `manage.py`?
It boots Django and runs commands such as runserver and migrate.

### Q5. What is the purpose of the `config` folder?
Project-wide configuration and URL wiring.

### Q6. What is the role of `FuelStation`?
It stores station data used in route optimization.

### Q7. Why are coordinates stored?
Because the app needs to measure distance and find stations near the route.

### Q8. What is `TripRequestSerializer`?
It validates the input request before optimization begins.

### Q9. What is the role of `TripOptimizeView`?
It handles the trip optimization API and returns the result.

### Q10. Why use OSRM?
To get the road route and distance between the two points.

### Q11. Why is only one external API call used?
To reduce latency and dependency cost.

### Q12. What is KDTree?
A spatial data structure for fast nearest-neighbor and radius queries.

### Q13. Why is it used here?
To efficiently find gas stations near the route corridor.

### Q14. What is greedy algorithm?
It chooses the locally best option at each step to reduce cost.

### Q15. Why is the data imported from CSV?
Because the app uses a standard dataset of fuel station locations and prices.

### Q16. Why is there offline city data?
To resolve city/state to lat/lng without heavy online geocoding.

### Q17. Why did `dbshell` fail?
Because the SQLite database file had not been created yet.

### Q18. Where is the secret key stored?
In environment variable `DJANGO_SECRET_KEY` as defined in settings.py.

### Q19. Is there a secret API key for OSRM?
No, not in this project; OSRM is used via a public base URL.

### Q20. What could you improve in this project?
Add tests, authentication, caching, better logging, more optimization checks, and frontend integration.

---

## 14. Final short interview summary

“This project is a Django REST API that finds the cheapest fuel stop plan for a road trip. It stores station prices in SQLite, resolves locations using offline city data, calls OSRM once for the route, and uses a KDTree to search nearby stations quickly. Then it applies a greedy optimization algorithm to decide the cheapest route-based refueling strategy and returns the result as JSON. It is a strong example of API development, geospatial logic, optimization, and performance-focused backend engineering.”

---

## 15. Practical commands to run

From the project folder:

```bash
python manage.py migrate
python manage.py load_fuel_prices --csv data/fuel_prices.csv --truncate
python manage.py runserver 0.0.0.0:8000
```

Then test API:

```bash
curl http://localhost:8000/api/health/
```

Or use POST request to:

```bash
http://localhost:8000/api/trip/optimize/
```

---

## 16. Key takeaway

This project is not just a simple CRUD app. It is a real optimization engine focused on:
- route planning
- geospatial data handling
- efficient search
- cost minimization
- API design

That is why it is a strong interview project.
