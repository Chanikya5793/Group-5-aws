import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from accounts.models import UserProfile
from sensore.models import PressureMetrics, SensorFrame, SensorSession
from sensore.utils import analyse_frame


class LegacySuiteCompatibilityTests(TestCase):
    """
    Compatibility tests for the active sensore_project architecture.

    These replace legacy tests that targeted deprecated core routes/models.
    """

    def setUp(self):
        self.clinician = User.objects.create_user(
            username="dr_legacy",
            password="clinic123",
            first_name="Dr",
            last_name="Legacy",
        )
        clinician_profile = self.clinician.profile
        clinician_profile.role = "clinician"
        clinician_profile.save(update_fields=["role"])

        self.patient = User.objects.create_user(
            username="legacy_patient",
            password="patient123",
            first_name="Legacy",
            last_name="Patient",
        )
        patient_profile = self.patient.profile
        patient_profile.role = "patient"
        patient_profile.assigned_clinician = self.clinician
        patient_profile.patient_id = "LEGACY-001"
        patient_profile.save(update_fields=["role", "assigned_clinician", "patient_id"])

        self.session = SensorSession.objects.create(
            patient=self.patient,
            session_date=timezone.now().date(),
            start_time=timezone.now() - timedelta(minutes=5),
            end_time=timezone.now(),
            notes="Legacy compatibility test session",
        )

        self.frame = self._create_analysed_frame(self.session, frame_index=0, pressure=1800)

    def _create_analysed_frame(self, session, frame_index, pressure):
        flat = [1] * 1024
        # Build a meaningful contact block so metrics and plain-English text are generated.
        for row in range(12, 20):
            for col in range(10, 22):
                flat[row * 32 + col] = pressure

        frame = SensorFrame.objects.create(
            session=session,
            timestamp=session.start_time + timedelta(seconds=frame_index * 30),
            frame_index=frame_index,
            data=json.dumps(flat),
        )
        analyse_frame(frame)
        return frame

    def test_patient_dashboard_and_live_heatmap_api(self):
        self.client.login(username="legacy_patient", password="patient123")

        dashboard = self.client.get("/patient/")
        self.assertEqual(dashboard.status_code, 200)

        frames_resp = self.client.get(f"/api/session/{self.session.id}/frames/")
        self.assertEqual(frames_resp.status_code, 200)

        frames = frames_resp.json().get("frames", [])
        self.assertEqual(len(frames), 1)
        self.assertIn("metrics", frames[0])
        self.assertTrue(frames[0]["metrics"].get("plain_english"))

    def test_patient_can_add_timestamped_comment(self):
        self.client.login(username="legacy_patient", password="patient123")

        payload = {
            "text": "Pressure spike when leaning left",
            "frame_id": self.frame.id,
            "timestamp": self.frame.timestamp.isoformat(),
        }
        create_resp = self.client.post(
            f"/api/session/{self.session.id}/comment/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(create_resp.status_code, 200)

        comments_resp = self.client.get(f"/api/session/{self.session.id}/comments/")
        self.assertEqual(comments_resp.status_code, 200)
        comments = comments_resp.json().get("comments", [])
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["text"], payload["text"])
        self.assertEqual(comments[0]["frame_id"], self.frame.id)

    def test_report_page_and_pdf_download(self):
        self.client.login(username="legacy_patient", password="patient123")

        page_resp = self.client.get("/report/")
        self.assertEqual(page_resp.status_code, 200)
        self.assertContains(page_resp, "Medical History Report")

        pdf_resp = self.client.get("/report/?download=1")
        self.assertEqual(pdf_resp.status_code, 200)
        self.assertIn("application/pdf", (pdf_resp.get("Content-Type") or "").lower())

    def test_clinician_dashboard_sees_risk_summary(self):
        self.client.login(username="dr_legacy", password="clinic123")

        resp = self.client.get("/clinician/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.patient.username)

        self.assertGreater(PressureMetrics.objects.count(), 0)

    def test_patient_cannot_access_other_patient_session_frames(self):
        other_patient = User.objects.create_user(username="other_patient", password="patient123")
        other_profile = other_patient.profile
        other_profile.role = "patient"
        other_profile.assigned_clinician = self.clinician
        other_profile.save(update_fields=["role", "assigned_clinician"])
        other_session = SensorSession.objects.create(
            patient=other_patient,
            session_date=timezone.now().date(),
            start_time=timezone.now() - timedelta(minutes=3),
        )
        self._create_analysed_frame(other_session, frame_index=0, pressure=2200)

        self.client.login(username="legacy_patient", password="patient123")
        forbidden = self.client.get(f"/api/session/{other_session.id}/frames/")
        self.assertEqual(forbidden.status_code, 403)

    def test_clinician_cannot_access_unassigned_patient_frames_or_report(self):
        other_clinician = User.objects.create_user(username="other_doc", password="clinic123")
        other_clinician_profile = other_clinician.profile
        other_clinician_profile.role = "clinician"
        other_clinician_profile.save(update_fields=["role"])

        unassigned_patient = User.objects.create_user(
            username="outside_patient",
            password="patient123",
        )
        unassigned_profile = unassigned_patient.profile
        unassigned_profile.role = "patient"
        unassigned_profile.assigned_clinician = other_clinician
        unassigned_profile.save(update_fields=["role", "assigned_clinician"])

        outside_session = SensorSession.objects.create(
            patient=unassigned_patient,
            session_date=timezone.now().date(),
            start_time=timezone.now() - timedelta(minutes=2),
        )
        self._create_analysed_frame(outside_session, frame_index=0, pressure=2300)

        self.client.login(username="dr_legacy", password="clinic123")

        frames_forbidden = self.client.get(f"/api/session/{outside_session.id}/frames/")
        self.assertEqual(frames_forbidden.status_code, 403)

        report_forbidden = self.client.get(f"/report/{unassigned_patient.id}/")
        self.assertEqual(report_forbidden.status_code, 403)
