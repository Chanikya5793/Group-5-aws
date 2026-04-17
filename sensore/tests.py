import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import SensorFrame, SensorSession
from .utils import analyse_frame


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


class AdvancedReportingAndMetricsTests(TestCase):
    def setUp(self):
        self.patient = User.objects.create_user(username="metrics_patient", password="patient123")
        self.clinician = User.objects.create_user(username="metrics_clinician", password="clinic123")

        clinician_profile = self.clinician.profile
        clinician_profile.role = "clinician"
        clinician_profile.save(update_fields=["role"])

        patient_profile = self.patient.profile
        patient_profile.role = "patient"
        patient_profile.assigned_clinician = self.clinician
        patient_profile.patient_id = "METRICS-001"
        patient_profile.save(update_fields=["role", "assigned_clinician", "patient_id"])

        self.session = SensorSession.objects.create(
            patient=self.patient,
            session_date=timezone.now().date(),
            start_time=timezone.now() - timedelta(minutes=10),
            end_time=timezone.now(),
            notes="Advanced metrics test session",
        )

        flat = [0] * 1024
        for row in range(10, 24):
            for col in range(8, 24):
                flat[row * 32 + col] = 2200

        self.frame = SensorFrame.objects.create(
            session=self.session,
            timestamp=self.session.start_time,
            frame_index=0,
            data=json.dumps(flat),
        )
        analyse_frame(self.frame)

    def test_latest_frame_payload_has_advanced_metrics(self):
        self.client.login(username="metrics_patient", password="patient123")

        response = self.client.get(f"/api/session/{self.session.id}/latest/")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertIn("metrics", payload)
        metrics = payload["metrics"]

        self.assertIn("movement_index", metrics)
        self.assertIn("pressure_variability", metrics)
        self.assertIn("pressure_concentration", metrics)
        self.assertIn("sustained_load_index", metrics)
        self.assertIn("center_of_pressure_x", metrics)
        self.assertIn("center_of_pressure_y", metrics)

    def test_csv_report_download(self):
        self.client.login(username="metrics_patient", password="patient123")

        response = self.client.get("/report/?download=csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", (response.get("Content-Type") or "").lower())

        payload = response.content.decode("utf-8")
        self.assertIn("Sensore Medical History Export", payload)
        self.assertIn("Session Date", payload)

    def test_clinician_patient_sessions_api_has_summary_fields(self):
        self.client.login(username="metrics_clinician", password="clinic123")

        response = self.client.get(f"/api/patient/{self.patient.id}/sessions/")
        self.assertEqual(response.status_code, 200)
        sessions = response.json().get("sessions", [])

        self.assertEqual(len(sessions), 1)
        self.assertIn("avg_risk_score", sessions[0])
        self.assertIn("high_risk_ratio", sessions[0])
        self.assertIn("risk_trend", sessions[0])
