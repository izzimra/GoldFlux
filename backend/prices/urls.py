"""URL configuration for the prices app."""

from django.urls import path

from prices.views import HistoricalPriceView

urlpatterns = [
    path("historical", HistoricalPriceView.as_view(), name="historical-prices"),
]
