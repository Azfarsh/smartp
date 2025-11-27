from django.db import models


class VendorLocationSession(models.Model):
    """
    Temporary store for vendor location verification flow.
    Phone updates this record; laptop polls until status=completed.
    """
    STATUS_PENDING = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_EXPIRED = 'expired'

    session_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=20,
        choices=[
            (STATUS_PENDING, 'Pending'),
            (STATUS_COMPLETED, 'Completed'),
            (STATUS_EXPIRED, 'Expired'),
        ],
        default=STATUS_PENDING,
        db_index=True,
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    full_address = models.TextField(blank=True)
    locality = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=255, blank=True)
    pincode = models.CharField(max_length=12, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"VendorLocationSession({self.session_id}, {self.status})"
