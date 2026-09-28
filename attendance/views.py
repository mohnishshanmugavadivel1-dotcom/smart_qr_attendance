import csv
import json
import logging
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator

from classroom.models import ClassRoom, Subject, Enrollment
from .models import AttendanceSession, AttendanceAttempt, AttendanceRecord, LocationDenial
from .utils import generate_qr_base64, get_qr_payload, haversine_meters

logger = logging.getLogger(__name__)

# Helpers
def teacher_required(view):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(settings.LOGIN_URL)
        if not request.user.is_teacher() and not request.user.is_superuser:
            return HttpResponseForbidden("Teachers only")
        return view(request, *args, **kwargs)
    return wrapper

def _rate_limit(request, key, limit=20, window=60):
    ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', 'unknown')
    uid = request.user.id if request.user.is_authenticated else 'anon'
    cache_key = f"rl:att:{key}:{ip}:{uid}"
    count = cache.get(cache_key, 0)
    if count >= limit:
        return False
    cache.set(cache_key, count+1, timeout=window)
    return True

def _validate_lat_lng(lat, lng):
    try:
        lat = float(lat); lng = float(lng)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None, None
        return lat, lng
    except:
        return None, None

@login_required
def dashboard_router(request):
    if request.user.is_teacher() or request.user.is_superuser:
        return redirect('attendance:teacher_dashboard')
    else:
        return redirect('attendance:student_dashboard')

# ================= TEACHER =================

@login_required
@teacher_required
def teacher_dashboard(request):
    classes = ClassRoom.objects.filter(teacher=request.user)
    subjects = Subject.objects.all()
    sessions = AttendanceSession.objects.filter(teacher=request.user).select_related('classroom','subject')[:10]
    total_sessions = AttendanceSession.objects.filter(teacher=request.user, status='CLOSED').count()
    total_students = Enrollment.objects.filter(classroom__teacher=request.user).values('student').distinct().count()
    today_present = AttendanceRecord.objects.filter(session__teacher=request.user, status='PRESENT', marked_at__date=timezone.now().date()).count()
    active_session = AttendanceSession.objects.filter(teacher=request.user, status='OPEN').order_by('-created_at').first()
    if active_session and active_session.is_expired():
        active_session.expire_if_needed()
        active_session = None
        active_session = AttendanceSession.objects.filter(teacher=request.user, status='OPEN').order_by('-created_at').first()
    # recent location denials for teacher
    recent_denials = LocationDenial.objects.filter(session__teacher=request.user).select_related('student','session','session__classroom').order_by('-created_at')[:10]
    context = {
        'classes': classes,
        'subjects': subjects,
        'sessions': sessions,
        'total_sessions': total_sessions,
        'total_students': total_students,
        'today_present': today_present,
        'active_session': active_session,
        'recent_denials': recent_denials,
    }
    return render(request, 'attendance/teacher_dashboard.html', context)

