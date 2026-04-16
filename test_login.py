#!/usr/bin/env python
import os


def main():
    import django
    from django.test import Client

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sensore.settings')
    django.setup()

    client = Client()
    response = client.post('/login/', {
        'username': 'admin',
        'password': 'admin123',
    })

    print(f"Status Code: {response.status_code}")
    if response.status_code in [301, 302]:
        print(f"Redirect URL: {response.url}")
    else:
        print("Redirect URL: No redirect")


if __name__ == '__main__':
    main()
