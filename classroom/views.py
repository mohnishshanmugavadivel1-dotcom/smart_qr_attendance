from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
import re

from .models import ClassRoom, Subject, Enrollment
from accounts.models import User

# Simple validators
CODE_RE = re.compile(r'^[A-Z0-9\-_]{3,20}$')
NAME_RE = re.compile(r'^[A-Za-z0-9 \-_.]{2,50}$')

def _clean_code(raw):
    if not raw:
        return None
    c = raw.strip().upper().replace(' ', '-')
    if not CODE_RE.match(c):
        return None
    return c

def _clean_name(raw):
    if not raw:
        return None
    n = raw.strip()
    if not NAME_RE.match(n):
        return None
    return n

@login_required
def classroom_list(request):
    if request.user.is_teacher():
        classes = ClassRoom.objects.filter(teacher=request.user).prefetch_related('enrollments__student')
    else:
        enrolled_ids = Enrollment.objects.filter(student=request.user).values_list('classroom_id', flat=True)
        classes = ClassRoom.objects.filter(id__in=enrolled_ids).prefetch_related('enrollments__student')
    subjects = Subject.objects.all().order_by('code')
    teachers = User.objects.filter(role='teacher') if request.user.is_superuser else []
    return render(request, 'classroom/list.html', {'classes': classes, 'subjects': subjects, 'teachers': teachers})

@login_required
def create_classroom(request):
    if not request.user.is_teacher() and not request.user.is_superuser:
        messages.error(request, "Only teachers can create classrooms.")
        return redirect('classroom:list')
    if request.method == 'POST':
        name_raw = request.POST.get('name', '').strip()
        section_raw = request.POST.get('section', '').strip()
        code_raw = request.POST.get('code', '').strip()
        # Validation
        if not name_raw or len(name_raw) > 50:
            messages.error(request, "Class name must be 2–50 chars (letters, numbers, space, - _ .)")
            return redirect('classroom:list')
        if not re.match(r'^[A-Za-z]{2,10}$', name_raw):
            messages.error(request, "Branch name must be 2–10 letters (e.g., CSE, ECE)")
            return redirect('classroom:list')
        if not section_raw or len(section_raw) > 5:
            messages.error(request, "Section must be 1–5 chars (A, B, 01, etc.)")
            return redirect('classroom:list')
        code = _clean_code(code_raw)
        if not code:
            messages.error(request, "Class code must be 3–20 chars, A-Z 0-9 - _ (e.g., CSE-A-2025)")
            return redirect('classroom:list')
        if ClassRoom.objects.filter(code=code).exists():
            messages.error(request, f"Class code {code} already exists.")
            return redirect('classroom:list')
        if ClassRoom.objects.filter(name=name_raw.upper(), section=section_raw.upper()).exists():
            messages.error(request, f"Class {name_raw}-{section_raw} already exists.")
            return redirect('classroom:list')
        ClassRoom.objects.create(name=name_raw.upper(), section=section_raw.upper(), code=code, teacher=request.user)
        messages.success(request, f"Class {name_raw.upper()}-{section_raw.upper()} ({code}) created!")
        return redirect('classroom:list')
    return redirect('classroom:list')

@login_required
def create_subject(request):
    if not request.user.is_teacher() and not request.user.is_superuser:
        messages.error(request, "Only teachers can create subjects.")
        return redirect('classroom:list')
    if request.method == 'POST':
        name_raw = request.POST.get('name', '').strip()
        code_raw = request.POST.get('code', '').strip()
        desc = request.POST.get('description', '').strip()[:500]
        if not name_raw or len(name_raw) < 3 or len(name_raw) > 100:
            messages.error(request, "Subject name must be 3–100 chars.")
            return redirect('classroom:list')
        code = _clean_code(code_raw)
        if not code:
            messages.error(request, "Subject code must be 3–20 chars A-Z 0-9 - _ (e.g., CS201)")
            return redirect('classroom:list')
        if Subject.objects.filter(code=code).exists():
            messages.error(request, f"Subject code {code} already exists.")
            return redirect('classroom:list')
        Subject.objects.create(name=name_raw, code=code, description=desc)
        messages.success(request, f"Subject {name_raw} ({code}) created!")
        return redirect('classroom:list')
    return redirect('classroom:list')

@login_required
def manage_enrollment(request, class_id):
    classroom = get_object_or_404(ClassRoom.objects.select_related('teacher'), id=class_id)
    if request.user != classroom.teacher and not request.user.is_superuser:
        messages.error(request, "Not authorized to manage this class.")
        return redirect('classroom:list')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'enroll':
            username = request.POST.get('username', '').strip()
            roll = request.POST.get('roll_number', '').strip()[:30]
            if not username:
                messages.error(request, "Username is required.")
                return redirect('classroom:manage', class_id=classroom.id)
            if len(username) > 150:
                messages.error(request, "Username too long.")
                return redirect('classroom:manage', class_id=classroom.id)
            try:
                student = User.objects.get(username=username, role='student')
                obj, created = Enrollment.objects.get_or_create(
                    student=student, classroom=classroom,
                    defaults={'roll_number': roll or student.roll_number or username}
                )
                if created:
                    messages.success(request, f"{student.username} enrolled.")
                else:
                    messages.info(request, f"{student.username} already enrolled.")
            except User.DoesNotExist:
                messages.error(request, f"Student '{username}' not found. Must be a student account.")
        elif action == 'remove':
            enroll_id = request.POST.get('enroll_id')
            try:
                eid = int(enroll_id)
                deleted, _ = Enrollment.objects.filter(id=eid, classroom=classroom).delete()
                if deleted:
                    messages.success(request, "Enrollment removed.")
                else:
                    messages.error(request, "Enrollment not found.")
            except (ValueError, TypeError):
                messages.error(request, "Invalid enrollment.")
        return redirect('classroom:manage', class_id=classroom.id)
    enrollments = classroom.enrollments.select_related('student').order_by('roll_number')
    enrolled_student_ids = enrollments.values_list('student_id', flat=True)
    available_students = User.objects.filter(role='student').exclude(id__in=enrolled_student_ids).order_by('username')[:50]
    return render(request, 'classroom/manage.html', {
        'classroom': classroom,
        'enrollments': enrollments,
        'available_students': available_students
    })

@login_required
def enroll_self(request, class_id):
    if not request.user.is_student():
        messages.error(request, "Only students can self-enroll.")
        return redirect('classroom:list')
    classroom = get_object_or_404(ClassRoom, id=class_id)
    # Prevent enrolling in own taught class if teacher
    if Enrollment.objects.filter(student=request.user, classroom=classroom).exists():
        messages.info(request, f"Already enrolled in {classroom.code}.")
        return redirect('classroom:list')
    # Limit per student to prevent abuse (max 10 classes)
    if Enrollment.objects.filter(student=request.user).count() >= 10:
        messages.error(request, "You can enroll in max 10 classes.")
        return redirect('classroom:list')
    Enrollment.objects.get_or_create(student=request.user, classroom=classroom, defaults={'roll_number': request.user.roll_number or request.user.username})
    messages.success(request, f"Enrolled in {classroom.code} successfully!")
    return redirect('classroom:list')