@login_required
@teacher_required
def create_session(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    classroom_id = request.POST.get('classroom')
    subject_id = request.POST.get('subject')
    if not classroom_id or not subject_id:
        return JsonResponse({'error': 'Class and Subject required'}, status=400)
    classroom = get_object_or_404(ClassRoom, id=classroom_id, teacher=request.user)
    subject = get_object_or_404(Subject, id=subject_id)
    face_enabled = request.POST.get('face_verification_enabled') in ('on','true','1', 'True')
    radius = request.POST.get('allowed_radius_meters')
    try:
        radius = int(radius) if radius else 50
        if radius < 10: radius = 10
        if radius > 500: radius = 500
    except:
        radius = 50
    # teacher location may be sent from JS
    lat = request.POST.get('teacher_latitude')
    lng = request.POST.get('teacher_longitude')
    try:
        lat = float(lat) if lat else None
        lng = float(lng) if lng else None
    except:
        lat = lng = None
    session = AttendanceSession.objects.create(
        teacher=request.user,
        classroom=classroom,
        subject=subject,
        face_verification_enabled=face_enabled,
        allowed_radius_meters=radius,
        teacher_latitude=lat,
        teacher_longitude=lng,
        teacher_location_updated_at=timezone.now() if lat and lng else None,
    )
    payload = get_qr_payload(request, session.token)
    qr_b64 = generate_qr_base64(payload)
    data = {
        'session_id': str(session.id),
        'token': session.token,
        'qr': qr_b64,
        'payload': payload,
        'expires_at': session.expires_at.isoformat(),
        'classroom': str(classroom),
        'subject': str(subject),
        'face_enabled': session.face_verification_enabled,
        'radius': session.allowed_radius_meters,
    }
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse(data)
    messages.success(request, f"QR Session created for {classroom.code} - {subject.name} {'+ Face Scan' if face_enabled else ''} • Radius {radius}m")
    return redirect('attendance:teacher_session', session_id=session.id)

@login_required
@teacher_required
def teacher_session_view(request, session_id):
    session = get_object_or_404(AttendanceSession, id=session_id, teacher=request.user)
    session.expire_if_needed()
    payload = get_qr_payload(request, session.token)
    qr_b64 = generate_qr_base64(payload)
    enrollments = Enrollment.objects.filter(classroom=session.classroom).select_related('student').order_by('roll_number')
    records = {r.student_id: r for r in session.records.select_related('student')}
    # attempts for face queue (OPEN attempts with face image)
    face_queue = AttendanceAttempt.objects.filter(session=session, status='OPEN').exclude(face_image__isnull=True).exclude(face_image__exact='').select_related('student').order_by('-created_at')[:10]
    # location denials — bulk fetch to avoid N+1
    denials_qs = LocationDenial.objects.filter(session=session).select_related('student').order_by('-created_at')
    denials_map = {d.student_id: d for d in denials_qs}
    denials = list(denials_qs)
    # latest attempt per student — single query
    latest_attempts = {}
    for a in AttendanceAttempt.objects.filter(session=session).select_related('student').order_by('-created_at'):
        if a.student_id not in latest_attempts:
            latest_attempts[a.student_id] = a
    students_data = []
    for e in enrollments:
        rec = records.get(e.student_id)
        att = latest_attempts.get(e.student_id)
        denial = denials_map.get(e.student_id)
        students_data.append({
            'enrollment': e,
            'student': e.student,
            'record': rec,
            'attempt': att,
            'denial': denial,
            'status': rec.status if rec else ('LOCATION_DENIED' if denial else 'PENDING'),
            'method': rec.method if rec else '-',
        })
    present_count = len([r for r in records.values() if r.status == 'PRESENT'])
    total = enrollments.count()
    return render(request, 'attendance/teacher_session.html', {
        'session': session,
        'qr_b64': qr_b64,
        'payload': payload,
        'students_data': students_data,
        'present_count': present_count,
        'total': total,
        'is_active': session.is_active(),
        'is_closed': session.is_closed(),
        'face_queue': face_queue,
        'denials': denials,
    })

@login_required
def session_status_api(request, session_id):
    session = get_object_or_404(AttendanceSession, id=session_id)
    if request.user != session.teacher:
        if not Enrollment.objects.filter(student=request.user, classroom=session.classroom).exists() and not request.user.is_superuser:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
    session.expire_if_needed()
    records = session.records.filter(status='PRESENT').select_related('student')
    present_list = [{'username': r.student.username, 'roll': r.student.roll_number or '', 'method': r.method, 'time': r.marked_at.strftime('%H:%M:%S'), 'distance': r.distance_meters, 'face': r.face_verified} for r in records]
    stale_attempts = AttendanceAttempt.objects.filter(session=session, status='OPEN')
    for att in stale_attempts:
        if att.is_stale():
            att.status = 'INVALID'
            att.save(update_fields=['status'])
    # denials for teacher polling
    denials = []
    if request.user == session.teacher or request.user.is_superuser:
        denials = [{'username': d.student.username, 'roll': d.student.roll_number or '', 'reason': d.reason, 'time': d.created_at.strftime('%H:%M:%S')} for d in LocationDenial.objects.filter(session=session).select_related('student')]
    # face queue count
    face_queue_count = AttendanceAttempt.objects.filter(session=session, status='OPEN').exclude(face_image__isnull=True).exclude(face_image__exact='').count()
    return JsonResponse({
        'session_id': str(session.id),
        'status': session.status,
        'is_active': session.is_active(),
        'is_expired': session.is_expired(),
        'expires_at': session.expires_at.isoformat(),
        'server_time': timezone.now().isoformat(),
        'present_count': len(present_list),
        'total': session.classroom.enrollments.count(),
        'present_list': present_list,
        'records': present_list,
        'face_enabled': session.face_verification_enabled,
        'radius': session.allowed_radius_meters,
        'teacher_lat': session.teacher_latitude,
        'teacher_lng': session.teacher_longitude,
        'teacher_location_set': session.has_teacher_location(),
        'denials': denials,
        'denials_count': len(denials),
        'face_queue_count': face_queue_count,
    })

@teacher_required
@login_required
@require_POST
def api_update_teacher_location(request, session_id):
    session = get_object_or_404(AttendanceSession, id=session_id, teacher=request.user)
    if session.is_closed():
        return JsonResponse({'error': 'Session closed'}, status=400)
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
    except:
        data = request.POST
    try:
        lat = float(data.get('latitude') or data.get('teacher_latitude') or data.get('lat'))
        lng = float(data.get('longitude') or data.get('teacher_longitude') or data.get('lng'))
    except:
        return JsonResponse({'error': 'latitude/longitude required'}, status=400)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return JsonResponse({'error': 'Invalid coordinates'}, status=400)
    # Optional accuracy (from best-of-3)
    try:
        acc = float(data.get('accuracy') or data.get('acc') or 0)
        if acc <=0 or acc>10000: acc=None
    except:
        acc=None
    session.teacher_latitude = lat
    session.teacher_longitude = lng
    session.teacher_location_updated_at = timezone.now()
    session.teacher_location_accuracy = acc
    # save with accuracy if field exists
    try:
        session.save(update_fields=['teacher_latitude','teacher_longitude','teacher_location_updated_at','teacher_location_accuracy'])
    except:
        session.save(update_fields=['teacher_latitude','teacher_longitude','teacher_location_updated_at'])
    # Log warning if accuracy poor (>30m explains 21m offset)
    if acc and acc>30:
        logger.warning(f"Teacher location low accuracy ±{acc}m session {session.id} teacher {request.user.username} — distance will be off by ~{acc}m")
    # broadcast
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer=get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(f"attendance_{session.id}", {"type":"attendance.update","data":{"type":"teacher_location","lat":lat,"lng":lng, "accuracy": acc}})
    except: pass
    return JsonResponse({'success': True, 'lat': lat, 'lng': lng, 'accuracy': acc, 'radius': session.allowed_radius_meters, 'warning': f'Accuracy ±{acc}m — move near window for better' if acc and acc>25 else None})

@teacher_required
@login_required
@require_POST
def api_toggle_face(request, session_id):
    session = get_object_or_404(AttendanceSession, id=session_id, teacher=request.user)
    if session.is_closed():
        return JsonResponse({'error': 'Session closed'}, status=400)
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
    except:
        data = request.POST
    # accept enabled as bool
    enabled_raw = data.get('enabled')
    if enabled_raw is None:
        enabled_raw = data.get('face_verification_enabled')
    if isinstance(enabled_raw, str):
        enabled = enabled_raw.lower() in ('true','1','on','yes')
    else:
        enabled = bool(enabled_raw)
    session.face_verification_enabled = enabled
    session.save(update_fields=['face_verification_enabled'])
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer=get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(f"attendance_{session.id}", {"type":"attendance.update","data":{"type":"face_toggle","enabled":enabled}})
    except: pass
    return JsonResponse({'success': True, 'face_enabled': enabled})

@teacher_required
@login_required
@require_POST
def api_teacher_verify_face(request, session_id):
    """Teacher captures student face via teacher's camera — TEACHER ONLY, manually on/off."""
    session = get_object_or_404(AttendanceSession, id=session_id, teacher=request.user)
    if session.is_closed():
        return JsonResponse({'error': 'Session closed'}, status=400)
    if not session.face_verification_enabled:
        return JsonResponse({'error': 'Face verification is OFF — turn it ON to capture'}, status=400)
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
    except:
        data = request.POST
    student_id = data.get('student_id') or data.get('student')
    face_image = data.get('face_image') or data.get('image')
    if not student_id:
        return JsonResponse({'error': 'student_id required'}, status=400)
    if not face_image or not isinstance(face_image, str) or not face_image.startswith('data:image/'):
        return JsonResponse({'error': 'face_image required (data:image/…)'}, status=400)
    if not (face_image.startswith('data:image/jpeg') or face_image.startswith('data:image/png') or face_image.startswith('data:image/jpg')):
        return JsonResponse({'error': 'Only JPEG/PNG allowed'}, status=400)
    if len(face_image) > 300000:
        return JsonResponse({'error': 'Image too large (300KB max)'}, status=400)
    if ';base64,' not in face_image:
        return JsonResponse({'error': 'Invalid base64'}, status=400)
    from accounts.models import User
    try:
        student = User.objects.get(id=student_id, role='student')
    except:
        return JsonResponse({'error': 'Student not found'}, status=404)
    if not Enrollment.objects.filter(student=student, classroom=session.classroom).exists():
        return JsonResponse({'error': 'Student not enrolled'}, status=400)
    # Find latest OPEN attempt for this student/session, or create a stub attempt for face queue
    attempt = AttendanceAttempt.objects.filter(student=student, session=session, status='OPEN').order_by('-created_at').first()
    if not attempt:
        # No OPEN attempt yet — create one so face queue shows; location will be filled when student starts
        # Allow teacher to pre-verify before QR — store as latest attempt with face only
        last = AttendanceAttempt.objects.filter(student=student, session=session).order_by('-attempt_number').first()
        next_num = (last.attempt_number + 1) if last else 1
        attempt = AttendanceAttempt.objects.create(
            student=student, session=session, attempt_number=next_num, status='OPEN',
            face_image=face_image[:200000], face_verified=True, face_verified_by_teacher=True,
            last_heartbeat=timezone.now()
        )
    else:
        attempt.face_image = face_image[:200000]
        attempt.face_verified = True
        attempt.face_verified_by_teacher = True
        attempt.save(update_fields=['face_image','face_verified','face_verified_by_teacher'])
    # If student already has a PRESENT record, also mark face_verified there
    rec = AttendanceRecord.objects.filter(session=session, student=student).first()
    if rec and not rec.face_verified:
        rec.face_verified = True
        rec.save(update_fields=['face_verified'])
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer=get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(f"attendance_{session.id}", {"type":"attendance.update","data":{"type":"face_captured","student": student.username, "by": "teacher"}})
    except: pass
    return JsonResponse({'success': True, 'student': student.username, 'roll': student.roll_number or '', 'face_verified': True, 'attempt_id': attempt.id})

@teacher_required
@login_required
@require_POST
def manual_mark(request, session_id):
    session = get_object_or_404(AttendanceSession, id=session_id, teacher=request.user)
    if session.is_closed():
        return JsonResponse({'error': 'Session is closed, cannot modify.'}, status=400)
    confirm = request.POST.get('confirm') == 'true' or request.POST.get('confirm') == 'on'
    if session.is_expired() and not confirm:
        return JsonResponse({'error': 'Session expired. Confirmation required to mark manually.', 'need_confirm': True}, status=400)
    student_id = request.POST.get('student_id')
    if not student_id:
        return JsonResponse({'error': 'student_id required'}, status=400)
    from accounts.models import User
    student = get_object_or_404(User, id=student_id, role='student')
    if not Enrollment.objects.filter(student=student, classroom=session.classroom).exists():
        return JsonResponse({'error': 'Student not enrolled in this class'}, status=400)
    try:
        with transaction.atomic():
            rec, created = AttendanceRecord.objects.get_or_create(
                session=session, student=student,
                defaults={'status': 'PRESENT', 'method': 'MANUAL', 'marked_by': request.user}
            )
            if not created:
                return JsonResponse({'error': 'Already marked present', 'already': True}, status=409)
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                layer = get_channel_layer()
                if layer:
                    async_to_sync(layer.group_send)(f"attendance_{session.id}", {
                        "type": "attendance.update",
                        "data": {
                            "type": "attendance_update",
                            "present_count": session.get_present_count(),
                            "student": student.username,
                            "method": "MANUAL"
                        }
                    })
            except: pass
            return JsonResponse({'success': True, 'message': f'{student.username} marked PRESENT (MANUAL)', 'present_count': session.get_present_count()})
    except IntegrityError:
        return JsonResponse({'error': 'Already marked (race)'}, status=409)

@teacher_required
@login_required
@require_POST
def finalize_session(request, session_id):
    # Use select_for_update to prevent concurrent finalize race
    with transaction.atomic():
        session = get_object_or_404(AttendanceSession.objects.select_for_update(), id=session_id, teacher=request.user)
        if session.is_closed():
            return JsonResponse({'error': 'Already closed'}, status=400)
        enrollments = Enrollment.objects.filter(classroom=session.classroom).select_related('student')
        present_ids = set(session.records.filter(status='PRESENT').values_list('student_id', flat=True))
        absent_created = 0
        for e in enrollments:
            if e.student_id not in present_ids:
                try:
                    AttendanceRecord.objects.create(session=session, student=e.student, status='ABSENT', method='MANUAL', marked_by=request.user)
                    absent_created += 1
                except IntegrityError:
                    pass
        session.status = 'CLOSED'
        session.closed_at = timezone.now()
        session.save(update_fields=['status', 'closed_at'])
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'absent_created': absent_created, 'status': 'CLOSED'})
    messages.success(request, f"Session finalized. {absent_created} students marked ABSENT. Total present: {len(present_ids)}")
    return redirect('attendance:teacher_session', session_id=session.id)

