#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore_project.settings')
django.setup()

from django.contrib.auth.models import User

from accounts.models import UserProfile

admin_user, created = User.objects.get_or_create(
    username='admin',
    defaults={
        'email': 'admin@sensore.local',
        'is_staff': True,
        'is_superuser': True,
    },
)

if not admin_user.is_staff or not admin_user.is_superuser:
    admin_user.is_staff = True
    admin_user.is_superuser = True

admin_user.email = admin_user.email or 'admin@sensore.local'
admin_user.set_password('admin123')
admin_user.save()

profile, _ = UserProfile.objects.get_or_create(user=admin_user, defaults={'role': 'admin'})
if profile.role != 'admin':
    profile.role = 'admin'
    profile.save(update_fields=['role'])

if created:
    print("✓ Superuser 'admin' created successfully")
else:
    print("✓ Superuser 'admin' updated successfully")
