from django.urls import path
from .views import TripOptimizeView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("trip/optimize/", TripOptimizeView.as_view(), name="trip-optimize"),
]
