from django.db import models


class Prediction(models.Model):
    """Gold price prediction for a specific future date."""

    predicted_date = models.DateField(unique=True, db_index=True)
    predicted_close_price = models.DecimalField(max_digits=10, decimal_places=2)
    confidence_interval_lower = models.DecimalField(max_digits=10, decimal_places=2)
    confidence_interval_upper = models.DecimalField(max_digits=10, decimal_places=2)
    generation_timestamp = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["predicted_date"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(
                    confidence_interval_lower__lte=models.F("confidence_interval_upper")
                ),
                name="ci_lower_lte_upper",
            )
        ]

    def __str__(self) -> str:
        return f"Prediction({self.predicted_date}: {self.predicted_close_price})"


class ModelMetadata(models.Model):
    """Metadata about a trained ML model version."""

    training_date = models.DateField()
    mean_absolute_error = models.DecimalField(max_digits=10, decimal_places=4)
    root_mean_squared_error = models.DecimalField(max_digits=10, decimal_places=4)
    number_of_training_samples = models.IntegerField()
    model_version = models.CharField(max_length=50)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-training_date"]

    def __str__(self) -> str:
        return f"ModelMetadata(v{self.model_version}, trained={self.training_date})"
