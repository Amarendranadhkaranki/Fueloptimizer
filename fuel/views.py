from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import TripRequestSerializer, TripResponseSerializer
from .services.routing import plan_trip


class TripOptimizeView(APIView):
    """POST /api/trip/optimize  -> optimized fuel plan for a US road trip."""

    def post(self, request, *args, **kwargs):
        req = TripRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        data = req.validated_data
        try:
            plan = plan_trip(
                start_raw=data["start"],
                finish_raw=data["finish"],
                starting_fuel_miles=data.get("starting_fuel_miles"),
            )
        except (ValueError, RuntimeError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        body = {
            "route_map": plan.route_geojson,
            "fuel_stops": [
                {
                    "name": s.station.name,
                    "address": s.station.address,
                    "city": s.station.city,
                    "state": s.station.state,
                    "price_per_gallon": round(s.station.price, 3),
                    "latitude": s.station.lat,
                    "longitude": s.station.lng,
                    "distance_from_start_miles": round(s.distance_from_start_miles, 2),
                    "gallons_to_pump": round(s.gallons_to_pump, 3),
                    "cost": round(s.cost, 2),
                }
                for s in plan.stops
            ],
            "total_fuel_cost": round(plan.total_fuel_cost, 2),
            "total_distance": round(plan.total_distance_miles, 2),
        }
        return Response(TripResponseSerializer(body).data, status=status.HTTP_200_OK)


class HealthView(APIView):
    def get(self, request, *args, **kwargs):
        from .models import FuelStation

        return Response({"status": "ok", "stations_loaded": FuelStation.objects.count()})