# ================= STUDENT =================

@login_required
def student_dashboard(request):
    if request.user.is_teacher():
        return redirect('attendance:teacher_dashboard')
    enrollments = Enrollment.objects.filter(student=request.user).select_related('classroom')
    classroom_ids = enrollments.values_list('classroom_id', flat=True)
    active_sessions = AttendanceSession.objects.filter(classroom_id__in=classroom_ids, status='OPEN').select_related('classroom','subject','teacher')
    active_sessions = [s for s in active_sessions if s.is_active()]
    total_records = AttendanceRecord.objects.filter(student=request.user).select_related('session')
    present_count = total_records.filter(status='PRESENT').count()
    total_closed = AttendanceSession.objects.filter(classroom_id__in=classroom_ids, status='CLOSED').count()
    percentage = round((present_count / total_closed * 100) if total_closed > 0 else 0, 1)
    history = total_records.order_by('-marked_at')[:10]
    open_attempts = AttendanceAttempt.objects.filter(student=request.user, status='OPEN').select_related('session')[:5]
    return render(request, 'attendance/student_dashboard.html', {
        'enrollments': enrollments,
        'active_sessions': active_sessions,
        'present_count': present_count,
        'total_closed': total_closed,
        'percentage': percentage,
        'history': history,
        'total_records': total_records.count(),
        'open_attempts': open_attempts,
    })

