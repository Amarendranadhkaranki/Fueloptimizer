"""
Loads the OPIS fuel-prices CSV into the FuelStation table.

The CSV does not contain coordinates, so we geocode by City + State.
Geocoding uses Nominatim with caching: each unique (city, state) pair is
queried at most once, regardless of how many station rows reference it.

Usage:
    python manage.py load_fuel_prices --csv data/fuel_prices.csv
    python manage.py load_fuel_prices --csv data/fuel_prices.csv --truncate
    python manage.py load_fuel_prices --csv data/fuel_prices.csv --limit 500
"""
from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuel.models import FuelStation
from fuel.services.geo import geocode_address, resolve_city_state
from fuel.services.station_index import StationIndex


class Command(BaseCommand):
    help = "Load fuel-station prices from the OPIS CSV into the database."

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="Path to CSV file.")
        parser.add_argument(
            "--truncate", action="store_true", help="Delete existing rows first."
        )
        parser.add_argument(
            "--limit", type=int, default=None, help="Only import the first N rows."
        )
        parser.add_argument(
            "--skip-geocode-errors",
            action="store_true",
            default=True,
            help="Skip rows that fail to geocode instead of aborting.",
        )
        parser.add_argument(
            "--online-geocode-missing",
            action="store_true",
            help="Use slow online geocoding only for cities missing from bundled offline data.",
        )

    def handle(self, *args, **opts):
        csv_path = Path(opts["csv"])
        if not csv_path.exists():
            raise CommandError(f"CSV not found: {csv_path}")

        if opts["truncate"]:
            self.stdout.write("Truncating existing FuelStation rows...")
            FuelStation.objects.all().delete()

        loc_cache: dict[tuple[str, str], tuple[float, float]] = {}
        created = 0
        skipped = 0
        batch: list[FuelStation] = []
        BATCH = 500

        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for i, row in enumerate(reader):
                if opts["limit"] and i >= opts["limit"]:
                    break
                city = (row.get("City") or "").strip()
                state = (row.get("State") or "").strip()
                if not city or not state:
                    skipped += 1
                    continue
                key = (city.lower(), state.lower())
                if key not in loc_cache:
                    loc_cache[key] = resolve_city_state(city, state)  # type: ignore[assignment]
                    if loc_cache[key] is None and opts["online_geocode_missing"]:
                        try:
                            loc_cache[key] = geocode_address(f"{city}, {state}, USA")
                        except Exception as exc:  # noqa: BLE001
                            self.stderr.write(f"Geocode fail [{city}, {state}]: {exc}")
                            loc_cache[key] = None  # type: ignore[assignment]
                latlng = loc_cache[key]
                if not latlng:
                    skipped += 1
                    continue
                try:
                    price = float(row.get("Retail Price") or 0)
                except ValueError:
                    skipped += 1
                    continue

                batch.append(
                    FuelStation(
                        opis_id=int(row.get("OPIS Truckstop ID") or 0),
                        name=(row.get("Truckstop Name") or "").strip(),
                        address=(row.get("Address") or "").strip(),
                        city=city,
                        state=state,
                        rack_id=int(row["Rack ID"]) if row.get("Rack ID") else None,
                        retail_price=price,
                        latitude=latlng[0],
                        longitude=latlng[1],
                    )
                )
                if len(batch) >= BATCH:
                    with transaction.atomic():
                        FuelStation.objects.bulk_create(batch, ignore_conflicts=True)
                    created += len(batch)
                    self.stdout.write(f"...inserted {created} rows")
                    batch.clear()

        if batch:
            with transaction.atomic():
                FuelStation.objects.bulk_create(batch, ignore_conflicts=True)
            created += len(batch)

        StationIndex.invalidate()
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Inserted {created} stations, skipped {skipped}, "
                f"unique locations resolved: {sum(1 for v in loc_cache.values() if v)}."
            )
        )
