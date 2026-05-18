"""URL configuration for GoldFlux project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/news/", include("news.urls")),
    path("api/v1/prices/", include("prices.urls")),
    path("api/v1/", include("predictions.urls")),
]