@login_required
def verify_page(request):
    token = request.GET.get('session') or request.GET.get('token')
    session = None
    if token:
        try:
            session = AttendanceSession.objects.select_related('classroom','subject','teacher').get(token=token)
            session.expire_if_needed()
        except AttendanceSession.DoesNotExist:
            messages.error(request, "Invalid QR session token.")
            session = None
    if not session and request.user.is_student():
        enroll_ids = Enrollment.objects.filter(student=request.user).values_list('classroom_id', flat=True)
        fallback = AttendanceSession.objects.filter(classroom_id__in=enroll_ids, status='OPEN').first()
        if fallback and fallback.is_active():
            session = fallback
    already_present = False
    if session and AttendanceRecord.objects.filter(session=session, student=request.user, status='PRESENT').exists():
        already_present = True
        messages.info(request, "You are already marked PRESENT for this session.")
    not_enrolled = False
    if session and not Enrollment.objects.filter(student=request.user, classroom=session.classroom).exists():
        not_enrolled = True
    open_attempt = None
    if session:
        open_attempt = AttendanceAttempt.objects.filter(student=request.user, session=session, status='OPEN').order_by('-created_at').first()
        if open_attempt and open_attempt.is_stale():
            open_attempt.status = 'INVALID'
            open_attempt.save(update_fields=['status'])
            open_attempt = None
    # Check if location denied for this session/student
    location_denied = False
    if session:
        location_denied = LocationDenial.objects.filter(session=session, student=request.user).exists()
    return render(request, 'attendance/student_verify.html', {
        'session': session,
        'token': token,
        'already_present': already_present,
        'not_enrolled': not_enrolled,
        'open_attempt': open_attempt,
        'is_active': session.is_active() if session else False,
        'is_expired': session.is_expired() if session else False,
        'location_denied': location_denied,
        'debug': settings.DEBUG,
    })

