#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore_project.settings')
django.setup()

from django.contrib.auth.models import User

from accounts.models import UserProfile


def ensure_user(username, password, **defaults):
    user, created = User.objects.get_or_create(username=username, defaults=defaults)

    changed = created
    for field, value in defaults.items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed = True

    if not user.check_password(password):
        user.set_password(password)
        changed = True

    if changed:
        user.save()

    return user, created


def ensure_profile(user, role, **defaults):
    profile, created = UserProfile.objects.get_or_create(
        user=user,
        defaults={"role": role, **defaults},
    )

    changed = created
    if profile.role != role:
        profile.role = role
        changed = True

    for field, value in defaults.items():
        if value is not None and getattr(profile, field) != value:
            setattr(profile, field, value)
            changed = True

    if changed:
        profile.save()

    return profile, created


clinician_user, clinician_created = ensure_user(
    username='clinician1',
    password='clinician123',
    email='clinician@sensore.local',
    first_name='Alex',
    last_name='Clinician',
)
ensure_profile(clinician_user, role='clinician')
print("✓ Clinician 'clinician1' created" if clinician_created else "✓ Clinician 'clinician1' updated")

patient_user, patient_created = ensure_user(
    username='patient1',
    password='patient123',
    email='patient@sensore.local',
    first_name='Pat',
    last_name='Patient',
)
ensure_profile(
    patient_user,
    role='patient',
    patient_id='PATIENT1',
    assigned_clinician=clinician_user,
)
print("✓ Patient 'patient1' created" if patient_created else "✓ Patient 'patient1' updated")

print("\nTest Credentials:")
print("  Admin:     username=admin, password=admin123")
print("  Clinician: username=clinician1, password=clinician123")
print("  Patient:   username=patient1, password=patient123")
