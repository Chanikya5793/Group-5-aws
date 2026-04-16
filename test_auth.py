#!/usr/bin/env python
import os


def main():
    import django
    from django.contrib.auth import authenticate

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore.settings')
    django.setup()

    users = [('admin', 'admin123'), ('clinician1', 'clinician123'), ('patient1', 'patient123')]
    for username, password in users:
        auth_result = authenticate(username=username, password=password)
        status = 'OK' if auth_result else 'FAILED'
        print(f'{username}: {status}')


if __name__ == '__main__':
    main()