# API: start attempt (now with location)
@login_required
@require_POST
def api_start_attempt(request):
    if not _rate_limit(request, 'start_attempt', limit=20, window=60):
        return JsonResponse({'error': 'Too many attempts. Slow down.'}, status=429)
    # Validate token length to prevent abuse
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict()
    except Exception as e:
        logger.warning(f"Bad JSON in start_attempt: {e}")
        data = request.POST
    token = data.get('token') or data.get('session')
    if not token or not isinstance(token, str) or len(token) > 200:
        return JsonResponse({'error': 'token required'}, status=400)
    # Sanitize token: allow only base64-url chars and URL
    if len(token) > 200:
        return JsonResponse({'error': 'token too long'}, status=400)
    try:
        session = AttendanceSession.objects.get(token=token)
    except AttendanceSession.DoesNotExist:
        return JsonResponse({'error': 'Invalid session token'}, status=404)
    session.expire_if_needed()
    if session.is_closed():
        return JsonResponse({'error': 'Session is closed'}, status=400)
    if session.is_expired():
        return JsonResponse({'error': 'QR expired. Please ask teacher to use manual attendance.'}, status=400)
    if not Enrollment.objects.filter(student=request.user, classroom=session.classroom).exists():
        return JsonResponse({'error': 'You are not enrolled in this class'}, status=403)
    if AttendanceRecord.objects.filter(session=session, student=request.user, status='PRESENT').exists():
        return JsonResponse({'error': 'Already marked present', 'already_present': True}, status=409)
    # LOCATION REQUIRED CHECK — with accuracy
    lat = data.get('latitude') or data.get('lat') or data.get('student_latitude')
    lng = data.get('longitude') or data.get('lng') or data.get('student_longitude')
    acc_raw = data.get('accuracy') or data.get('acc') or data.get('student_accuracy')
    try:
        acc = float(acc_raw) if acc_raw is not None else None
        if acc is not None and (acc<=0 or acc>10000): acc=None
    except:
        acc=None
    if lat is None or lng is None:
        return JsonResponse({'error': 'Location is required. Please enable location services. Frozen until enabled.', 'location_required': True}, status=400)
    try:
        lat = float(lat); lng = float(lng)
    except:
        return JsonResponse({'error': 'Invalid location coordinates'}, status=400)
    # Check teacher location set
    if not session.has_teacher_location():
        return JsonResponse({'error': "Teacher location not set yet. Ask teacher to enable 'Capture My Location' on their device.", 'teacher_location_missing': True}, status=400)
    # Distance check (fail early if too far)
    dist = haversine_meters(lat, lng, session.teacher_latitude, session.teacher_longitude)
    if dist is None:
        return JsonResponse({'error': 'Could not compute distance'}, status=400)
    if dist > session.allowed_radius_meters:
        # Log? Not denial, but out of range — still allow attempt but will fail at complete
        # For now, allow but warn; final check will enforce
        pass
    # Invalidate stale
    stale = AttendanceAttempt.objects.filter(student=request.user, session=session, status='OPEN')
    for att in stale:
        if att.is_stale():
            att.status = 'INVALID'
            att.save(update_fields=['status'])
    existing_open = AttendanceAttempt.objects.filter(student=request.user, session=session, status='OPEN').first()
    if existing_open:
        return JsonResponse({'error': 'Verification already in progress', 'attempt_id': existing_open.id, 'already_open': True}, status=409)
    last = AttendanceAttempt.objects.filter(student=request.user, session=session).order_by('-attempt_number').first()
    next_num = (last.attempt_number + 1) if last else 1
    # Store accuracy for debugging 21m issue
    try:
        attempt = AttendanceAttempt.objects.create(
            student=request.user,
            session=session,
            attempt_number=next_num,
            status='OPEN',
            last_heartbeat=timezone.now(),
            student_latitude=lat,
            student_longitude=lng,
            student_location_accuracy=acc,
            distance_meters=dist,
            location_verified=(dist <= session.allowed_radius_meters),
        )
    except Exception as e:
        # Fallback if migration not yet applied
        attempt = AttendanceAttempt.objects.create(
            student=request.user,
            session=session,
            attempt_number=next_num,
            status='OPEN',
            last_heartbeat=timezone.now(),
            student_latitude=lat,
            student_longitude=lng,
            distance_meters=dist,
            location_verified=(dist <= session.allowed_radius_meters),
        )
    # If far, we already store distance; client will show warning
    # Remove any previous denial since now they provided location
    LocationDenial.objects.filter(session=session, student=request.user).delete()
    return JsonResponse({'success': True, 'attempt_id': attempt.id, 'attempt_number': attempt.attempt_number, 'expires_at': session.expires_at.isoformat(), 'distance': dist, 'location_verified': attempt.location_verified, 'face_required': session.face_verification_enabled})

@login_required
@require_POST
def api_scan(request, attempt_id):
    if not _rate_limit(request, 'scan', limit=30, window=60):
        return JsonResponse({'error': 'Too many scans.'}, status=429)
    attempt = get_object_or_404(AttendanceAttempt, id=attempt_id, student=request.user)
    if attempt.status != 'OPEN':
        return JsonResponse({'error': f'Attempt is {attempt.status}, not OPEN'}, status=400)
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict()
    except:
        data = request.POST
    token = data.get('token') or data.get('session')
    if not token:
        return JsonResponse({'error': 'token required'}, status=400)
    session = attempt.session
    session.expire_if_needed()
    if token != session.token:
        if 'session=' in token:
            import urllib.parse as up
            parsed = up.urlparse(token)
            qs = up.parse_qs(parsed.query)
            extracted = qs.get('session', [None])[0]
            if extracted != session.token:
                return JsonResponse({'error': 'Invalid QR token for this session'}, status=400)
        else:
            return JsonResponse({'error': 'Invalid QR token'}, status=400)
    if session.is_expired():
        return JsonResponse({'error': 'QR has expired'}, status=400)
    if not Enrollment.objects.filter(student=request.user, classroom=session.classroom).exists():
        return JsonResponse({'error': 'Not enrolled'}, status=403)
    if AttendanceRecord.objects.filter(session=session, student=request.user, status='PRESENT').exists():
        attempt.status = 'INVALID'
        attempt.save(update_fields=['status'])
        return JsonResponse({'error': 'Already marked present'}, status=409)
    # Optional: update location if provided again (with accuracy)
    lat = data.get('latitude') or data.get('lat')
    lng = data.get('longitude') or data.get('lng')
    acc = data.get('accuracy') or data.get('acc')
    if lat is not None and lng is not None:
        try:
            lat = float(lat); lng = float(lng)
            try:
                acc_f=float(acc) if acc is not None else None
                if acc_f and (acc_f<=0 or acc_f>10000): acc_f=None
            except: acc_f=None
            dist = haversine_meters(lat, lng, session.teacher_latitude, session.teacher_longitude)
            attempt.student_latitude = lat
            attempt.student_longitude = lng
            if hasattr(attempt, 'student_location_accuracy'):
                attempt.student_location_accuracy = acc_f
            attempt.distance_meters = dist
            attempt.location_verified = (dist is not None and dist <= session.allowed_radius_meters)
            try:
                attempt.save(update_fields=['student_latitude','student_longitude','student_location_accuracy','distance_meters','location_verified'])
            except:
                attempt.save(update_fields=['student_latitude','student_longitude','distance_meters','location_verified'])
        except:
            pass
    attempt.scan_verified_at = timezone.now()
    attempt.last_heartbeat = timezone.now()
    attempt.save(update_fields=['scan_verified_at', 'last_heartbeat'])
    return JsonResponse({'success': True, 'message': 'QR verified. Completing active verification...', 'scan_verified_at': attempt.scan_verified_at.isoformat(), 'location_verified': attempt.location_verified, 'distance': attempt.distance_meters})

