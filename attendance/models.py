import secrets
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from classroom.models import ClassRoom, Subject

class AttendanceSession(models.Model):
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('EXPIRED', 'Expired'),
        ('CLOSED', 'Closed'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendance_sessions')
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name='attendance_sessions')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='attendance_sessions')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    # === NEW: Location & Face ===
    # Teacher's location (source of truth for 50m radius)
    teacher_latitude = models.FloatField(null=True, blank=True, help_text="Teacher lat at session start")
    teacher_longitude = models.FloatField(null=True, blank=True, help_text="Teacher lng at session start")
    teacher_location_updated_at = models.DateTimeField(null=True, blank=True)
    # Teacher can toggle face verification on/off anytime
    face_verification_enabled = models.BooleanField(default=False, help_text="If True, students must pass face scan")
    # Radius in meters (default 50)
    allowed_radius_meters = models.PositiveIntegerField(default=50)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.classroom.code} - {self.subject.code} @ {self.created_at:%Y-%m-%d %H:%M} [{self.status}]"

    def is_expired(self):
        return timezone.now() >= self.expires_at or self.status == 'EXPIRED'

    def is_active(self):
        return self.status == 'OPEN' and timezone.now() < self.expires_at

    def is_closed(self):
        return self.status == 'CLOSED'

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            from django.conf import settings
            self.expires_at = timezone.now() + timedelta(seconds=getattr(settings, 'QR_EXPIRY_SECONDS', 30))
        super().save(*args, **kwargs)

    def get_present_count(self):
        return self.records.filter(status='PRESENT').count()

    def get_total_enrolled(self):
        return self.classroom.enrollments.count()

    def expire_if_needed(self):
        if self.status == 'OPEN' and timezone.now() >= self.expires_at:
            self.status = 'EXPIRED'
            self.save(update_fields=['status'])
            return True
        return False

    def has_teacher_location(self):
        return self.teacher_latitude is not None and self.teacher_longitude is not None

class AttendanceAttempt(models.Model):
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('INVALID', 'Invalid'),
        ('SUCCESS', 'Success'),
    )
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendance_attempts')
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name='attempts')
    attempt_number = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat = models.DateTimeField(auto_now_add=True)
    scan_verified_at = models.DateTimeField(null=True, blank=True)
    verification_started_at = models.DateTimeField(null=True, blank=True)

    # === NEW: Location & Face per attempt ===
    student_latitude = models.FloatField(null=True, blank=True)
    student_longitude = models.FloatField(null=True, blank=True)
    distance_meters = models.FloatField(null=True, blank=True, help_text="Distance from teacher at verification")
    location_verified = models.BooleanField(default=False)
    face_verified = models.BooleanField(default=False)
    face_image = models.TextField(null=True, blank=True, help_text="Base64 face snapshot (optional)")

    class Meta:
        unique_together = ('student', 'session', 'attempt_number')
        ordering = ['-created_at']

    def __str__(self):
        return f"Attempt {self.attempt_number} - {self.student.username} - {self.session.id} [{self.status}]"

    def is_stale(self):
        from django.conf import settings
        timeout = getattr(settings, 'HEARTBEAT_TIMEOUT_SECONDS', 15)
        return timezone.now() - self.last_heartbeat > timedelta(seconds=timeout)

class AttendanceRecord(models.Model):
    STATUS_CHOICES = (
        ('PRESENT', 'Present'),
        ('ABSENT', 'Absent'),
    )
    METHOD_CHOICES = (
        ('QR', 'QR'),
        ('MANUAL', 'Manual'),
    )
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name='records')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendance_records')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    marked_at = models.DateTimeField(auto_now_add=True)
    marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='manual_marks')

    # === NEW: Snapshot location/distance at mark time ===
    student_latitude = models.FloatField(null=True, blank=True)
    student_longitude = models.FloatField(null=True, blank=True)
    distance_meters = models.FloatField(null=True, blank=True)
    face_verified = models.BooleanField(default=False)

    class Meta:
        unique_together = ('session', 'student')
        ordering = ['-marked_at']

    def __str__(self):
        return f"{self.student.username} - {self.session} - {self.status} ({self.method})"

class LocationDenial(models.Model):
    """Tracks students who denied / disabled location — sent to teacher."""
    REASON_CHOICES = (
        ('denied', 'Permission denied'),
        ('unavailable', 'Location unavailable'),
        ('timeout', 'Timeout'),
        ('disabled', 'Disabled'),
    )
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name='location_denials')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='location_denials')
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default='denied')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # To avoid spam, one per student/session
    class Meta:
        unique_together = ('session', 'student')
        ordering = ['-created_at']

    def __str__(self):
        return f"DENIED {self.student.username} @ {self.session.id} ({self.reason})"
