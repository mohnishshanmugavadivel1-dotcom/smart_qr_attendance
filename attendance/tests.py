from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from classroom.models import ClassRoom, Subject, Enrollment
from attendance.models import AttendanceSession, AttendanceAttempt, AttendanceRecord, LocationDenial
import json

User = get_user_model()

class AttendanceCoreTest(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='t1', password='pass12345', role='teacher', email='t1@example.com')
        self.student = User.objects.create_user(username='s1', password='pass12345', role='student', roll_number='R001', email='s1@example.com')
        self.student2 = User.objects.create_user(username='s2', password='pass12345', role='student', roll_number='R002', email='s2@example.com')
        self.classroom = ClassRoom.objects.create(name='CSE', section='A', code='CSE-A-99', teacher=self.teacher)
        self.subject = Subject.objects.create(name='DS', code='CS999', description='Test')
        Enrollment.objects.create(student=self.student, classroom=self.classroom, roll_number='R001')
        Enrollment.objects.create(student=self.student2, classroom=self.classroom, roll_number='R002')

    def test_teacher_can_create_session(self):
        c = Client()
        c.login(username='t1', password='pass12345')
        r = c.post('/attendance/session/create/', {'classroom': self.classroom.id, 'subject': self.subject.id, 'allowed_radius_meters': '50', 'teacher_latitude': '13.0', 'teacher_longitude': '80.0'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AttendanceSession.objects.filter(teacher=self.teacher).exists())

    def test_student_must_be_enrolled(self):
        outsider = User.objects.create_user(username='outsider', password='pass12345', role='student', email='o@example.com', roll_number='R999')
        c = Client()
        c.login(username='outsider', password='pass12345')
        sess = AttendanceSession.objects.create(teacher=self.teacher, classroom=self.classroom, subject=self.subject, teacher_latitude=13.0, teacher_longitude=80.0)
        r = c.post('/attendance/api/attempt/start/', data=json.dumps({'token': sess.token, 'latitude': 13.0, 'longitude': 80.0}), content_type='application/json')
        self.assertEqual(r.status_code, 403)

    def test_location_required(self):
        c = Client()
        c.login(username='s1', password='pass12345')
        sess = AttendanceSession.objects.create(teacher=self.teacher, classroom=self.classroom, subject=self.subject, teacher_latitude=13.0, teacher_longitude=80.0)
        r = c.post('/attendance/api/attempt/start/', data=json.dumps({'token': sess.token}), content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('location_required', r.json())

    def test_teacher_location_missing_blocks(self):
        c = Client()
        c.login(username='s1', password='pass12345')
        sess = AttendanceSession.objects.create(teacher=self.teacher, classroom=self.classroom, subject=self.subject)  # no teacher loc
        r = c.post('/attendance/api/attempt/start/', data=json.dumps({'token': sess.token, 'latitude': 13.0, 'longitude': 80.0}), content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('teacher_location_missing', r.json())

    def test_geofence_out_of_range(self):
        c = Client()
        c.login(username='s1', password='pass12345')
        sess = AttendanceSession.objects.create(teacher=self.teacher, classroom=self.classroom, subject=self.subject, teacher_latitude=13.0, teacher_longitude=80.0, allowed_radius_meters=50)
        r = c.post('/attendance/api/attempt/start/', data=json.dumps({'token': sess.token, 'latitude': 13.1, 'longitude': 80.1}), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        aid = r.json()['attempt_id']
        c.post(f'/attendance/api/attempt/{aid}/scan/', data=json.dumps({'token': sess.token}), content_type='application/json')
        r = c.post(f'/attendance/api/attempt/{aid}/complete/', content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('out_of_range', r.json())

    def test_face_toggle(self):
        c = Client()
        c.login(username='t1', password='pass12345')
        sess = AttendanceSession.objects.create(teacher=self.teacher, classroom=self.classroom, subject=self.subject, teacher_latitude=13.0, teacher_longitude=80.0, face_verification_enabled=True)
        # student must do face
        c2 = Client()
        c2.login(username='s1', password='pass12345')
        r = c2.post('/attendance/api/attempt/start/', data=json.dumps({'token': sess.token, 'latitude': 13.0, 'longitude': 80.0}), content_type='application/json')
        aid = r.json()['attempt_id']
        c2.post(f'/attendance/api/attempt/{aid}/scan/', data=json.dumps({'token': sess.token}), content_type='application/json')
        r = c2.post(f'/attendance/api/attempt/{aid}/complete/', content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('face_required', r.json())
        # upload face
        fake = "data:image/jpeg;base64,/9j/aaa"
        r = c2.post(f'/attendance/api/attempt/{aid}/face/', data=json.dumps({'face_image': fake}), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        r = c2.post(f'/attendance/api/attempt/{aid}/complete/', content_type='application/json')
        self.assertEqual(r.status_code, 200)
        # toggle off
        c.post(f'/attendance/session/{sess.id}/toggle-face/', data=json.dumps({'enabled': False}), content_type='application/json')
        sess.refresh_from_db()
        self.assertFalse(sess.face_verification_enabled)

    def test_duplicate_prevention(self):
        c = Client()
        c.login(username='s1', password='pass12345')
        sess = AttendanceSession.objects.create(teacher=self.teacher, classroom=self.classroom, subject=self.subject, teacher_latitude=13.0, teacher_longitude=80.0)
        # use new API flow with location
        r = c.post('/attendance/api/attempt/start/', data=json.dumps({'token': sess.token, 'latitude': 13.0, 'longitude': 80.0}), content_type='application/json')
        aid = r.json()['attempt_id']
        c.post(f'/attendance/api/attempt/{aid}/scan/', data=json.dumps({'token': sess.token}), content_type='application/json')
        c.post(f'/attendance/api/attempt/{aid}/complete/', content_type='application/json')
        # second attempt should be blocked already_present
        r = c.post('/attendance/api/attempt/start/', data=json.dumps({'token': sess.token, 'latitude': 13.0, 'longitude': 80.0}), content_type='application/json')
        self.assertEqual(r.status_code, 409)

    def test_location_denial_reported(self):
        c = Client()
        c.login(username='s1', password='pass12345')
        sess = AttendanceSession.objects.create(teacher=self.teacher, classroom=self.classroom, subject=self.subject, teacher_latitude=13.0, teacher_longitude=80.0)
        r = c.post('/attendance/api/location-denied/', data=json.dumps({'token': sess.token, 'reason': 'denied'}), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(LocationDenial.objects.filter(session=sess, student=self.student).exists())
        # teacher sees denial in status
        c2 = Client()
        c2.login(username='t1', password='pass12345')
        r = c2.get(f'/attendance/session/{sess.id}/status/')
        self.assertIn('denials', r.json())
        self.assertEqual(len(r.json()['denials']), 1)

    def test_finalize_marks_absent(self):
        c = Client()
        c.login(username='t1', password='pass12345')
        sess = AttendanceSession.objects.create(teacher=self.teacher, classroom=self.classroom, subject=self.subject, teacher_latitude=13.0, teacher_longitude=80.0)
        # mark one present
        AttendanceRecord.objects.create(session=sess, student=self.student, status='PRESENT', method='QR')
        r = c.post(f'/attendance/session/{sess.id}/finalize/')
        self.assertEqual(r.status_code, 302)
        sess.refresh_from_db()
        self.assertEqual(sess.status, 'CLOSED')
        self.assertTrue(AttendanceRecord.objects.filter(session=sess, student=self.student2, status='ABSENT').exists())
        self.assertTrue(AttendanceRecord.objects.filter(session=sess, student=self.student, status='PRESENT').exists())

    def test_open_redirect_protection(self):
        c = Client()
        r = c.post('/accounts/login/', {'username': 't1', 'password': 'pass12345', 'next': 'https://evil.com'})
        # Should redirect to dashboard not evil
        # login view checks _is_safe_url
        # We test that next with evil is not followed
        # Since we don't login via that exact flow, we just ensure helper works
        from accounts.views import _is_safe_url
        from django.test import RequestFactory
        rf = RequestFactory()
        req = rf.get('/?next=https://evil.com', HTTP_HOST='testserver')
        self.assertFalse(_is_safe_url('https://evil.com', req))
        req2 = rf.get('/?next=/dashboard/', HTTP_HOST='testserver')
        self.assertTrue(_is_safe_url('/dashboard/', req2))

    def test_unauthorized_teacher_session_access(self):
        other_teacher = User.objects.create_user(username='t2', password='pass12345', role='teacher', email='t2@example.com')
        sess = AttendanceSession.objects.create(teacher=self.teacher, classroom=self.classroom, subject=self.subject, teacher_latitude=13.0, teacher_longitude=80.0)
        c = Client()
        c.login(username='t2', password='pass12345')
        r = c.get(f'/attendance/session/{sess.id}/')
        self.assertEqual(r.status_code, 404)
        # student not enrolled cannot access status
        outsider = User.objects.create_user(username='outsider2', password='pass12345', role='student', email='o2@example.com', roll_number='R998')
        c2 = Client()
        c2.login(username='outsider2', password='pass12345')
        r = c2.get(f'/attendance/session/{sess.id}/status/')
        self.assertEqual(r.status_code, 403)
