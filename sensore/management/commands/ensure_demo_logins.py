"""Ensure demo login accounts always exist with expected passwords."""

import os
import sys
from datetime import date

if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sensore_project.settings")
    import django
    django.setup()

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import UserProfile


class Command(BaseCommand):
    help = "Ensure all demo login accounts exist and have known passwords"

    def handle(self, *args, **options):
        User = get_user_model()

        def ensure_user(
            username,
            password,
            defaults=None,
            is_staff=False,
            is_superuser=False,
            is_active=True,
        ):
            defaults = defaults or {}
            user, created = User.objects.get_or_create(username=username, defaults=defaults)

            changed = created
            for field, value in defaults.items():
                if getattr(user, field) != value:
                    setattr(user, field, value)
                    changed = True

            if user.is_staff != is_staff:
                user.is_staff = is_staff
                changed = True

            if user.is_superuser != is_superuser:
                user.is_superuser = is_superuser
                changed = True

            if user.is_active != is_active:
                user.is_active = is_active
                changed = True

            if not user.check_password(password):
                user.set_password(password)
                changed = True

            if changed:
                user.save()

            return user

        def ensure_profile(user, role, patient_id=None, assigned_clinician=None, date_of_birth=None, medical_notes=None):
            profile, created = UserProfile.objects.get_or_create(user=user, defaults={"role": role})

            changed_fields = []
            if profile.role != role:
                profile.role = role
                changed_fields.append("role")

            if role == "patient":
                if patient_id and profile.patient_id != patient_id:
                    profile.patient_id = patient_id
                    changed_fields.append("patient_id")

                if assigned_clinician and profile.assigned_clinician_id != assigned_clinician.id:
                    profile.assigned_clinician = assigned_clinician
                    changed_fields.append("assigned_clinician")

                if date_of_birth and profile.date_of_birth != date_of_birth:
                    profile.date_of_birth = date_of_birth
                    changed_fields.append("date_of_birth")

                if medical_notes is not None and profile.medical_notes != medical_notes:
                    profile.medical_notes = medical_notes
                    changed_fields.append("medical_notes")

            if created or changed_fields:
                profile.save()

        self.stdout.write("Ensuring demo login accounts...")

        admin = ensure_user(
            username="admin",
            password="admin123",
            defaults={"first_name": "System", "last_name": "Admin", "email": "admin@sensore.local"},
            is_staff=True,
            is_superuser=True,
        )
        ensure_profile(admin, "admin")

        clinician = ensure_user(
            username="dr_smith",
            password="clinic123",
            defaults={
                "first_name": "Dr. Sarah",
                "last_name": "Smith",
                "email": "sarah.smith@hospital.org",
            },
        )
        ensure_profile(clinician, "clinician")

        patient_defaults = [
            ("patient_001", "James", "Wilson", "PATIENT_001", date(1960, 1, 15)),
            ("patient_002", "Maria", "Chen", "PATIENT_002", date(1975, 4, 22)),
            ("patient_003", "Robert", "Taylor", "PATIENT_003", date(1982, 7, 9)),
            ("patient_004", "Agnes", "Okafor", "PATIENT_004", date(1958, 9, 2)),
            ("patient_005", "Thomas", "Brown", "PATIENT_005", date(1969, 11, 30)),
        ]

        for username, first_name, last_name, patient_id, dob in patient_defaults:
            patient = ensure_user(
                username=username,
                password="patient123",
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{username}@sensore.test",
                },
            )
            ensure_profile(
                patient,
                "patient",
                patient_id=patient_id,
                assigned_clinician=clinician,
                date_of_birth=dob,
            )

        real_patient = ensure_user(
            username="de0e9b2c",
            password="patient123",
            defaults={
                "first_name": "Sensor",
                "last_name": "Patient DE0E",
                "email": "de0e9b2c@sensore.device",
            },
        )
        ensure_profile(
            real_patient,
            "patient",
            patient_id="DE0E9B2C",
            assigned_clinician=clinician,
            date_of_birth=date(1970, 1, 1),
            medical_notes="Real hardware login account for de0e9b2c_20251013.csv",
        )

        self.stdout.write(self.style.SUCCESS("Demo credentials are now guaranteed:"))
        self.stdout.write("  admin / admin123")
        self.stdout.write("  dr_smith / clinic123")
        self.stdout.write("  patient_001 ... patient_005 / patient123")
        self.stdout.write("  de0e9b2c / patient123")


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sensore_project.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line([sys.argv[0], "ensure_demo_logins", *sys.argv[1:]])
