import json

from django.contrib.auth.models import User
from django.db import models


class SensorSession(models.Model):
    """A recording session containing multiple frames of pressure data."""
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    session_date = models.DateField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    flagged_for_review = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-session_date', '-start_time']

    def __str__(self):
        return f"Session for {self.patient.username} on {self.session_date}"

    @property
    def frame_count(self):
        return self.frames.count()

    @property
    def duration_minutes(self):
        if self.end_time and self.start_time:
            delta = self.end_time - self.start_time
            return int(delta.total_seconds() / 60)
        return None


class SensorFrame(models.Model):
    """A single 32x32 pressure frame at a specific timestamp."""
    session = models.ForeignKey(SensorSession, on_delete=models.CASCADE, related_name='frames')
    timestamp = models.DateTimeField()
    frame_index = models.PositiveIntegerField()
    # Store 32x32 matrix as JSON array
    data = models.TextField()  # JSON: list of 1024 integers (32x32 flattened)

    class Meta:
        ordering = ['timestamp', 'frame_index']
        unique_together = ['session', 'frame_index']

    def __str__(self):
        return f"Frame {self.frame_index} @ {self.timestamp}"

    def get_matrix(self):
        """Return data as list of 1024 integers."""
        return json.loads(self.data)

    def set_matrix(self, matrix):
        """Set data from list of 1024 integers."""
        self.data = json.dumps(matrix)


class PressureMetrics(models.Model):
    """Calculated pressure metrics for a single frame."""
    RISK_LEVELS = [
        ('low', 'Low Risk'),
        ('moderate', 'Moderate Risk'),
        ('high', 'High Risk'),
        ('critical', 'Critical Risk'),
    ]

    frame = models.OneToOneField(SensorFrame, on_delete=models.CASCADE, related_name='metrics')
    peak_pressure_index = models.FloatField()       # Highest reading excluding < 10-pixel areas
    contact_area_percent = models.FloatField()       # % of pixels above lower threshold
    average_pressure = models.FloatField()
    asymmetry_score = models.FloatField(default=0.0)  # Left/right imbalance 0-100
    pressure_variability = models.FloatField(default=0.0)  # Coefficient of variation of in-contact pressure
    pressure_concentration = models.FloatField(default=0.0)  # 0-100 localised load intensity index
    movement_index = models.FloatField(default=0.0)  # Frame-to-frame movement intensity 0-100
    sustained_load_index = models.FloatField(default=0.0)  # Persistence of high load over recent frames 0-100
    center_of_pressure_x = models.FloatField(null=True, blank=True)  # 0-31 x-axis
    center_of_pressure_y = models.FloatField(null=True, blank=True)  # 0-31 y-axis
    risk_level = models.CharField(max_length=20, choices=RISK_LEVELS, default='low')
    risk_score = models.FloatField(default=0.0)      # 0-100 composite score
    hot_zones = models.TextField(default='[]')       # JSON: list of {x, y, value} high-pressure pixels
    plain_english = models.TextField(blank=True)     # AI-generated explanation

    class Meta:
        ordering = ['frame__timestamp']

    def __str__(self):
        return f"Metrics for Frame {self.frame.frame_index} - {self.risk_level}"

    def get_hot_zones(self):
        return json.loads(self.hot_zones)


class Comment(models.Model):
    """Patient or clinician comment linked to a specific session/timestamp."""
    AUTHOR_TYPES = [
        ('patient', 'Patient'),
        ('clinician', 'Clinician'),
    ]

    session = models.ForeignKey(SensorSession, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pressure_comments')
    author_type = models.CharField(max_length=20, choices=AUTHOR_TYPES, default='patient')
    frame = models.ForeignKey(SensorFrame, on_delete=models.SET_NULL, null=True, blank=True, related_name='comments')
    timestamp_reference = models.DateTimeField()    # The time this comment refers to
    text = models.TextField()
    is_reply = models.BooleanField(default=False)
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.username} on {self.session}"


class PressureAlert(models.Model):
    """System-generated alert for high-pressure events."""
    ALERT_TYPES = [
        ('high_ppi', 'High Peak Pressure'),
        ('sustained', 'Sustained High Pressure'),
        ('asymmetry', 'Significant Asymmetry'),
        ('critical', 'Critical Pressure Level'),
    ]

    session = models.ForeignKey(SensorSession, on_delete=models.CASCADE, related_name='alerts')
    frame = models.ForeignKey(SensorFrame, on_delete=models.SET_NULL, null=True, related_name='alerts')
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPES)
    message = models.TextField()
    risk_score = models.FloatField()
    acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='acknowledged_alerts'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Alert: {self.alert_type} for {self.session}"


class Report(models.Model):
    """Generated medical history report for a patient."""
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports')
    generated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='generated_reports'
    )
    title = models.CharField(max_length=200)
    date_range_start = models.DateField()
    date_range_end = models.DateField()
    sessions_included = models.ManyToManyField(SensorSession, blank=True)
    summary = models.TextField(blank=True)
    peak_risk_level = models.CharField(max_length=20, default='low')
    avg_ppi = models.FloatField(default=0.0)
    avg_contact_area = models.FloatField(default=0.0)
    total_high_risk_events = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Report: {self.title} for {self.patient.username}"
