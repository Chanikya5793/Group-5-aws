from django.contrib.auth.models import User
from django.test import Client, TestCase

from .models import UserProfile


class LoginCsrfTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="csrf_user", password="secret123")
        self.client = Client(enforce_csrf_checks=True)

    def test_login_get_sets_csrf_cookie(self):
        response = self.client.get("/accounts/login/?next=/patient/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", self.client.cookies)

    def test_login_post_with_valid_csrf_redirects_to_next(self):
        self.client.get("/accounts/login/?next=/patient/")
        csrf_token = self.client.cookies["csrftoken"].value

        response = self.client.post(
            "/accounts/login/?next=/patient/",
            {
                "username": "csrf_user",
                "password": "secret123",
                "csrfmiddlewaretoken": csrf_token,
                "next": "/patient/",
            },
            HTTP_REFERER="http://testserver/accounts/login/?next=/patient/",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/patient/")

    def test_external_next_is_ignored(self):
        self.client.get("/accounts/login/?next=http://evil.example/")
        csrf_token = self.client.cookies["csrftoken"].value

        response = self.client.post(
            "/accounts/login/?next=http://evil.example/",
            {
                "username": "csrf_user",
                "password": "secret123",
                "csrfmiddlewaretoken": csrf_token,
                "next": "http://evil.example/",
            },
            HTTP_REFERER="http://testserver/accounts/login/?next=http://evil.example/",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")


class UserProfileSignalTests(TestCase):
    def test_profile_created_for_regular_user(self):
        user = User.objects.create_user(username="signal_patient", password="pass12345")
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.role, "patient")

    def test_profile_created_as_admin_for_superuser(self):
        user = User.objects.create_superuser(
            username="signal_admin",
            email="signal_admin@example.com",
            password="pass12345",
        )
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.role, "admin")