@login_required
@require_POST
def api_heartbeat(request, attempt_id):
    if not _rate_limit(request, 'heartbeat', limit=60, window=60):
        return JsonResponse({'error': 'Heartbeat throttled'}, status=429)
    attempt = get_object_or_404(AttendanceAttempt, id=attempt_id, student=request.user)
    if attempt.status != 'OPEN':
        return JsonResponse({'error': f'Attempt is {attempt.status}'}, status=400)
    attempt.last_heartbeat = timezone.now()
    attempt.save(update_fields=['last_heartbeat'])
    return JsonResponse({'success': True, 'last_heartbeat': attempt.last_heartbeat.isoformat()})

@login_required
@require_POST
def api_invalidate(request, attempt_id):
    attempt = get_object_or_404(AttendanceAttempt, id=attempt_id, student=request.user)
    if attempt.status == 'OPEN':
        attempt.status = 'INVALID'
        attempt.save(update_fields=['status'])
        return JsonResponse({'success': True, 'status': 'INVALID'})
    return JsonResponse({'success': False, 'status': attempt.status})

@login_required
@require_POST
def api_face_verify(request, attempt_id):
    """Student uploads face snapshot; server marks face_verified if image provided and session requires it.
    Teacher's camera is also involved: teacher must have face_verification_enabled toggle.
    For prototype, detection is client-side; server just stores image and marks verified if non-empty.
    Teacher can later manually approve via dashboard if needed.
    """
    if not _rate_limit(request, 'face', limit=10, window=60):
        return JsonResponse({'error': 'Too many face attempts'}, status=429)
    attempt = get_object_or_404(AttendanceAttempt, id=attempt_id, student=request.user)
    if attempt.status != 'OPEN':
        return JsonResponse({'error': f'Attempt is {attempt.status}'}, status=400)
    if not attempt.session.face_verification_enabled:
        return JsonResponse({'success': True, 'message': 'Face verification disabled for this session — skipped', 'face_verified': True})
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict()
    except:
        data = request.POST
    image = data.get('face_image') or data.get('image')
    if not image:
        return JsonResponse({'error': 'face_image required'}, status=400)
    # Basic validation: must be base64 data URL, JPEG/PNG only, size limit 250KB string
    if not isinstance(image, str) or not image.startswith('data:image/'):
        return JsonResponse({'error': 'Invalid face_image format'}, status=400)
    if not (image.startswith('data:image/jpeg') or image.startswith('data:image/png') or image.startswith('data:image/jpg')):
        return JsonResponse({'error': 'Only JPEG/PNG face images allowed'}, status=400)
    if len(image) > 300000:
        return JsonResponse({'error': 'Face image too large (max 300KB)'}, status=400)
    if ';base64,' not in image:
        return JsonResponse({'error': 'Invalid base64 image'}, status=400)
    # For prototype, we trust client face detection already passed; store and mark verified
    attempt.face_image = image[:200000]  # truncate to avoid huge DB
    attempt.face_verified = True
    attempt.save(update_fields=['face_image','face_verified'])
    # Notify teacher via channel
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer=get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(f"attendance_{attempt.session.id}", {"type":"attendance.update","data":{"type":"face_captured","student": attempt.student.username, "attempt_id": attempt.id}})
    except: pass
    return JsonResponse({'success': True, 'face_verified': True})

