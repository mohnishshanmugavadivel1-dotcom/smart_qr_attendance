from django.db import models
from django.conf import settings

class ClassRoom(models.Model):
    name = models.CharField(max_length=100, help_text="e.g., CSE")
    section = models.CharField(max_length=20, help_text="e.g., A, B")
    code = models.CharField(max_length=20, unique=True, help_text="e.g., CSE-A-2025")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='taught_classes', limit_choices_to={'role': 'teacher'})
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('name', 'section')
        ordering = ['name', 'section']
    
    def __str__(self):
        return f"{self.name}-{self.section} ({self.code})"
    
    @property
    def student_count(self):
        return self.enrollments.count()

class Subject(models.Model):
    name = models.CharField(max_length=100, help_text="e.g., Data Structures")
    code = models.CharField(max_length=20, unique=True, help_text="e.g., CS201")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.code})"

class Enrollment(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='enrollments', limit_choices_to={'role': 'student'})
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name='enrollments')
    roll_number = models.CharField(max_length=30, blank=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('student', 'classroom')
        ordering = ['roll_number', 'student__username']
    
    def __str__(self):
        return f"{self.student.username} -> {self.classroom}"
