from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    """Input for POST /api/trip/optimize."""

    start = serializers.CharField(
        help_text='Start location: "lat,lng" or a free-text address.'
    )
    finish = serializers.CharField(
        help_text='Finish location: "lat,lng" or a free-text address.'
    )
    starting_fuel_miles = serializers.FloatField(
        required=False,
        default=None,
        help_text="Range remaining in the tank in miles. Defaults to full tank.",
    )


class FuelStopSerializer(serializers.Serializer):
    name = serializers.CharField()
    address = serializers.CharField(allow_blank=True)
    city = serializers.CharField()
    state = serializers.CharField()
    price_per_gallon = serializers.FloatField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    distance_from_start_miles = serializers.FloatField()
    gallons_to_pump = serializers.FloatField()
    cost = serializers.FloatField()


class TripResponseSerializer(serializers.Serializer):
    route_map = serializers.DictField()
    fuel_stops = FuelStopSerializer(many=True)
    total_fuel_cost = serializers.FloatField()
    total_distance = serializers.FloatField()