@login_required
@require_POST
def api_verify_complete(request, attempt_id):
    if not _rate_limit(request, 'complete', limit=10, window=60):
        return JsonResponse({'error': 'Too many completions'}, status=429)
    attempt = get_object_or_404(AttendanceAttempt, id=attempt_id, student=request.user)
    if attempt.status != 'OPEN':
        return JsonResponse({'error': f'Attempt is {attempt.status}'}, status=400)
    if not attempt.scan_verified_at:
        return JsonResponse({'error': 'QR scan not verified yet. Cannot complete verification.'}, status=400)
    session = attempt.session
    if session.is_closed():
        attempt.status = 'INVALID'
        attempt.save(update_fields=['status'])
        return JsonResponse({'error': 'Session is closed'}, status=400)
    if AttendanceRecord.objects.filter(session=session, student=request.user, status='PRESENT').exists():
        attempt.status = 'INVALID'
        attempt.save(update_fields=['status'])
        return JsonResponse({'error': 'Already marked present'}, status=409)
    # LOCATION ENFORCEMENT (must)
    if attempt.student_latitude is None or attempt.student_longitude is None:
        return JsonResponse({'error': 'Location not captured. Enable location to mark attendance.', 'location_required': True}, status=400)
    # Recompute distance with latest teacher location (in case teacher moved)
    dist = haversine_meters(attempt.student_latitude, attempt.student_longitude, session.teacher_latitude, session.teacher_longitude)
    if dist is None:
        return JsonResponse({'error': 'Teacher location not available'}, status=400)
    attempt.distance_meters = dist
    attempt.location_verified = (dist <= session.allowed_radius_meters)
    attempt.save(update_fields=['distance_meters','location_verified'])
    if not attempt.location_verified:
        # Do not mark present; keep attempt OPEN? But spec says cannot be present if outside 50m
        # Mark attempt INVALID? Keep for retry after moving closer
        return JsonResponse({'error': f'You are {dist:.0f}m away from classroom. Must be within {session.allowed_radius_meters}m. Move closer and retry.', 'distance': dist, 'out_of_range': True}, status=400)
    # FACE ENFORCEMENT if enabled — now TEACHER-SIDE only (student does not upload face)
    # Teacher must have captured face via teacher camera (face_verified_by_teacher or face_verified)
    if session.face_verification_enabled and not attempt.face_verified:
        # Check if teacher pre-verified (face_verified_by_teacher) — already covered by face_verified flag
        # If not verified, inform student to wait for teacher in-person check
        return JsonResponse({'error': 'Face verification is ON — please ask teacher to capture your face via TEACHER camera (teacher portal → Face Verification → select your name → Capture). You do not need to do face scan here.', 'face_required': True, 'teacher_side': True}, status=400)
    try:
        with transaction.atomic():
            rec, created = AttendanceRecord.objects.get_or_create(
                session=session, student=request.user,
                defaults={'status': 'PRESENT', 'method': 'QR', 'student_latitude': attempt.student_latitude, 'student_longitude': attempt.student_longitude, 'distance_meters': dist, 'face_verified': attempt.face_verified}
            )
            if not created:
                attempt.status = 'INVALID'
                attempt.save(update_fields=['status'])
                return JsonResponse({'error': 'Already marked present (race)'}, status=409)
            attempt.status = 'SUCCESS'
            attempt.save(update_fields=['status'])
            # Remove denial if was there
            LocationDenial.objects.filter(session=session, student=request.user).delete()
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                layer = get_channel_layer()
                if layer:
                    async_to_sync(layer.group_send)(f"attendance_{session.id}", {
                        "type": "attendance.update",
                        "data": {
                            "type": "attendance_update",
                            "present_count": session.get_present_count(),
                            "student": request.user.username,
                            "roll": request.user.roll_number or '',
                            "method": "QR",
                            "distance": dist,
                            "face": attempt.face_verified,
                            "time": rec.marked_at.strftime('%H:%M:%S')
                        }
                    })
            except: pass
            return JsonResponse({'success': True, 'status': 'SUCCESS', 'message': 'Attendance marked PRESENT', 'record_id': rec.id, 'distance': dist})
    except IntegrityError:
        attempt.status = 'INVALID'
        attempt.save(update_fields=['status'])
        return JsonResponse({'error': 'Race condition prevented duplicate'}, status=409)

@login_required
@require_POST
def api_location_denied(request):
    """Student reports location denied — frozen until enabled; teacher gets list."""
    if not _rate_limit(request, 'denied', limit=10, window=60):
        return JsonResponse({'error': 'Too many denials'}, status=429)
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict()
    except:
        data = request.POST
    token = data.get('token') or data.get('session')
    reason = data.get('reason', 'denied')
    if not token:
        return JsonResponse({'error': 'token required'}, status=400)
    try:
        session = AttendanceSession.objects.get(token=token)
    except AttendanceSession.DoesNotExist:
        return JsonResponse({'error': 'Invalid session token'}, status=404)
    # enrollment check not strictly needed but we log anyway
    # Create or update denial
    obj, created = LocationDenial.objects.get_or_create(session=session, student=request.user, defaults={'reason': reason})
    if not created:
        obj.reason = reason
        obj.save(update_fields=['reason'])
    # Notify teacher
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer=get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(f"attendance_{session.id}", {"type":"attendance.update","data":{"type":"location_denied","student": request.user.username, "roll": request.user.roll_number or '', "reason": reason}})
    except: pass
    return JsonResponse({'success': True, 'message': 'Location denial recorded — teacher notified. Enable location to proceed.'})

# History & Analytics remain same but include location/face

@login_required
@teacher_required
def teacher_history(request):
    sessions = AttendanceSession.objects.filter(teacher=request.user).select_related('classroom','subject').order_by('-created_at')
    class_filter = request.GET.get('class')
    subject_filter = request.GET.get('subject')
    date_filter = request.GET.get('date')
    status_filter = request.GET.get('status')
    if class_filter:
        sessions = sessions.filter(classroom__code=class_filter)
    if subject_filter:
        sessions = sessions.filter(subject__code=subject_filter)
    if date_filter:
        try:
            sessions = sessions.filter(created_at__date=date_filter)
        except: pass
    records = AttendanceRecord.objects.filter(session__teacher=request.user).select_related('student','session','session__classroom','session__subject').order_by('-marked_at')
    if class_filter:
        records = records.filter(session__classroom__code=class_filter)
    if subject_filter:
        records = records.filter(session__subject__code=subject_filter)
    if date_filter:
        try:
            records = records.filter(session__created_at__date=date_filter)
        except: pass
    if status_filter:
        records = records.filter(status=status_filter)
    if request.GET.get('method'):
        records = records.filter(method=request.GET.get('method'))
    # Pagination for records (prevent huge load)
    paginator = Paginator(records, 50)
    page_num = request.GET.get('page')
    records_page = paginator.get_page(page_num)
    classes = ClassRoom.objects.filter(teacher=request.user).order_by('code')
    subjects = Subject.objects.all().order_by('code')
    # sessions limited to 50 most recent for sidebar
    return render(request, 'attendance/teacher_history.html', {
        'sessions': sessions[:50],
        'records': records_page,
        'paginator': paginator,
        'page_obj': records_page,
        'classes': classes,
        'subjects': subjects,
    })

