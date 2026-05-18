from django.db import models


class GoldPrice(models.Model):
    """Historical gold price record for the GC=F (Gold Futures) ticker."""

    date = models.DateField(unique=True, db_index=True)
    open = models.DecimalField(max_digits=10, decimal_places=2)
    high = models.DecimalField(max_digits=10, decimal_places=2)
    low = models.DecimalField(max_digits=10, decimal_places=2)
    close = models.DecimalField(max_digits=10, decimal_places=2)
    volume = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date"]
        indexes = [models.Index(fields=["date"])]

    def __str__(self):
        return f"GoldPrice({self.date}: close={self.close})"
