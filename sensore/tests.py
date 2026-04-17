from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import SensorFrame, SensorSession


class SessionFramesApiWindowingTests(TestCase):
    def setUp(self):
        self.patient = User.objects.create_user(username="api_patient", password="patient123")
        self.client.login(username="api_patient", password="patient123")

        self.session = SensorSession.objects.create(
            patient=self.patient,
            session_date=timezone.now().date(),
            start_time=timezone.now() - timedelta(hours=1),
        )

    def _create_frames(self, count):
        base_time = self.session.start_time
        frames = [
            SensorFrame(
                session=self.session,
                timestamp=base_time + timedelta(seconds=i * 30),
                frame_index=i,
                data='[0]',
            )
            for i in range(count)
        ]
        SensorFrame.objects.bulk_create(frames)

    def test_default_returns_latest_window(self):
        self._create_frames(1305)

        response = self.client.get(f"/api/session/{self.session.id}/frames/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["total_frames"], 1305)
        self.assertEqual(payload["returned_frames"], 1200)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["first_frame_index"], 105)
        self.assertEqual(payload["last_frame_index"], 1304)
        self.assertEqual(payload["frames"][0]["frame_index"], 105)
        self.assertEqual(payload["frames"][-1]["frame_index"], 1304)

    def test_limit_all_returns_full_session(self):
        self._create_frames(25)

        response = self.client.get(f"/api/session/{self.session.id}/frames/?limit=all")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["total_frames"], 25)
        self.assertEqual(payload["returned_frames"], 25)
        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["first_frame_index"], 0)
        self.assertEqual(payload["last_frame_index"], 24)

    def test_numeric_limit_returns_latest_n_frames(self):
        self._create_frames(40)

        response = self.client.get(f"/api/session/{self.session.id}/frames/?limit=7")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["returned_frames"], 7)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["first_frame_index"], 33)
        self.assertEqual(payload["last_frame_index"], 39)