@login_required
def student_history(request):
    if request.user.is_teacher():
        return redirect('attendance:teacher_history')
    records_qs = AttendanceRecord.objects.filter(student=request.user).select_related('session','session__classroom','session__subject').order_by('-marked_at')
    paginator = Paginator(records_qs, 50)
    page_num = request.GET.get('page')
    records_page = paginator.get_page(page_num)
    return render(request, 'attendance/student_history.html', {'records': records_page, 'paginator': paginator, 'page_obj': records_page})

@login_required
@teacher_required
def analytics_view(request):
    teacher = request.user
    classrooms = ClassRoom.objects.filter(teacher=teacher)
    selected_class = request.GET.get('class')
    sessions = AttendanceSession.objects.filter(teacher=teacher, status='CLOSED')
    if selected_class:
        sessions = sessions.filter(classroom__code=selected_class)
    total_finalized = sessions.count()
    total_enrolled = Enrollment.objects.filter(classroom__teacher=teacher).values('student').distinct().count()
    if selected_class:
        try:
            cr = ClassRoom.objects.get(code=selected_class, teacher=teacher)
            total_enrolled = cr.enrollments.count()
        except: pass
    records = AttendanceRecord.objects.filter(session__in=sessions)
    present_total = records.filter(status='PRESENT').count()
    absent_total = records.filter(status='ABSENT').count()
    overall_pct = round(present_total / (present_total+absent_total)*100, 1) if (present_total+absent_total)>0 else 0
    if selected_class:
        enrollments = Enrollment.objects.filter(classroom__code=selected_class, classroom__teacher=teacher).select_related('student')
    else:
        seen = set()
        uniq = []
        for e in Enrollment.objects.filter(classroom__teacher=teacher).select_related('student'):
            if e.student_id not in seen:
                seen.add(e.student_id)
                uniq.append(e)
        enrollments = uniq
    threshold = 75
    try:
        threshold = int(request.GET.get('threshold', 75))
    except: threshold = 75
    low_attendance = []
    student_stats=[]
    for e in enrollments:
        s = e.student
        student_class_ids = Enrollment.objects.filter(student=s).values_list('classroom_id', flat=True)
        student_sessions = sessions.filter(classroom_id__in=student_class_ids)
        total_for_student = student_sessions.count()
        present_for_student = AttendanceRecord.objects.filter(student=s, session__in=student_sessions, status='PRESENT').count()
        pct = round(present_for_student/total_for_student*100,1) if total_for_student>0 else 0
        stat = {
            'student': s,
            'roll': e.roll_number or s.roll_number or '-',
            'classroom': e.classroom.code if hasattr(e, 'classroom') else '-',
            'total': total_for_student,
            'present': present_for_student,
            'absent': total_for_student - present_for_student,
            'pct': pct,
            'is_low': pct < threshold,
        }
        student_stats.append(stat)
        if pct < threshold:
            low_attendance.append(stat)
    student_stats.sort(key=lambda x: x['pct'])
    avg_pct = round(sum(s['pct'] for s in student_stats)/len(student_stats),1) if student_stats else 0
    return render(request, 'attendance/analytics.html', {
        'classrooms': classrooms,
        'selected_class': selected_class,
        'total_finalized': total_finalized,
        'total_enrolled': total_enrolled,
        'present_total': present_total,
        'absent_total': absent_total,
        'overall_pct': overall_pct,
        'avg_pct': avg_pct,
        'student_stats': student_stats,
        'low_attendance': low_attendance,
        'threshold': threshold,
    })

@login_required
@teacher_required
def export_csv(request):
    records = AttendanceRecord.objects.filter(session__teacher=request.user).select_related('student','session','session__classroom','session__subject').order_by('-marked_at')
    class_filter = request.GET.get('class')
    subject_filter = request.GET.get('subject')
    date_filter = request.GET.get('date')
    status_filter = request.GET.get('status')
    if class_filter:
        records = records.filter(session__classroom__code=class_filter)
    if subject_filter:
        records = records.filter(session__subject__code=subject_filter)
    if date_filter:
        records = records.filter(session__created_at__date=date_filter)
    if status_filter:
        records = records.filter(status=status_filter)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="attendance_{timezone.now().date()}.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Student', 'Roll Number', 'Class', 'Subject', 'Date', 'Status', 'Method', 'Time', 'Distance(m)', 'Face', 'Session ID'])
    for r in records:
        writer.writerow([
            r.student.username,
            r.student.roll_number or r.student.username,
            r.session.classroom.code,
            r.session.subject.name,
            r.session.created_at.strftime('%Y-%m-%d'),
            r.status,
            r.method,
            r.marked_at.strftime('%H:%M:%S'),
            f"{r.distance_meters:.0f}" if r.distance_meters is not None else "",
            "Yes" if r.face_verified else "No",
            str(r.session.id)
        ])
    return response

@login_required
def scan_redirect(request):
    token = request.GET.get('session')
    if not token:
        messages.error(request, "No session token provided in QR.")
        return redirect('dashboard')
    if not request.user.is_authenticated:
        login_url = f"{settings.LOGIN_URL}?session={token}&next=/attendance/verify/?session={token}"
        return redirect(login_url)
    return redirect(f"/attendance/verify/?session={token}")
