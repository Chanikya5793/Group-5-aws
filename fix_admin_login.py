#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore_project.settings')
django.setup()

from django.contrib.auth import authenticate
from django.contrib.auth.models import User

from accounts.models import UserProfile

admin, _ = User.objects.get_or_create(
    username='admin',
    defaults={'email': 'admin@sensore.local', 'is_staff': True, 'is_superuser': True},
)

if not admin.is_staff or not admin.is_superuser:
    admin.is_staff = True
    admin.is_superuser = True

admin.set_password('admin123')
admin.save()

profile, _ = UserProfile.objects.get_or_create(user=admin, defaults={'role': 'admin'})
if profile.role != 'admin':
    profile.role = 'admin'
    profile.save(update_fields=['role'])

print("✓ Password reset for admin user")

# Test authentication
auth_result = authenticate(username='admin', password='admin123')
if auth_result:
    print("✓ Authentication successful!")
    print(f"  User: {auth_result.username}")
    print(f"  Role: {profile.role}")
else:
    print("✗ Authentication failed")
