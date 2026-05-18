"""URL configuration for the predictions app."""

from django.urls import path

from predictions.views import ModelMetadataView, PredictionListView

urlpatterns = [
    path("prices/predictions", PredictionListView.as_view(), name="prediction-list"),
    path("model/metadata", ModelMetadataView.as_view(), name="model-metadata"),
]
