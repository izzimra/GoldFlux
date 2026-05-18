from django.contrib import admin

from .models import GoldPrice


@admin.register(GoldPrice)
class GoldPriceAdmin(admin.ModelAdmin):
    list_display = ("date", "open", "high", "low", "close", "volume")
    list_filter = ("date",)
    ordering = ("-date",)
