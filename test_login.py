#!/usr/bin/env python
import os


def main():
    import django
    from django.test import Client

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore_project.settings')
    django.setup()

    from django.contrib.auth.models import User

    credentials = [
        ('admin', 'admin123'),
        ('dr_smith', 'clinic123'),
        ('patient_001', 'patient123'),
    ]

    chosen_username = None
    chosen_password = None
    for username, password in credentials:
        if User.objects.filter(username=username).exists():
            chosen_username = username
            chosen_password = password
            break

    if not chosen_username:
        print('No known test user exists. Run: python manage.py load_sample_data')
        return

    client = Client(enforce_csrf_checks=True)
    login_url = '/accounts/login/?next=/dashboard/'
    get_response = client.get(login_url, secure=True)
    csrf_token = client.cookies.get('csrftoken').value if client.cookies.get('csrftoken') else ''

    response = client.post(
        login_url,
        {
            'username': chosen_username,
            'password': chosen_password,
            'next': '/dashboard/',
            'csrfmiddlewaretoken': csrf_token,
        },
        secure=True,
        HTTP_REFERER='https://testserver/accounts/login/?next=/dashboard/',
    )

    print(f'Login page status: {get_response.status_code}')
    print(f'Username tested: {chosen_username}')
    print(f"Status Code: {response.status_code}")
    if response.status_code in [301, 302]:
        print(f"Redirect URL: {response.url}")
    else:
        print("Redirect URL: No redirect")


if __name__ == '__main__':
    main()
