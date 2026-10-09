import asyncio
import hashlib
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base, get_db
from otp_delivery import CaptureOtpDeliveryProvider
from routers import assessments, auth, patients


TEST_OTP_SECRET = "task15-core-test-hmac-secret-32-characters-minimum"


BACKEND_DIR = Path(__file__).resolve().parent
AUTHORITATIVE_DATABASES = (
    BACKEND_DIR / "eldercare_bd.db",
    BACKEND_DIR / "eldercare_bd_2.db",
)


def _database_signatures():
    signatures = {}
    for path in AUTHORITATIVE_DATABASES:
        if path.exists():
            signatures[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            signatures[path.name] = None
    return signatures


class FastApiRequestHarness:
    def __init__(self, app):
        self.app = app

    def request(self, method, path, payload=None, token=None):
        return asyncio.run(self._request(method, path, payload, token))

    async def _request(self, method, path, payload, token):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        headers = [(b"accept", b"application/json")]
        if payload is not None:
            headers.append((b"content-type", b"application/json"))
        if token is not None:
            headers.append((b"authorization", f"Bearer {token}".encode("ascii")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }

        request_sent = False
        messages = []

        async def receive():
            nonlocal request_sent
            if request_sent:
                return {"type": "http.disconnect"}
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        await self.app(scope, receive, send)

        start = next(
            message
            for message in messages
            if message["type"] == "http.response.start"
        )
        response_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        decoded = json.loads(response_body) if response_body else None
        return start["status"], decoded


class CoreWorkflowIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.database_signatures = _database_signatures()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.assertEqual(str(self.engine.url), "sqlite://")
        Base.metadata.create_all(bind=self.engine)
        self.session = sessionmaker(bind=self.engine)()

        app = FastAPI()
        app.include_router(auth.router)
        app.include_router(patients.router)
        app.include_router(assessments.router)

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = FastApiRequestHarness(app)
        self.otp_provider = CaptureOtpDeliveryProvider()
        self.delivery_patch = patch.object(
            auth,
            "get_otp_delivery_provider",
            return_value=self.otp_provider,
        )
        self.secret_patch = patch.object(
            auth,
            "get_otp_hmac_secret",
            return_value=TEST_OTP_SECRET,
        )
        self.delivery_patch.start()
        self.secret_patch.start()

    def tearDown(self):
        self.secret_patch.stop()
        self.delivery_patch.stop()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.assertEqual(self.database_signatures, _database_signatures())

    def _register_caregiver(self, label):
        status, body = self.client.request(
            "POST",
            "/auth/register-caregiver",
            {
                "name": f"Caregiver {label}",
                "phone_or_email": f"caregiver-{label.lower()}@example.invalid",
                "password": f"password-{label.lower()}",
            },
        )
        self.assertEqual(status, 202)
        self.assertIsInstance(body["caregiver_id"], int)
        self.assertNotIn("access_token", body)
        status, verification = self.client.request(
            "POST",
            "/auth/verify-otp",
            {
                "caregiver_id": body["caregiver_id"],
                "channel": body["channel"],
                "otp": self.otp_provider.deliveries[-1].code,
            },
        )
        self.assertEqual(status, 200)
        self.assertNotIn("access_token", verification)
        status, login = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": f"caregiver-{label.lower()}@example.invalid",
                "password": f"password-{label.lower()}",
            },
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(login["access_token"], str)
        self.assertTrue(login["access_token"])
        return body["caregiver_id"], login["access_token"]

    def _create_patient(self, caregiver_id, token, label):
        status, body = self.client.request(
            "POST",
            "/patients/",
            {
                "caregiver_id": caregiver_id,
                "name": f"Patient {label}",
                "age": 72,
                "gender": "Other",
                "phone": f"patient-{label.lower()}",
                "address": f"Address {label}",
                "emergency_contact": f"Emergency {label}",
                "has_diabetes": label == "A",
                "has_heart_disease": False,
                "has_hypertension": True,
                "has_kidney_disease": False,
                "has_stroke_history": False,
                "disease_history": f"History {label}",
            },
            token=token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["caregiver_id"], caregiver_id)
        self.assertIsInstance(body["patient_id"], int)
        return body["patient_id"]

    def _assessment_payload(self, patient_id, *, note, glucose, overall_risk):
        return {
            "patient_id": patient_id,
            "age": 72,
            "glucose": glucose,
            "systolic_bp": 145,
            "diastolic_bp": 90,
            "height_cm": 160.0,
            "weight_kg": 64.0,
            "bmi": 25.0,
            "chest_pain": True,
            "dizziness": False,
            "shortness_of_breath": True,
            "excessive_thirst": False,
            "fatigue": True,
            "blurred_vision": False,
            "note": note,
            "diabetes_risk": "High",
            "heart_risk": "Moderate",
            "overall_risk": overall_risk,
            "recommendation": "Arrange a clinical review and continue monitoring.",
        }

    def test_authentication_registration_login_and_failures(self):
        caregiver_id, _ = self._register_caregiver("Auth")

        status, body = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "caregiver-auth@example.invalid",
                "password": "password-auth",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["caregiver_id"], caregiver_id)

        status, body = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "caregiver-auth@example.invalid",
                "password": "incorrect-password",
            },
        )
        self.assertEqual(status, 401)
        self.assertEqual(body["detail"], "Invalid login credentials")

        status, body = self.client.request(
            "POST",
            "/auth/register-caregiver",
            {
                "name": "Duplicate",
                "phone_or_email": "caregiver-auth@example.invalid",
                "password": "another-password",
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["detail"]["code"], "caregiver_already_exists")

        status, body = self.client.request(
            "POST",
            "/auth/register-caregiver",
            {"name": "   ", "phone_or_email": "   ", "password": "   "},
        )
        self.assertEqual(status, 422)
        self.assertIsInstance(body["detail"], list)

    def test_patient_creation_and_caregiver_filtering_are_isolated(self):
        caregiver_a, token_a = self._register_caregiver("A")
        caregiver_b, token_b = self._register_caregiver("B")
        patient_a = self._create_patient(caregiver_a, token_a, "A")
        patient_b = self._create_patient(caregiver_b, token_b, "B")

        status, caregiver_a_patients = self.client.request(
            "GET", f"/patients/caregiver/{caregiver_a}", token=token_a
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            [patient["id"] for patient in caregiver_a_patients], [patient_a]
        )
        self.assertNotIn(patient_b, [patient["id"] for patient in caregiver_a_patients])

        status, caregiver_b_patients = self.client.request(
            "GET", f"/patients/caregiver/{caregiver_b}", token=token_b
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            [patient["id"] for patient in caregiver_b_patients], [patient_b]
        )

        status, body = self.client.request(
            "POST",
            "/patients/",
            {
                "caregiver_id": 999999,
                "name": "Missing caregiver patient",
                "age": 72,
                "gender": "Other",
            },
            token=token_a,
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["detail"], "Not authorized to access this resource.")

        status, body = self.client.request(
            "POST",
            "/patients/",
            {
                "caregiver_id": caregiver_a,
                "name": "   ",
                "age": 0,
                "gender": "Unknown",
            },
            token=token_a,
        )
        self.assertEqual(status, 422)
        self.assertIsInstance(body["detail"], list)

    def test_complete_workflow_persists_and_retrieves_assessment_history(self):
        caregiver_a, registration_token_a = self._register_caregiver("Workflow-A")
        caregiver_b, token_b = self._register_caregiver("Workflow-B")

        status, login_body = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "caregiver-workflow-a@example.invalid",
                "password": "password-workflow-a",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(login_body["caregiver_id"], caregiver_a)
        token_a = login_body["access_token"]
        self.assertNotEqual(token_a, registration_token_a)

        patient_a = self._create_patient(
            caregiver_a,
            token_a,
            "Workflow-A",
        )
        patient_b = self._create_patient(
            caregiver_b,
            token_b,
            "Workflow-B",
        )

        status, patients_for_a = self.client.request(
            "GET", f"/patients/caregiver/{caregiver_a}", token=token_a
        )
        self.assertEqual(status, 200)
        self.assertEqual([patient["id"] for patient in patients_for_a], [patient_a])

        older_payload = self._assessment_payload(
            patient_a,
            note="Older caregiver note",
            glucose=150,
            overall_risk="Moderate",
        )
        status, older_response = self.client.request(
            "POST", "/assessments/", older_payload, token=token_a
        )
        self.assertEqual(status, 200)
        self.assertEqual(older_response["overall_risk"], "Moderate")

        older_row = self.session.get(models.Assessment, older_response["assessment_id"])
        older_row.created_at = datetime(2026, 8, 18, 8, 0, 0)
        self.session.commit()

        newer_payload = self._assessment_payload(
            patient_a,
            note="Newest caregiver note",
            glucose=165,
            overall_risk="High",
        )
        status, newer_response = self.client.request(
            "POST", "/assessments/", newer_payload, token=token_a
        )
        self.assertEqual(status, 200)
        self.assertEqual(newer_response["overall_risk"], "High")

        newer_row = self.session.get(models.Assessment, newer_response["assessment_id"])
        newer_row.created_at = datetime(2026, 8, 18, 9, 0, 0)
        self.session.commit()

        other_patient_payload = self._assessment_payload(
            patient_b,
            note="Other patient note",
            glucose=130,
            overall_risk="Low",
        )
        status, _ = self.client.request(
            "POST",
            "/assessments/",
            other_patient_payload,
            token=token_b,
        )
        self.assertEqual(status, 200)

        self.assertEqual(newer_row.patient_id, patient_a)
        for field, value in newer_payload.items():
            self.assertEqual(getattr(newer_row, field), value, msg=field)

        status, history = self.client.request(
            "GET", f"/assessments/patient/{patient_a}", token=token_a
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(history), 2)
        self.assertEqual(len({item["id"] for item in history}), 2)
        self.assertEqual(
            [item["id"] for item in history],
            [newer_response["assessment_id"], older_response["assessment_id"]],
        )
        self.assertEqual(
            [item["created_at"] for item in history],
            ["2026-08-18T09:00:00Z", "2026-08-18T08:00:00Z"],
        )

        newest = history[0]
        for field, value in newer_payload.items():
            self.assertEqual(newest[field], value, msg=field)

        status, other_history = self.client.request(
            "GET", f"/assessments/patient/{patient_b}", token=token_b
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(other_history), 1)
        self.assertEqual(other_history[0]["patient_id"], patient_b)


if __name__ == "__main__":
    unittest.main()
