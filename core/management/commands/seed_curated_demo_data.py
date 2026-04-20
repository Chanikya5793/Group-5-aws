import math
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (PREDEFINED_ZONES, ClinicianPatientAssignment,
                         ClinicianProfile, Comment, Feedback,
                         HeatmapAnnotation, PainZoneReport, PatientProfile,
                         PressureFrame, SensorData, User)
from core.views import _build_matrix_from_pressure, _calculate_frame_metrics

PATIENT_NAME_POOL = [
    ("Amara", "Bennett"),
    ("Idris", "Cole"),
    ("Nia", "Farrow"),
    ("Kofi", "Hale"),
    ("Leona", "Ibarra"),
    ("Mateo", "Jensen"),
    ("Priya", "Kapoor"),
    ("Elias", "Navarro"),
    ("Talia", "Okafor"),
    ("Rowan", "Pierce"),
    ("Sana", "Quincy"),
    ("Arjun", "Reyes"),
    ("Mina", "Santos"),
    ("Theo", "Upton"),
    ("Yara", "Voss"),
    ("Ibrahim", "Walker"),
    ("Lina", "Xu"),
    ("Dario", "Young"),
    ("Aisha", "Zane"),
    ("Emil", "Abbott"),
]

COMMENT_TEMPLATES = [
    "Pressure increased after I leaned left for a few minutes.",
    "I shifted posture and discomfort eased shortly after.",
    "This period felt uncomfortable near my lower back.",
    "Wheelchair transfer happened around this reading.",
    "Posture correction helped reduce pressure in the next readings.",
]

FEEDBACK_TEMPLATES = [
    "This pressure trend matches how I felt during the session.",
    "The spike aligns with a transfer movement.",
    "Pressure looked better after posture adjustment.",
    "The readings stayed stable for most of this period.",
]


