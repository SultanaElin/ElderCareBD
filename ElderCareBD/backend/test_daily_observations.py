import asyncio
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from daily_observation_migration import migrate_daily_observations
from database import Base, get_db
from routers import daily_observations
from security import create_caregiver_session


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
        return (
            start["status"],
            json.loads(response_body) if response_body else None,
        )


class DailyObservationApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = sessionmaker(bind=self.engine)()
        app = FastAPI()
        app.include_router(daily_observations.router)

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = FastApiRequestHarness(app)
        self.owner, self.owner_token = self._caregiver("owner")
        self.other, self.other_token = self._caregiver("other")
        self.patient = self._patient(self.owner, "Owned patient")
        self.other_patient = self._patient(self.other, "Other patient")

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _caregiver(self, label):
        caregiver = models.Caregiver(
            name=label,
            phone_or_email=f"{label}@example.invalid",
            password="unused",
            identity_normalized=f"{label}@example.invalid",
            verification_status="verified",
            verified_at=datetime.utcnow(),
            primary_verification_channel="email",
        )
        self.session.add(caregiver)
        self.session.flush()
        token = create_caregiver_session(self.session, caregiver.id)
        self.session.commit()
        return caregiver, token

    def _patient(self, caregiver, name):
        patient = models.Patient(
            caregiver_id=caregiver.id,
            name=name,
            age=70,
            gender="Other",
        )
        self.session.add(patient)
        self.session.commit()
        return patient

    def _create(self, payload, *, patient=None, token=None):
        patient = patient or self.patient
        return self.client.request(
            "POST",
            f"/patients/{patient.id}/observations/today",
            payload,
            token=token or self.owner_token,
        )

    def test_01_create_full_observation(self):
        status, body = self._create(
            {
                "systolic_bp": 130,
                "diastolic_bp": 80,
                "glucose_value": 6.1,
                "glucose_unit": "mmol/L",
                "glucose_context": "fasting",
                "pulse_bpm": 72,
                "spo2_percent": 98,
                "temperature_value": 36.8,
                "temperature_unit": "C",
                "weight_kg": 65.5,
                "symptoms": "Mild fatigue",
                "notes": "Observed after breakfast",
            }
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["patient_id"], self.patient.id)
        self.assertEqual(
            body["observation_date"],
            datetime.utcnow().date().isoformat(),
        )
        self.assertEqual(body["glucose_value"], 6.1)
        self.assertEqual(self.session.query(models.Assessment).count(), 0)

    def test_02_create_partial_observation(self):
        status, body = self._create({"pulse_bpm": 68})
        self.assertEqual(status, 201)
        self.assertEqual(body["pulse_bpm"], 68)

    def test_03_same_day_create_conflicts(self):
        self.assertEqual(self._create({"notes": "First"})[0], 201)
        status, body = self._create({"notes": "Second"})
        self.assertEqual(status, 409)
        self.assertIn("already exists", body["detail"])

    def test_04_update_observation(self):
        _, created = self._create({"pulse_bpm": 70})
        status, updated = self.client.request(
            "PATCH",
            f"/patients/{self.patient.id}/observations/{created['id']}",
            {"pulse_bpm": 75, "notes": "Rechecked"},
            token=self.owner_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["pulse_bpm"], 75)
        self.assertEqual(updated["notes"], "Rechecked")

    def test_05_today_lookup(self):
        _, created = self._create({"spo2_percent": 97})
        status, body = self.client.request(
            "GET",
            f"/patients/{self.patient.id}/observations/today",
            token=self.owner_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], created["id"])

    def test_06_list_is_newest_date_first(self):
        old = models.PatientDailyObservation(
            patient_id=self.patient.id,
            observation_date=datetime.utcnow().date() - timedelta(days=1),
            recorded_at=datetime.utcnow(),
            pulse_bpm=65,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.session.add(old)
        self.session.commit()
        _, newest = self._create({"pulse_bpm": 70})
        status, body = self.client.request(
            "GET",
            f"/patients/{self.patient.id}/observations",
            token=self.owner_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in body], [newest["id"], old.id])

    def test_07_missing_values_stay_null(self):
        _, body = self._create({"notes": "Only a note"})
        for field_name in (
            "systolic_bp",
            "diastolic_bp",
            "glucose_value",
            "glucose_unit",
            "glucose_context",
            "pulse_bpm",
            "spo2_percent",
            "temperature_value",
            "temperature_unit",
            "weight_kg",
            "symptoms",
        ):
            self.assertIsNone(body[field_name])
        stored = self.session.get(models.PatientDailyObservation, body["id"])
        self.assertIsNone(stored.glucose_value)
        self.assertIsNone(stored.temperature_value)

    def test_08_invalid_blood_pressure_is_rejected(self):
        for payload in (
            {"systolic_bp": 120, "diastolic_bp": 120},
            {"systolic_bp": 59},
            {"diastolic_bp": 161},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self._create(payload)[0], 422)

    def test_09_invalid_spo2_is_rejected(self):
        self.assertEqual(self._create({"spo2_percent": -0.1})[0], 422)
        self.assertEqual(self._create({"spo2_percent": 100.1})[0], 422)

    def test_10_invalid_temperature_is_rejected(self):
        for payload in (
            {"temperature_value": 31.9, "temperature_unit": "C"},
            {"temperature_value": 110, "temperature_unit": "F"},
            {"temperature_value": 37},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self._create(payload)[0], 422)

    def test_11_invalid_numeric_values_are_rejected(self):
        for value in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertEqual(self._create({"pulse_bpm": value})[0], 422)

    def test_12_owner_can_access_observation(self):
        self._create({"weight_kg": 61})
        status, body = self.client.request(
            "GET",
            f"/patients/{self.patient.id}/observations",
            token=self.owner_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 1)

    def test_13_cross_owner_access_is_hidden(self):
        _, other_observation = self._create(
            {"notes": "Other caregiver data"},
            patient=self.other_patient,
            token=self.other_token,
        )
        status, body = self.client.request(
            "GET",
            f"/patients/{self.other_patient.id}/observations",
            token=self.owner_token,
        )
        self.assertEqual(status, 404)
        self.assertEqual(body["detail"], "Resource not found.")
        self.assertEqual(
            self._create(
                {"notes": "Unauthorized create"},
                patient=self.other_patient,
                token=self.owner_token,
            )[0],
            404,
        )
        self.assertEqual(
            self.client.request(
                "PATCH",
                f"/patients/{self.other_patient.id}/observations/"
                f"{other_observation['id']}",
                {"notes": "Unauthorized update"},
                token=self.owner_token,
            )[0],
            404,
        )

    def test_14_unauthenticated_access_is_rejected(self):
        status, body = self.client.request(
            "GET",
            f"/patients/{self.patient.id}/observations",
        )
        self.assertEqual(status, 401)
        self.assertEqual(body["detail"], "Authentication required.")


class DailyObservationMigrationTest(unittest.TestCase):
    def test_15_migration_rerun_is_safe_byte_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "eldercare_bd.db"
            backup = root / "pre_task18a1.db"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    PRAGMA foreign_keys = ON;
                    CREATE TABLE patients (id INTEGER PRIMARY KEY);
                    CREATE TABLE eldercare_schema_migrations (
                        version TEXT PRIMARY KEY NOT NULL,
                        applied_at TEXT NOT NULL,
                        source_backup_sha256 TEXT NOT NULL
                    );
                    INSERT INTO patients (id) VALUES (1);
                    """
                )
                connection.commit()
            finally:
                connection.close()
            shutil.copy2(database, backup)

            first = migrate_daily_observations(database, backup)
            self.assertTrue(first["applied"])
            hash_after_first = hashlib.sha256(database.read_bytes()).hexdigest()
            second = migrate_daily_observations(database, backup)
            self.assertFalse(second["applied"])
            self.assertEqual(
                hash_after_first,
                hashlib.sha256(database.read_bytes()).hexdigest(),
            )
            self.assertEqual(second["integrity_check"], "ok")
            self.assertEqual(second["foreign_key_issues"], 0)


if __name__ == "__main__":
    unittest.main()
