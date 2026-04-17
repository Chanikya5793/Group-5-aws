"""
Management command to populate the database with realistic sample sensor data.
Creates 5 patients, 1 clinician, 1 admin, with 3 sessions each.
"""
import json
import math
import os
import random
import sys
from datetime import date, datetime, timedelta

if __name__ == '__main__':
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore_project.settings')
    import django
    django.setup()

import numpy as np
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import UserProfile
from sensore.models import SensorFrame, SensorSession
from sensore.utils import (analyse_frame, generate_session_alerts,
                           parse_frame_data)


class Command(BaseCommand):
    help = 'Load sample Sensore pressure data for 5 patients'

    def handle(self, *args, **kwargs):
        self.stdout.write("Creating users...")

        # Admin
        admin_user, _ = User.objects.get_or_create(username='admin',
            defaults={'first_name': 'System', 'last_name': 'Admin', 'is_staff': True, 'is_superuser': True})
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.is_active = True
        admin_user.set_password('admin123')
        admin_user.save()
        admin_profile, _ = UserProfile.objects.get_or_create(user=admin_user, defaults={'role': 'admin'})
        if admin_profile.role != 'admin':
            admin_profile.role = 'admin'
            admin_profile.save(update_fields=['role'])

        # Clinician
        clin_user, _ = User.objects.get_or_create(username='dr_smith',
            defaults={'first_name': 'Dr. Sarah', 'last_name': 'Smith', 'email': 'sarah.smith@hospital.org'})
        clin_user.is_active = True
        clin_user.set_password('clinic123')
        clin_user.save()
        clin_profile, _ = UserProfile.objects.get_or_create(user=clin_user, defaults={'role': 'clinician'})
        if clin_profile.role != 'clinician':
            clin_profile.role = 'clinician'
            clin_profile.save(update_fields=['role'])

        # Patients
        patient_data = [
            ('patient_001', 'James', 'Wilson', 1960),
            ('patient_002', 'Maria', 'Chen', 1975),
            ('patient_003', 'Robert', 'Taylor', 1982),
            ('patient_004', 'Agnes', 'Okafor', 1958),
            ('patient_005', 'Thomas', 'Brown', 1969),
        ]

        patients = []
        for pid, fn, ln, birth_year in patient_data:
            dob = date(birth_year, random.randint(1, 12), random.randint(1, 28))
            u, _ = User.objects.get_or_create(username=pid,
                defaults={'first_name': fn, 'last_name': ln, 'email': f'{pid}@sensore.test'})
            u.is_active = True
            u.set_password('patient123')
            u.save()
            profile, _ = UserProfile.objects.get_or_create(user=u, defaults={
                'role': 'patient',
                'patient_id': pid.upper(),
                'assigned_clinician': clin_user,
                'date_of_birth': dob,
            })
            changed_fields = []
            if profile.role != 'patient':
                profile.role = 'patient'
                changed_fields.append('role')
            if profile.patient_id != pid.upper():
                profile.patient_id = pid.upper()
                changed_fields.append('patient_id')
            if profile.assigned_clinician_id != clin_user.id:
                profile.assigned_clinician = clin_user
                changed_fields.append('assigned_clinician')
            if profile.date_of_birth is None:
                profile.date_of_birth = dob
                changed_fields.append('date_of_birth')
            if changed_fields:
                profile.save(update_fields=changed_fields)
            patients.append(u)
            self.stdout.write(f"  Created patient: {u.get_full_name()} ({pid})")

        # Sessions: 3 per patient, different days
        for patient in patients:
            for day_offset in [0, 1, 2]:
                session_date = date.today() - timedelta(days=day_offset * 3)
                start_dt = timezone.make_aware(
                    datetime(session_date.year, session_date.month, session_date.day, 9, 0, 0)
                )
                end_dt = start_dt + timedelta(hours=2)

                session, created = SensorSession.objects.get_or_create(
                    patient=patient,
                    session_date=session_date,
                    defaults={'start_time': start_dt, 'end_time': end_dt}
                )
                if not created and session.frames.exists():
                    continue

                self.stdout.write(f"  Generating session for {patient.username} on {session_date}...")
                self._generate_frames(session, start_dt, num_frames=60)

        self.stdout.write(self.style.SUCCESS("\n✅ Sample data loaded successfully!"))
        self.stdout.write("\nLogin credentials:")
        self.stdout.write("  Admin:     admin / admin123")
        self.stdout.write("  Clinician: dr_smith / clinic123")
        self.stdout.write("  Patients:  patient_001 to patient_005 / patient123")

    def _generate_frames(self, session, start_time, num_frames=60):
        """Generate realistic 32x32 pressure frames for a session."""
        # Simulate a person sitting: two pressure zones (buttocks) with variation
        base_frame = self._generate_sitting_pattern()
        frames_to_create = []

        for i in range(num_frames):
            frame_time = start_time + timedelta(seconds=i * 30)

            # Add temporal variation: occasional shifts, high pressure events
            variation = random.uniform(0.7, 1.3)
            if random.random() < 0.1:  # 10% chance of repositioning
                variation = random.uniform(0.2, 0.5)
            if random.random() < 0.05:  # 5% chance of high pressure event
                variation = random.uniform(1.5, 2.0)

            frame_data = self._vary_frame(base_frame, variation)
            flat = frame_data.flatten().tolist()
            flat = [max(1, min(4095, int(v))) for v in flat]

            frame = SensorFrame(
                session=session,
                timestamp=frame_time,
                frame_index=i,
                data=json.dumps(flat),
            )
            frames_to_create.append(frame)

        SensorFrame.objects.bulk_create(frames_to_create, ignore_conflicts=True)

        # Run sequential analysis so movement and sustained-load metrics are accurate.
        sustained_streak = 0
        previous_matrix = None
        for frame in session.frames.order_by('frame_index'):
            metrics = analyse_frame(
                frame,
                previous_matrix=previous_matrix,
                sustained_streak=sustained_streak,
            )
            previous_matrix = parse_frame_data(frame.data)
            if metrics.risk_score >= 60 or metrics.peak_pressure_index >= 2800:
                sustained_streak += 1
            else:
                sustained_streak = 0

        generate_session_alerts(session, recreate_unacknowledged=True)

    def _generate_sitting_pattern(self):
        """Generate a base 32x32 sitting pressure pattern (two pressure zones)."""
        grid = np.ones((32, 32), dtype=np.float32)

        # Left buttock centre
        lc_x, lc_y = 10, 18
        # Right buttock centre
        rc_x, rc_y = 22, 18

        for y in range(32):
            for x in range(32):
                # Left zone
                dist_l = math.sqrt((x - lc_x)**2 + (y - lc_y)**2)
                val_l = max(0, 3200 - dist_l * 280)

                # Right zone
                dist_r = math.sqrt((x - rc_x)**2 + (y - rc_y)**2)
                val_r = max(0, 3000 - dist_r * 280)

                # Thigh contact area (low pressure)
                if y < 14:
                    thigh_val = max(0, 800 - abs(x - 16) * 100)
                else:
                    thigh_val = 0

                val = max(val_l, val_r, thigh_val)
                grid[y][x] = max(1, val + random.gauss(0, 50))

        return grid

    def _vary_frame(self, base, variation):
        """Apply variation to a base frame."""
        noise = np.random.normal(0, 80, base.shape)
        varied = base * variation + noise
        # Shift slightly
        shift_x = random.randint(-2, 2)
        shift_y = random.randint(-1, 1)
        if shift_x or shift_y:
            varied = np.roll(varied, shift_x, axis=1)
            varied = np.roll(varied, shift_y, axis=0)
        return np.clip(varied, 1, 4095)


if __name__ == '__main__':
    import os
    import sys

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore_project.settings')
    from django.core.management import execute_from_command_line

    execute_from_command_line([sys.argv[0], 'load_sample_data', *sys.argv[1:]])