class Command(BaseCommand):
    help = (
        "Reset noisy generated users and seed a curated demo cohort with unique patient names, "
        "multiple records per patient, and explicit clinician assignment."
    )

    def add_arguments(self, parser):
        parser.add_argument("--patients", type=int, default=10)
        parser.add_argument("--frames-per-patient", type=int, default=18)
        parser.add_argument("--comments-per-patient", type=int, default=3)
        parser.add_argument("--feedback-per-patient", type=int, default=2)
        parser.add_argument("--days-window", type=int, default=14)
        parser.add_argument("--seed", type=int, default=2026)
        parser.add_argument("--patient-password", type=str, default="patient123")
        parser.add_argument("--clinician-username", type=str, default="clinician1")
        parser.add_argument("--clinician-password", type=str, default="clinician123")
        parser.add_argument("--admin-password", type=str, default="admin123")
        parser.add_argument(
            "--keep-existing-generated",
            action="store_true",
            help="Keep existing patient_bulk_/clinician_bulk_/junk/demo generated users.",
        )
        parser.add_argument(
            "--keep-clinician-assignments",
            action="store_true",
            help="Keep existing assignments for the target clinician.",
        )

    def handle(self, *args, **options):
        rng = random.Random(options["seed"])
        now = timezone.now()

        requested_patients = max(1, int(options["patients"]))
        patient_count = max(10, requested_patients)
        if patient_count != requested_patients:
            self.stdout.write(self.style.WARNING("Requested fewer than 10 patients, using 10."))

        frames_per_patient = max(4, int(options["frames_per_patient"]))
        comments_per_patient = max(0, int(options["comments_per_patient"]))
        feedback_per_patient = max(0, int(options["feedback_per_patient"]))
        days_window = max(1, int(options["days_window"]))

        with transaction.atomic():
            admin_user = self._ensure_admin(password=options["admin_password"])
            clinician_user = self._ensure_clinician(
                username=options["clinician_username"],
                password=options["clinician_password"],
            )

            purged_generated_users = []
            if not options["keep_existing_generated"]:
                purged_generated_users = self._purge_generated_users(keep_usernames={admin_user.username, clinician_user.username})

            roster = self._build_roster(patient_count)
            patients = self._ensure_patients(
                roster=roster,
                password=options["patient_password"],
            )

            cleared_assignments = 0
            if not options["keep_clinician_assignments"]:
                cleared_assignments, _ = ClinicianPatientAssignment.objects.filter(clinician=clinician_user).delete()

            # Ensure a single deterministic assignment source for this curated cohort.
            ClinicianPatientAssignment.objects.filter(patient__in=patients).exclude(clinician=clinician_user).delete()

            assignments_created = 0
            for index, patient in enumerate(patients, start=1):
                _, created = ClinicianPatientAssignment.objects.get_or_create(
                    clinician=clinician_user,
                    patient=patient,
                    defaults={"assigned_at": now - timedelta(days=max(1, index))},
                )
                if created:
                    assignments_created += 1

            self._clear_patient_records(patients)

            stats = {
                "sensor_rows": 0,
                "pressure_frames": 0,
                "comments": 0,
                "feedback": 0,
                "pain_reports": 0,
                "annotations": 0,
            }

            for index, patient in enumerate(patients, start=1):
                patient_stats = self._seed_patient_records(
                    patient=patient,
                    patient_index=index,
                    frames_per_patient=frames_per_patient,
                    comments_per_patient=comments_per_patient,
                    feedback_per_patient=feedback_per_patient,
                    days_window=days_window,
                    now=now,
                    reviewer=admin_user,
                    rng=rng,
                )
                for key in stats:
                    stats[key] += patient_stats[key]

        self.stdout.write(self.style.SUCCESS("Curated demo data seed complete."))
        self.stdout.write(
            " | ".join(
                [
                    f"patients={len(patients)}",
                    f"purged_generated_users={len(purged_generated_users)}",
                    f"cleared_clinician_assignments={cleared_assignments}",
                    f"new_assignments={assignments_created}",
                    f"sensor_rows={stats['sensor_rows']}",
                    f"pressure_frames={stats['pressure_frames']}",
                    f"comments={stats['comments']}",
                    f"feedback={stats['feedback']}",
                    f"pain_reports={stats['pain_reports']}",
                    f"annotations={stats['annotations']}",
                ]
            )
        )
        self.stdout.write(
            "Clinician login: "
            f"{clinician_user.username}/{options['clinician_password']} | "
            f"Patient password: {options['patient_password']}"
        )
        self.stdout.write("Curated patient usernames:")
        for patient in patients:
            self.stdout.write(f"  - {patient.username}")

    def _ensure_admin(self, password):
        admin, _ = User.objects.get_or_create(
            username="admin",
            defaults={
                "role": User.ROLE_ADMIN,
                "email": "admin@sensore.local",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        admin.role = User.ROLE_ADMIN
        admin.is_staff = True
        admin.is_superuser = True
        admin.email = admin.email or "admin@sensore.local"
        admin.set_password(password)
        admin.save()
        return admin

    def _ensure_clinician(self, username, password):
        clinician, _ = User.objects.get_or_create(
            username=username,
            defaults={
                "role": User.ROLE_CLINICIAN,
                "email": f"{username}@sensore.local",
                "first_name": "Demo",
                "last_name": "Clinician",
            },
        )
        clinician.role = User.ROLE_CLINICIAN
        clinician.email = clinician.email or f"{username}@sensore.local"
        clinician.set_password(password)
        clinician.save()

        ClinicianProfile.objects.get_or_create(user=clinician)
        return clinician

    def _build_roster(self, patient_count):
        roster = []
        for idx in range(patient_count):
            if idx < len(PATIENT_NAME_POOL):
                roster.append(PATIENT_NAME_POOL[idx])
            else:
                roster.append((f"Patient{idx + 1}", f"Demo{idx + 1}"))
        return roster

    def _normalise_username(self, value):
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")

    def _ensure_patients(self, roster, password):
        patients = []
        used_usernames = set()

        for first_name, last_name in roster:
            base_username = self._normalise_username(f"demo_patient_{first_name}_{last_name}")
            username = base_username
            suffix = 2
            while username in used_usernames:
                username = f"{base_username}_{suffix:02d}"
                suffix += 1
            used_usernames.add(username)

            patient, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "role": User.ROLE_PATIENT,
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{username}@sensore.local",
                },
            )
            patient.role = User.ROLE_PATIENT
            patient.first_name = first_name
            patient.last_name = last_name
            patient.email = f"{username}@sensore.local"
            patient.set_password(password)
            patient.save()

            PatientProfile.objects.get_or_create(user=patient)
            patients.append(patient)

        # Keep legacy demo credentials available in curated mode.
        # The login screen references patient1/patient123 for quick testing.
        patient1, _ = User.objects.get_or_create(
            username="patient1",
            defaults={
                "role": User.ROLE_PATIENT,
                "first_name": "Demo",
                "last_name": "Patient One",
                "email": "patient1@sensore.local",
            },
        )
        patient1.role = User.ROLE_PATIENT
        patient1.first_name = patient1.first_name or "Demo"
        patient1.last_name = patient1.last_name or "Patient One"
        patient1.email = patient1.email or "patient1@sensore.local"
        patient1.set_password(password)
        patient1.save()
        PatientProfile.objects.get_or_create(user=patient1)

        if not any(p.id == patient1.id for p in patients):
            patients.append(patient1)

        return patients

    def _purge_generated_users(self, keep_usernames):
        generated_q = (
            Q(username__startswith="patient_bulk_")
            | Q(username__startswith="clinician_bulk_")
            | Q(username__startswith="junk_patient")
            | Q(username__startswith="junk_clin")
            | Q(username__startswith="demo_patient_")
        )

        users = User.objects.filter(generated_q).exclude(username__in=keep_usernames)
        usernames = list(users.values_list("username", flat=True))
        if usernames:
            users.delete()
        return usernames

    def _clear_patient_records(self, patients):
        Feedback.objects.filter(user__in=patients).delete()
        Comment.objects.filter(user__in=patients).delete()
        HeatmapAnnotation.objects.filter(user__in=patients).delete()
        PainZoneReport.objects.filter(user__in=patients).delete()
        PressureFrame.objects.filter(user__in=patients).delete()
        SensorData.objects.filter(user__in=patients).delete()

    def _seed_patient_records(
        self,
        patient,
        patient_index,
        frames_per_patient,
        comments_per_patient,
        feedback_per_patient,
        days_window,
        now,
        reviewer,
        rng,
    ):
        pressure_profiles = [1150, 1450, 1750, 2050, 2350]
        base_pressure = pressure_profiles[(patient_index - 1) % len(pressure_profiles)] + rng.randint(-120, 120)
        start_time = now - timedelta(days=days_window, hours=patient_index * 2)
        step_minutes = max(20, int((days_window * 24 * 60) / max(1, frames_per_patient)))

        sensor_rows = []
        frame_rows = []

        for frame_idx in range(frames_per_patient):
            timestamp = start_time + timedelta(minutes=frame_idx * step_minutes + rng.randint(0, 7))
            wave = int(320 * math.sin((frame_idx + patient_index) / 3.8))
            drift = int((frame_idx / max(1, frames_per_patient - 1)) * 180)
            spike = rng.randint(260, 950) if rng.random() < 0.14 else 0
            pressure = max(650, min(3900, base_pressure + wave + drift + spike + rng.randint(-90, 90)))

            matrix = _build_matrix_from_pressure(pressure)
            metrics = _calculate_frame_metrics(matrix)

            sensor_rows.append(
                SensorData(
                    user=patient,
                    timestamp=timestamp,
                    pressure_value=pressure,
                    sensor_id=f"CURATED_{patient.username}",
                    location="seat-mat",
                )
            )
            frame_rows.append(
                PressureFrame(
                    user=patient,
                    timestamp=timestamp,
                    raw_matrix=matrix,
                    peak_pressure_index=metrics["peak_pressure_index"],
                    contact_area_percentage=metrics["contact_area_percentage"],
                    high_pressure_flag=metrics["high_pressure_flag"],
                )
            )

        SensorData.objects.bulk_create(sensor_rows, batch_size=200)
        PressureFrame.objects.bulk_create(frame_rows, batch_size=200)

        recent_frames = list(
            PressureFrame.objects.filter(user=patient).order_by("-timestamp")[: max(1, comments_per_patient)]
        )
        comment_rows = []
        for i, frame in enumerate(recent_frames):
            comment_rows.append(
                Comment(
                    user=patient,
                    pressure_frame=frame,
                    timestamp=frame.timestamp,
                    text=COMMENT_TEMPLATES[(patient_index + i) % len(COMMENT_TEMPLATES)],
                )
            )
        if comment_rows:
            Comment.objects.bulk_create(comment_rows, batch_size=100)

        recent_sensor_rows = list(
            SensorData.objects.filter(user=patient).order_by("-timestamp")[: max(1, feedback_per_patient)]
        )
        feedback_rows = []
        for i, sensor_row in enumerate(recent_sensor_rows):
            cycle = (patient_index + i) % 3
            if cycle == 0:
                status = Feedback.STATUS_PENDING
                reviewed_by = None
                reviewed_at = None
                admin_notes = ""
            elif cycle == 1:
                status = Feedback.STATUS_REVIEWED
                reviewed_by = reviewer
                reviewed_at = timezone.now() - timedelta(days=1)
                admin_notes = "Reviewed and monitoring trend."
            else:
                status = Feedback.STATUS_RESOLVED
                reviewed_by = reviewer
                reviewed_at = timezone.now() - timedelta(days=2)
                admin_notes = "Resolved after posture guidance."

            feedback_rows.append(
                Feedback(
                    user=patient,
                    sensor_data=sensor_row,
                    comment=FEEDBACK_TEMPLATES[(patient_index + i) % len(FEEDBACK_TEMPLATES)],
                    status=status,
                    reviewed_by=reviewed_by,
                    reviewed_at=reviewed_at,
                    admin_notes=admin_notes,
                    created_at=sensor_row.timestamp + timedelta(minutes=5),
                )
            )
        if feedback_rows:
            Feedback.objects.bulk_create(feedback_rows, batch_size=100)

        zones_count = 1 + ((patient_index + rng.randint(0, 2)) % 3)
        zones = rng.sample(PREDEFINED_ZONES, zones_count)
        PainZoneReport.objects.create(
            user=patient,
            zones=zones,
            note="Curated demo pain-zone report.",
        )

        anchor_row = 14 + ((patient_index % 3) - 1)
        anchor_col = 16 + (((patient_index + 1) % 3) - 1)
        cells = [
            [max(0, min(31, anchor_row)), max(0, min(31, anchor_col))],
            [max(0, min(31, anchor_row + 1)), max(0, min(31, anchor_col))],
            [max(0, min(31, anchor_row)), max(0, min(31, anchor_col + 1))],
            [max(0, min(31, anchor_row + 1)), max(0, min(31, anchor_col + 1))],
        ]
        HeatmapAnnotation.objects.create(
            user=patient,
            cells=cells,
            note="Curated demo annotation.",
        )

        return {
            "sensor_rows": len(sensor_rows),
            "pressure_frames": len(frame_rows),
            "comments": len(comment_rows),
            "feedback": len(feedback_rows),
            "pain_reports": 1,
            "annotations": 1,
        }
