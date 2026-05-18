from django.contrib import admin

from .models import ModelMetadata, Prediction

admin.site.register(Prediction)
admin.site.register(ModelMetadata)
