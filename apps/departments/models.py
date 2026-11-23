from django.db import models

class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Department'
        verbose_name_plural = 'Departments'

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def employee_count(self):
        return self.employees.count()


class Designation(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='designations')
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ('department', 'title')
        ordering = ['department', 'title']
        verbose_name = 'Designation'
        verbose_name_plural = 'Designations'

    def __str__(self):
        return f"{self.title} - {self.department.name}"


class Branch(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name="Branch / Office Name")
    code = models.CharField(max_length=50, unique=True, verbose_name="Branch Code")
    address = models.TextField(blank=True, verbose_name="Office Address")
    latitude = models.DecimalField(max_digits=10, decimal_places=6, verbose_name="Office Latitude", help_text="e.g. 12.971598")
    longitude = models.DecimalField(max_digits=10, decimal_places=6, verbose_name="Office Longitude", help_text="e.g. 77.594566")
    radius_meters = models.PositiveIntegerField(default=100, verbose_name="Geofence Radius (Meters)", help_text="Allowed radius in meters for on-site punch (default 100m)")
    is_active = models.BooleanField(default=True, verbose_name="Is Active Branch")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Office Branch'
        verbose_name_plural = 'Office Branches'

    def __str__(self):
        return f"{self.name} ({self.code})"

    def distance_to(self, lat, lon):
        """Calculates distance in meters from this branch to given (lat, lon) using Haversine formula."""
        import math
        try:
            lat1 = math.radians(float(self.latitude))
            lon1 = math.radians(float(self.longitude))
            lat2 = math.radians(float(lat))
            lon2 = math.radians(float(lon))
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return 6371000 * c
        except (ValueError, TypeError):
            return float('inf')

    def is_within_radius(self, lat, lon):
        dist = self.distance_to(lat, lon)
        return dist <= self.radius_meters, dist

    @property
    def employee_count(self):
        return self.employees.count() if hasattr(self, 'employees') else 0
