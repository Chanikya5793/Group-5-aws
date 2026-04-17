#!/usr/bin/env python
import os


def main():
    import django
    from django.contrib.auth import authenticate

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore_project.settings')
    django.setup()

    from django.contrib.auth.models import User

    users = [
        ('admin', 'admin123'),
        ('dr_smith', 'clinic123'),
        ('patient_001', 'patient123'),
    ]
    for username, password in users:
        if not User.objects.filter(username=username).exists():
            print(f'{username}: MISSING USER')
            continue

        auth_result = authenticate(username=username, password=password)
        status = 'OK' if auth_result else 'FAILED'
        print(f'{username}: {status}')


if __name__ == '__main__':
    main()
