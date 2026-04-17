"""
Management command: import the real Sensore CSV file
de0e9b2c_20251013.csv into the database.

Usage:
    python manage.py import_real_csv

The file must be present at sample_data/de0e9b2c_20251013.csv
(relative to BASE_DIR).  It is bundled with the project.

What this command does:
  1. Creates a patient user 'de0e9b2c' if they don't exist.
  2. Creates a SensorSession dated 2025-10-13.
  3. Parses the CSV (Format A: 32 rows x 32 cols per frame).
  4. Normalises values from the 0-705 hardware scale to 1-4095.
  5. Bulk-creates all 4,190 SensorFrame records.
  6. Runs full pressure analysis (PPI, Contact Area, Risk Score,
     Plain-English explanation) on every frame.
  7. Auto-generates PressureAlerts for high/critical frames.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

if __name__ == '__main__':
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore_project.settings')
    import django
    django.setup()

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import UserProfile
from sensore.models import SensorFrame, SensorSession
from sensore.utils import (analyse_frame, generate_session_alerts,
                           normalise_frame, parse_frame_data)

CSV_FILENAME = 'de0e9b2c_20251013.csv'
PATIENT_USERNAME = 'de0e9b2c'
SESSION_DATE = date(2025, 10, 13)


def _parse_csv(path):
    """Parse the CSV and return a list of normalised 1024-int frames."""
    import csv as _csv

    rows = []
    with open(path, newline='') as f:
        reader = _csv.reader(f)
        for row in reader:
            if not row or row[0].strip().startswith('#'):
                continue
            try:
                vals = [int(float(v)) for v in row if v.strip()]
                if vals:
                    rows.append(vals)
            except ValueError:
                continue

    # Pass 1: assemble raw frames
    frames_raw = []
    i = 0
    while i + 32 <= len(rows):
        flat = []
        for r in rows[i:i + 32]:
            flat.extend(r[:32])
        if len(flat) == 1024:
            frames_raw.append(flat)
        i += 32

    if not frames_raw:
        return []

    # Pass 2: find global max across ALL frames, then normalise consistently
    # so relative pressures between frames are preserved.
    global_max = max(max(f) for f in frames_raw)
    return [normalise_frame(f, global_max=global_max) for f in frames_raw]


class Command(BaseCommand):
    help = 'Import de0e9b2c_20251013.csv (real Sensore hardware data) into the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            default=None,
            help='Path to the CSV file (default: sample_data/de0e9b2c_20251013.csv inside BASE_DIR)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=200,
            help='How many frames to analyse per progress update (default: 200)',
        )
        parser.add_argument(
            '--max-frames',
            type=int,
            default=None,
            help='Limit the number of frames imported (default: all 4190)',
        )

    def handle(self, *args, **options):
        csv_path = options['path'] or os.path.join(
            settings.BASE_DIR, 'sample_data', CSV_FILENAME
        )

        if not os.path.exists(csv_path):
            self.stderr.write(
                f'CSV file not found: {csv_path}\n'
                f'Place the file at that path and re-run.'
            )
            return

        self.stdout.write(f'Reading {csv_path} …')
        frames_data = _parse_csv(csv_path)

        if not frames_data:
            self.stderr.write('No frames parsed — check CSV format.')
            return

        max_frames = options['max_frames']
        if max_frames:
            frames_data = frames_data[:max_frames]

        self.stdout.write(f'  Parsed {len(frames_data)} frames (normalised to 1-4095 scale)')

        # ── Create / fetch clinician ────────────────────────────────────
        clin_user, _ = User.objects.get_or_create(
            username='dr_smith',
            defaults={'first_name': 'Dr. Sarah', 'last_name': 'Smith',
                      'email': 'sarah.smith@hospital.org'}
        )
        clin_user.is_active = True
        clin_user.set_password('clinic123')
        clin_user.save()
        clin_profile, _ = UserProfile.objects.get_or_create(user=clin_user, defaults={'role': 'clinician'})
        if clin_profile.role != 'clinician':
            clin_profile.role = 'clinician'
            clin_profile.save(update_fields=['role'])

        # ── Create / fetch patient ──────────────────────────────────────
        patient, _ = User.objects.get_or_create(
            username=PATIENT_USERNAME,
            defaults={
                'first_name': 'Sensor',
                'last_name':  'Patient DE0E',
                'email':      f'{PATIENT_USERNAME}@sensore.device',
            }
        )
        patient.is_active = True
        patient.set_password('patient123')
        patient.save()
        patient_profile, _ = UserProfile.objects.get_or_create(user=patient, defaults={
            'role':                 'patient',
            'patient_id':           PATIENT_USERNAME.upper(),
            'assigned_clinician':   clin_user,
            'date_of_birth':        date(1970, 1, 1),
            'medical_notes':        f'Real hardware session imported from {CSV_FILENAME}',
        })
        profile_updates = []
        if patient_profile.role != 'patient':
            patient_profile.role = 'patient'
            profile_updates.append('role')
        if patient_profile.patient_id != PATIENT_USERNAME.upper():
            patient_profile.patient_id = PATIENT_USERNAME.upper()
            profile_updates.append('patient_id')
        if patient_profile.assigned_clinician_id != clin_user.id:
            patient_profile.assigned_clinician = clin_user
            profile_updates.append('assigned_clinician')
        if patient_profile.date_of_birth is None:
            patient_profile.date_of_birth = date(1970, 1, 1)
            profile_updates.append('date_of_birth')
        expected_notes = f'Real hardware session imported from {CSV_FILENAME}'
        if not patient_profile.medical_notes:
            patient_profile.medical_notes = expected_notes
            profile_updates.append('medical_notes')
        if profile_updates:
            patient_profile.save(update_fields=profile_updates)
        self.stdout.write(f'  Patient user: {PATIENT_USERNAME}  (password: patient123)')

        # ── Create session ──────────────────────────────────────────────
        start_dt = timezone.make_aware(
            datetime(SESSION_DATE.year, SESSION_DATE.month, SESSION_DATE.day, 0, 0, 0)
        )
        # Duration: frames × 30 s
        total_seconds = len(frames_data) * 30
        end_dt = start_dt + timedelta(seconds=total_seconds)

        session, created = SensorSession.objects.get_or_create(
            patient=patient,
            session_date=SESSION_DATE,
            defaults={
                'start_time': start_dt,
                'end_time':   end_dt,
                'notes': (
                    f'Real Sensore hardware session — {len(frames_data)} frames, '
                    f'~{total_seconds // 60} minutes.  '
                    f'Sensor ID: {PATIENT_USERNAME}.  '
                    'Values normalised from 0-705 hardware scale to 1-4095.'
                ),
            }
        )

        if not created and session.frames.exists():
            self.stdout.write(
                self.style.WARNING(
                    f'Session already exists for {PATIENT_USERNAME} on {SESSION_DATE} '
                    f'({session.frames.count()} frames).  '
                    'Delete it first or use --max-frames 0 to skip.'
                )
            )
            return

        # ── Bulk-create frames ──────────────────────────────────────────
        self.stdout.write('  Inserting frames …')
        frame_objs = []
        for idx, flat in enumerate(frames_data):
            total_s = idx * 30
            frame_time = start_dt + timedelta(seconds=total_s)
            frame_objs.append(SensorFrame(
                session=session,
                timestamp=frame_time,
                frame_index=idx,
                data=json.dumps(flat),
            ))

        SensorFrame.objects.bulk_create(frame_objs, batch_size=500)
        self.stdout.write(f'  Inserted {len(frame_objs)} SensorFrame records')

        # ── Analyse every frame ─────────────────────────────────────────
        self.stdout.write('  Running pressure analysis (this may take a minute) …')
        batch = options['batch_size']
        all_frames = list(session.frames.order_by('frame_index'))
        high_risk = 0
        sustained_streak = 0
        previous_matrix = None

        for i, frame in enumerate(all_frames):
            try:
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

                if metrics.risk_level in ('high', 'critical'):
                    high_risk += 1

            except Exception as e:
                self.stderr.write(f'  Frame {i} analysis error: {e}')

            if (i + 1) % batch == 0:
                pct = (i + 1) / len(all_frames) * 100
                self.stdout.write(f'    … {i+1}/{len(all_frames)} frames ({pct:.0f}%)')

        alerts_created = generate_session_alerts(session, recreate_unacknowledged=True)

        # ── Done ────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS(
            f'\n✅  Import complete!\n'
            f'    Patient:       {PATIENT_USERNAME}  (password: patient123)\n'
            f'    Session date:  {SESSION_DATE}\n'
            f'    Frames:        {len(all_frames)}\n'
            f'    Duration:      ~{len(all_frames) * 30 // 60} minutes\n'
            f'    High-risk frames: {high_risk}\n'
            f'    Alerts created:   {alerts_created}\n'
        ))
        self.stdout.write(
            'Log in as de0e9b2c / patient123 at http://127.0.0.1:8000'
        )


if __name__ == '__main__':
    import os
    import sys

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore_project.settings')
    from django.core.management import execute_from_command_line

    execute_from_command_line([sys.argv[0], 'import_real_csv', *sys.argv[1:]])
