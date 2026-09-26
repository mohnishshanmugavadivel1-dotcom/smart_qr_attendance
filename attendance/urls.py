from django.urls import path
from . import views

app_name = 'attendance'

urlpatterns = [
    path('teacher/', views.teacher_dashboard, name='teacher_dashboard'),
    path('teacher/history/', views.teacher_history, name='teacher_history'),
    path('teacher/analytics/', views.analytics_view, name='analytics'),
    path('teacher/export/', views.export_csv, name='export_csv'),
    
    path('student/', views.student_dashboard, name='student_dashboard'),
    path('student/history/', views.student_history, name='student_history'),
    
    path('session/create/', views.create_session, name='create_session'),
    path('session/<uuid:session_id>/', views.teacher_session_view, name='teacher_session'),
    path('session/<uuid:session_id>/status/', views.session_status_api, name='session_status'),
    path('session/<uuid:session_id>/manual/', views.manual_mark, name='manual_mark'),
    path('session/<uuid:session_id>/finalize/', views.finalize_session, name='finalize_session'),
    path('session/<uuid:session_id>/teacher-location/', views.api_update_teacher_location, name='teacher_location'),
    path('session/<uuid:session_id>/toggle-face/', views.api_toggle_face, name='toggle_face'),
    path('session/<uuid:session_id>/teacher-verify-face/', views.api_teacher_verify_face, name='teacher_verify_face'),
    
    path('verify/', views.verify_page, name='verify_page'),
    path('scan/', views.scan_redirect, name='scan_redirect'),
    
    path('api/attempt/start/', views.api_start_attempt, name='api_start_attempt'),
    path('api/attempt/<int:attempt_id>/scan/', views.api_scan, name='api_scan'),
    path('api/attempt/<int:attempt_id>/heartbeat/', views.api_heartbeat, name='api_heartbeat'),
    path('api/attempt/<int:attempt_id>/invalidate/', views.api_invalidate, name='api_invalidate'),
    path('api/attempt/<int:attempt_id>/face/', views.api_face_verify, name='api_face_verify'),
    path('api/attempt/<int:attempt_id>/complete/', views.api_verify_complete, name='api_complete'),
    path('api/location-denied/', views.api_location_denied, name='api_location_denied'),
]
