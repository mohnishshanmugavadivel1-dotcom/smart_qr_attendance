from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from classroom.models import ClassRoom, Subject, Enrollment
from attendance.models import AttendanceSession, AttendanceRecord
from django.utils import timezone

User = get_user_model()

class Command(BaseCommand):
    help = 'Seed demo data for Smart QR Attendance'

    def handle(self, *args, **options):
        self.stdout.write("Seeding demo data...")

        # Teachers
        teacher, created = User.objects.get_or_create(username='teacher01', defaults={
            'email': 'teacher01@example.com',
            'role': 'teacher',
            'is_staff': True,
        })
        if created:
            teacher.set_password('teacher123')
            teacher.save()
            self.stdout.write(self.style.SUCCESS(f"Created teacher01 / teacher123"))
        else:
            teacher.role='teacher'
            teacher.set_password('teacher123')
            teacher.save()
            self.stdout.write(f"Reset teacher01 password to teacher123")

        # Subjects
        subjects_data = [
            ('Data Structures', 'CS201', 'Core DS concepts'),
            ('Operating Systems', 'CS301', 'OS fundamentals'),
            ('Database Systems', 'CS302', 'DBMS'),
            ('Computer Networks', 'CS401', 'Networks'),
        ]
        subjects = []
        for name, code, desc in subjects_data:
            s, _ = Subject.objects.get_or_create(code=code, defaults={'name': name, 'description': desc})
            subjects.append(s)

        # Classroom
        classroom, _ = ClassRoom.objects.get_or_create(code='CSE-A-2025', defaults={
            'name': 'CSE',
            'section': 'A',
            'teacher': teacher,
        })
        # Also create CSE-B
        classroom_b, _ = ClassRoom.objects.get_or_create(code='CSE-B-2025', defaults={
            'name': 'CSE',
            'section': 'B',
            'teacher': teacher,
        })

        # Students
        students_info = [
            ('student01', '22CSE001', 'student01@example.com'),
            ('student02', '22CSE002', 'student02@example.com'),
            ('student03', '22CSE003', 'student03@example.com'),
            ('student04', '22CSE004', 'student04@example.com'),
            ('student05', '22CSE005', 'student05@example.com'),
            ('student06', '22CSE006', 'student06@example.com'),
            ('student07', '22CSE007', 'student07@example.com'),
            ('student08', '22CSE008', 'student08@example.com'),
            ('arjun', '22CSE009', 'arjun@example.com'),
            ('priya', '22CSE010', 'priya@example.com'),
        ]
        students=[]
        for username, roll, email in students_info:
            u, created = User.objects.get_or_create(username=username, defaults={'email': email, 'role':'student', 'roll_number': roll})
            if created:
                u.set_password('student123')
                u.roll_number=roll
                u.save()
                self.stdout.write(f"Created {username} / student123")
            else:
                u.role='student'
                u.roll_number=roll
                u.set_password('student123')
                u.save()
            students.append(u)
            Enrollment.objects.get_or_create(student=u, classroom=classroom, defaults={'roll_number': roll})
            # some also in B
            if username in ['student01','student02']:
                Enrollment.objects.get_or_create(student=u, classroom=classroom_b, defaults={'roll_number': roll})

        # Create a couple of past finalized sessions for analytics demo
        from datetime import timedelta
        for i in range(3):
            # avoid duplicate by checking existing count
            if AttendanceSession.objects.filter(classroom=classroom, subject=subjects[0]).count() >= 3:
                break
            session = AttendanceSession.objects.create(
                teacher=teacher,
                classroom=classroom,
                subject=subjects[i % len(subjects)],
                status='CLOSED',
                expires_at=timezone.now() - timedelta(days=i+1),
                closed_at=timezone.now() - timedelta(days=i+1),
            )
            # mark ~70% present
            import random
            random.seed(i)
            for stu in students[:8]:
                if random.random() < 0.7:
                    AttendanceRecord.objects.get_or_create(session=session, student=stu, defaults={'status':'PRESENT','method':'QR'})
                else:
                    AttendanceRecord.objects.get_or_create(session=session, student=stu, defaults={'status':'ABSENT','method':'MANUAL', 'marked_by': teacher})

        self.stdout.write(self.style.SUCCESS("Demo seed complete!"))
        self.stdout.write("Logins:")
        self.stdout.write("  Teacher: teacher01 / teacher123")
        self.stdout.write("  Students: student01..student08, arjun, priya / student123")
        self.stdout.write(f"  Classes: {classroom.code}, {classroom_b.code}")
        self.stdout.write(f"  Subjects: {', '.join([s.code for s in subjects])}")
