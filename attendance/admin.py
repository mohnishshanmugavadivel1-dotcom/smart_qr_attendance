from django.contrib import admin
from .models import AttendanceSession, AttendanceAttempt, AttendanceRecord, LocationDenial

@admin.register(AttendanceSession)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'classroom', 'subject', 'teacher', 'status', 'face_verification_enabled', 'allowed_radius_meters', 'created_at', 'expires_at')
    list_filter = ('status', 'face_verification_enabled', 'classroom', 'subject')
    search_fields = ('token',)
    readonly_fields = ('token',)

@admin.register(AttendanceAttempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'attempt_number', 'status', 'location_verified', 'face_verified', 'distance_meters', 'created_at')
    list_filter = ('status','location_verified','face_verified')

@admin.register(AttendanceRecord)
class RecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'status', 'method', 'face_verified', 'distance_meters', 'marked_at')
    list_filter = ('status', 'method', 'face_verified', 'session__classroom')

@admin.register(LocationDenial)
class LocationDenialAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'reason', 'created_at')
    list_filter = ('reason','session__classroom')
