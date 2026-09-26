from django.contrib import admin
from .models import ClassRoom, Subject, Enrollment

@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'section', 'teacher', 'student_count', 'created_at')
    search_fields = ('name', 'code', 'section')

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'created_at')
    search_fields = ('name', 'code')

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'classroom', 'roll_number', 'enrolled_at')
    list_filter = ('classroom',)
