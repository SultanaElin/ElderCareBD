import asyncio
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, UploadFile
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import image_storage
import models
import prescription_foundation_migration
from auth_test_support import create_verified_caregiver_session
from database import Base, get_db
from migrate_prescription_foundation import migrate_prescription_foundation
from prescription_foundation_migration import (
    MEDICINE_COLUMNS,
    PRESCRIPTION_COLUMNS,
)
from prescription_integrity import MEDICINE_PRESCRIPTION_TRIGGER_SQL
from request_limits import (
    MAX_PRESCRIPTION_UPLOAD_REQUEST_BYTES,
    PrescriptionUploadLimitMiddleware,
)
from routers import auth, medicines, patients, prescriptions
from test_core_workflow import _database_signatures


PIL_AVAILABLE = importlib.util.find_spec("PIL") is not None


class RawRequestHarness:
    def __init__(self, app):
        self.app = app

    def request(
        self,
        method,
        path,
        body=b"",
        content_type=None,
        token=None,
        include_content_length=True,
    ):
        return asyncio.run(
            self._request(
                method,
                path,
                body,
                content_type,
                token,
                include_content_length,
            )
        )

    async def _request(
        self,
        method,
        path,
        body,
        content_type,
        token,
        include_content_length,
    ):
        headers = [(b"accept", b"application/json")]
        if content_type is not None:
            headers.append((b"content-type", content_type.encode("ascii")))
        if body and include_content_length:
            headers.append((b"content-length", str(len(body)).encode("ascii")))
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
        response_headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in start.get("headers", [])
        }
        if response_headers.get("content-type", "").startswith("application/json"):
            decoded = json.loads(response_body) if response_body else None
        else:
            decoded = response_body
        return start["status"], decoded, response_headers

    def json(self, method, path, payload=None, token=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        return self.request(
            method,
            path,
            body,
            "application/json" if payload is not None else None,
            token,
        )

    def multipart(
        self,
        method,
        path,
        fields,
        token=None,
        file_bytes=None,
        filename="prescription.jpg",
        file_content_type="image/jpeg",
    ):
        boundary = "eldercare-test-boundary"
        sections = []
        for name, value in fields.items():
            sections.extend(
                [
                    f"--{boundary}\r\n".encode("ascii"),
                    (
                        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    ).encode("ascii"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        if file_bytes is not None:
            sections.extend(
                [
                    f"--{boundary}\r\n".encode("ascii"),
                    (
                        'Content-Disposition: form-data; name="image"; '
                        f'filename="{filename}"\r\n'
                    ).encode("utf-8"),
                    f"Content-Type: {file_content_type}\r\n\r\n".encode("ascii"),
                    file_bytes,
                    b"\r\n",
                ]
            )
        sections.append(f"--{boundary}--\r\n".encode("ascii"))
        return self.request(
            method,
            path,
            b"".join(sections),
            f"multipart/form-data; boundary={boundary}",
            token,
        )


class PrescriptionMedicineFoundationTest(unittest.TestCase):
    def setUp(self):
        self.database_signatures = _database_signatures()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="eldercare-task12a-test-"
        )
        self.original_private_directory = image_storage.PRIVATE_UPLOAD_DIR
        image_storage.PRIVATE_UPLOAD_DIR = (
            Path(self.temporary_directory.name) / "private_uploads"
        ).resolve()

        app = FastAPI()
        app.add_middleware(PrescriptionUploadLimitMiddleware)
        app.include_router(auth.router)
        app.include_router(patients.router)
        app.include_router(prescriptions.router)
        app.include_router(medicines.router)

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = RawRequestHarness(app)

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        image_storage.PRIVATE_UPLOAD_DIR = self.original_private_directory
        self.temporary_directory.cleanup()
        self.assertEqual(self.database_signatures, _database_signatures())

    def _register(self, label):
        return create_verified_caregiver_session(
            self.session,
            name=f"Caregiver {label}",
            identity=f"task12a-{label}@example.invalid",
            password=f"secure-password-{label}",
        )

    def _patient(self, caregiver_id, token, label):
        status, body, _ = self.client.json(
            "POST",
            "/patients/",
            {
                "caregiver_id": caregiver_id,
                "name": f"Patient {label}",
                "age": 70,
                "gender": "Other",
            },
            token,
        )
        self.assertEqual(status, 200)
        return body["patient_id"]

    def _prescription(self, patient_id, token):
        status, body, _ = self.client.multipart(
            "POST",
            "/prescriptions/",
            {"patient_id": patient_id, "doctor_name": "Test Doctor"},
            token,
        )
        self.assertEqual(status, 200)
        self.assertFalse(body["has_image"])
        self.assertNotIn("image_path", body)
        return body["prescription_id"]

    def _image_bytes(self, image_format):
        from PIL import Image

        output = io.BytesIO()
        Image.new("RGB", (4, 3), color=(20, 120, 80)).save(
            output,
            format=image_format,
        )
        return output.getvalue()

    def test_all_existing_endpoints_require_authentication(self):
        requests = (
            ("GET", "/prescriptions/", None),
            ("GET", "/prescriptions/patient/1", None),
            ("GET", "/prescriptions/1", None),
            ("GET", "/prescriptions/1/image", None),
            ("POST", "/prescriptions/1/confirm", {"medicines": [{"name": "A"}]}),
            ("GET", "/medicines/", None),
            ("GET", "/medicines/patient/1", None),
            ("GET", "/medicines/prescription/1", None),
            ("POST", "/medicines/", {"patient_id": 1, "name": "A"}),
        )
        for method, path, payload in requests:
            with self.subTest(method=method, path=path):
                status, _, _ = self.client.json(method, path, payload)
                self.assertEqual(status, 401)

        status, _, _ = self.client.multipart(
            "POST",
            "/prescriptions/",
            {"patient_id": 1},
        )
        self.assertEqual(status, 401)

    def test_fresh_sqlite_schema_has_expected_indexes_foreign_keys_and_triggers(self):
        trigger_names = {
            row[0]
            for row in self.session.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            ).all()
        }
        self.assertTrue(
            set(MEDICINE_PRESCRIPTION_TRIGGER_SQL).issubset(trigger_names)
        )

        prescription_indexes = {
            row[1]
            for row in self.session.execute(
                text("PRAGMA index_list('prescriptions')")
            ).all()
        }
        medicine_indexes = {
            row[1]
            for row in self.session.execute(text("PRAGMA index_list('medicines')")).all()
        }
        self.assertIn("idx_prescriptions_patient_id", prescription_indexes)
        self.assertTrue(
            {
                "idx_medicines_patient_id",
                "idx_medicines_prescription_id",
            }.issubset(medicine_indexes),
        )

        patient_foreign_keys = self.session.execute(
            text("PRAGMA foreign_key_list('patients')")
        ).all()
        prescription_foreign_keys = self.session.execute(
            text("PRAGMA foreign_key_list('prescriptions')")
        ).all()
        medicine_foreign_keys = self.session.execute(
            text("PRAGMA foreign_key_list('medicines')")
        ).all()
        self.assertEqual(patient_foreign_keys[0][5], "CASCADE")
        self.assertEqual(prescription_foreign_keys[0][5], "CASCADE")
        self.assertEqual(
            {row[5] for row in medicine_foreign_keys},
            {"CASCADE"},
        )

        prescription_types = {
            row[1]: row[2]
            for row in self.session.execute(
                text("PRAGMA table_info('prescriptions')")
            ).all()
        }
        medicine_types = {
            row[1]: row[2]
            for row in self.session.execute(text("PRAGMA table_info('medicines')")).all()
        }
        self.assertEqual(
            {name: prescription_types[name] for name in PRESCRIPTION_COLUMNS},
            PRESCRIPTION_COLUMNS,
        )
        self.assertEqual(
            {name: medicine_types[name] for name in MEDICINE_COLUMNS},
            MEDICINE_COLUMNS,
        )

    def test_preparser_request_limit_rejects_declared_and_streamed_oversize(self):
        caregiver_id, token = self._register("request-limit")
        self._patient(caregiver_id, token, "request-limit")
        oversized = b"x" * (MAX_PRESCRIPTION_UPLOAD_REQUEST_BYTES + 1)

        status, body, _ = self.client.request(
            "POST",
            "/prescriptions/",
            oversized,
            "multipart/form-data; boundary=invalid",
            token,
        )
        self.assertEqual(status, 413)
        self.assertEqual(body["detail"], "Prescription upload request is too large.")

        status, body, _ = self.client.request(
            "POST",
            "/prescriptions/",
            oversized,
            "multipart/form-data; boundary=invalid",
            token,
            include_content_length=False,
        )
        self.assertEqual(status, 413)
        self.assertEqual(body["detail"], "Prescription upload request is too large.")
        self.assertEqual(self.session.query(models.Prescription).count(), 0)

    def test_cross_owner_and_cross_patient_manipulation_are_denied(self):
        caregiver_a, token_a = self._register("owner-a")
        caregiver_b, token_b = self._register("owner-b")
        patient_a1 = self._patient(caregiver_a, token_a, "a1")
        patient_a2 = self._patient(caregiver_a, token_a, "a2")
        patient_b = self._patient(caregiver_b, token_b, "b")
        prescription_a = self._prescription(patient_a1, token_a)

        status, _, _ = self.client.multipart(
            "POST", "/prescriptions/", {"patient_id": patient_b}, token_a
        )
        self.assertEqual(status, 404)
        status, _, _ = self.client.json(
            "GET", f"/prescriptions/{prescription_a}", token=token_b
        )
        self.assertEqual(status, 404)
        status, body, _ = self.client.json(
            "GET", "/prescriptions/", token=token_b
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, [])

        status, _, _ = self.client.json(
            "POST",
            "/medicines/",
            {
                "patient_id": patient_a2,
                "prescription_id": prescription_a,
                "name": "Cross-linked medicine",
            },
            token_a,
        )
        self.assertEqual(status, 404)
        status, _, _ = self.client.json(
            "POST",
            "/medicines/",
            {"patient_id": patient_a1, "name": "Owned medicine"},
            token_a,
        )
        self.assertEqual(status, 200)

        status, body, _ = self.client.json("GET", "/medicines/", token=token_b)
        self.assertEqual(status, 200)
        self.assertEqual(body, [])
        status, _, _ = self.client.json(
            "GET", f"/medicines/patient/{patient_a1}", token=token_b
        )
        self.assertEqual(status, 404)

    def test_confirmation_is_atomic_idempotent_and_patient_is_server_derived(self):
        caregiver_id, token = self._register("confirm")
        patient_id = self._patient(caregiver_id, token, "confirm")
        prescription_id = self._prescription(patient_id, token)
        payload = {
            "medicines": [
                {
                    "name": "Medicine One",
                    "strength": "500 mg",
                    "dosage": "1 tablet",
                    "frequency": "Twice daily",
                    "duration": "5 days",
                    "instructions": "Take after food",
                },
                {"name": "Medicine Two", "frequency": "At night"},
            ]
        }

        status, body, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/confirm", payload, token
        )
        self.assertEqual(status, 200)
        self.assertFalse(body["already_confirmed"])
        self.assertEqual(len(body["medicines"]), 2)
        self.assertEqual(
            {medicine["patient_id"] for medicine in body["medicines"]},
            {patient_id},
        )

        status, repeated, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/confirm", payload, token
        )
        self.assertEqual(status, 200)
        self.assertTrue(repeated["already_confirmed"])
        self.assertEqual(self.session.query(models.Medicine).count(), 2)

        status, body, _ = self.client.json(
            "POST",
            "/medicines/",
            {
                "patient_id": patient_id,
                "prescription_id": prescription_id,
                "name": "Late linked medicine",
            },
            token,
        )
        self.assertEqual(status, 409)
        self.assertEqual(
            body["detail"],
            "Confirmed prescription medicines cannot be changed.",
        )
        self.assertEqual(self.session.query(models.Medicine).count(), 2)

        changed = {"medicines": [{"name": "Different medicine"}]}
        status, _, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/confirm", changed, token
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.session.query(models.Medicine).count(), 2)

        another_prescription = self._prescription(patient_id, token)
        invalid_payload = {
            "medicines": [{"name": "Valid"}, {"name": "   "}]
        }
        status, _, _ = self.client.json(
            "POST",
            f"/prescriptions/{another_prescription}/confirm",
            invalid_payload,
            token,
        )
        self.assertEqual(status, 422)
        self.assertEqual(
            self.session.query(models.Medicine)
            .filter(models.Medicine.prescription_id == another_prescription)
            .count(),
            0,
        )

    def test_legacy_manually_linked_medicines_are_not_duplicated_by_confirm(self):
        caregiver_id, token = self._register("legacy")
        patient_id = self._patient(caregiver_id, token, "legacy")
        prescription_id = self._prescription(patient_id, token)
        status, _, _ = self.client.json(
            "POST",
            "/medicines/",
            {
                "patient_id": patient_id,
                "prescription_id": prescription_id,
                "name": "Legacy medicine",
            },
            token,
        )
        self.assertEqual(status, 200)
        status, _, _ = self.client.json(
            "POST",
            f"/prescriptions/{prescription_id}/confirm",
            {"medicines": [{"name": "Legacy medicine"}]},
            token,
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.session.query(models.Medicine).count(), 1)

    @unittest.skipUnless(PIL_AVAILABLE, "Pillow dependency is not installed")
    def test_valid_images_are_sanitized_privately_and_retrieved_by_owner(self):
        caregiver_a, token_a = self._register("image-a")
        caregiver_b, token_b = self._register("image-b")
        patient_a = self._patient(caregiver_a, token_a, "image-a")
        for image_format, expected_mime in (
            ("JPEG", "image/jpeg"),
            ("PNG", "image/png"),
        ):
            with self.subTest(image_format=image_format):
                status, body, _ = self.client.multipart(
                    "POST",
                    "/prescriptions/",
                    {"patient_id": patient_a},
                    token_a,
                    self._image_bytes(image_format),
                    filename="../../private/attack.txt",
                    file_content_type="text/plain",
                )
                self.assertEqual(status, 200)
                self.assertTrue(body["has_image"])
                prescription = self.session.get(
                    models.Prescription,
                    body["prescription_id"],
                )
                self.assertRegex(
                    prescription.image_path,
                    r"^[0-9a-f]{32}\.(jpg|png)$",
                )
                self.assertEqual(prescription.image_mime_type, expected_mime)
                self.assertEqual(prescription.image_original_name, "attack.txt")
                stored_path = image_storage.PRIVATE_UPLOAD_DIR / prescription.image_path
                self.assertTrue(stored_path.is_file())

                status, raw_image, headers = self.client.request(
                    "GET",
                    f"/prescriptions/{prescription.id}/image",
                    token=token_a,
                )
                self.assertEqual(status, 200)
                self.assertTrue(raw_image)
                self.assertEqual(headers["content-type"], expected_mime)
                self.assertEqual(headers["x-content-type-options"], "nosniff")
                status, _, _ = self.client.request(
                    "GET",
                    f"/prescriptions/{prescription.id}/image",
                    token=token_b,
                )
                self.assertEqual(status, 404)

    @unittest.skipUnless(PIL_AVAILABLE, "Pillow dependency is not installed")
    def test_invalid_malformed_and_oversized_uploads_are_rejected(self):
        caregiver_id, token = self._register("invalid-image")
        patient_id = self._patient(caregiver_id, token, "invalid-image")
        for payload in (b"plain text disguised as JPEG", b"\x89PNG\r\n\x1a\nmalformed"):
            status, _, _ = self.client.multipart(
                "POST",
                "/prescriptions/",
                {"patient_id": patient_id},
                token,
                payload,
                filename="fake.jpg",
                file_content_type="image/jpeg",
            )
            self.assertEqual(status, 400)

        status, _, _ = self.client.multipart(
            "POST",
            "/prescriptions/",
            {"patient_id": patient_id},
            token,
            b"x" * (image_storage.MAX_IMAGE_BYTES + 1),
            filename="large.jpg",
            file_content_type="image/jpeg",
        )
        self.assertEqual(status, 413)
        self.assertEqual(self.session.query(models.Prescription).count(), 0)

    @unittest.skipUnless(PIL_AVAILABLE, "Pillow dependency is not installed")
    def test_database_failure_removes_the_new_private_image(self):
        class FailingSession:
            def add(self, _value):
                pass

            def commit(self):
                raise RuntimeError("simulated commit failure")

            def rollback(self):
                pass

        upload = UploadFile(
            file=io.BytesIO(self._image_bytes("PNG")),
            filename="prescription.png",
        )
        caregiver = models.Caregiver(id=1, name="A", phone_or_email="a", password="x")
        with patch(
            "routers.prescriptions.get_owned_patient",
            return_value=models.Patient(id=1, caregiver_id=1, name="P", age=70),
        ):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(
                    prescriptions.create_prescription(
                        patient_id=1,
                        doctor_name=None,
                        note=None,
                        image=upload,
                        db=FailingSession(),
                        caregiver=caregiver,
                    )
                )
        self.assertEqual(context.exception.status_code, 500)
        stored_files = (
            list(image_storage.PRIVATE_UPLOAD_DIR.iterdir())
            if image_storage.PRIVATE_UPLOAD_DIR.exists()
            else []
        )
        self.assertEqual(stored_files, [])


class PrescriptionFoundationMigrationTest(unittest.TestCase):
    def setUp(self):
        self.database_signatures = _database_signatures()
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="eldercare-task12a-migration-"
        )
        self.database_path = Path(self.temporary_directory.name) / "eldercare_bd.db"
        self.backup_path = Path(self.temporary_directory.name) / "verified.backup.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE caregivers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                phone_or_email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                created_at DATETIME
            );
            CREATE TABLE patients (
                id INTEGER PRIMARY KEY,
                caregiver_id INTEGER,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                gender TEXT,
                created_at DATETIME,
                FOREIGN KEY(caregiver_id) REFERENCES caregivers(id)
                    ON UPDATE CASCADE ON DELETE SET NULL
            );
            CREATE TABLE prescriptions (
                id INTEGER PRIMARY KEY,
                patient_id INTEGER NOT NULL,
                doctor_name TEXT,
                note TEXT,
                image_path TEXT,
                created_at DATETIME,
                FOREIGN KEY(patient_id) REFERENCES patients(id)
                    ON UPDATE CASCADE ON DELETE CASCADE
            );
            CREATE TABLE medicines (
                id INTEGER PRIMARY KEY,
                patient_id INTEGER NOT NULL,
                prescription_id INTEGER,
                name TEXT NOT NULL,
                dosage TEXT,
                frequency TEXT,
                quantity INTEGER,
                daily_dose INTEGER,
                start_date TEXT,
                run_out_date TEXT,
                alert_date TEXT,
                note TEXT,
                created_at DATETIME,
                FOREIGN KEY(patient_id) REFERENCES patients(id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY(prescription_id) REFERENCES prescriptions(id)
                    ON UPDATE CASCADE ON DELETE SET NULL
            );
            CREATE INDEX idx_prescriptions_patient_id
                ON prescriptions(patient_id);
            CREATE INDEX idx_medicines_patient_id
                ON medicines(patient_id);
            CREATE INDEX idx_medicines_prescription_id
                ON medicines(prescription_id);
            INSERT INTO caregivers (id, name, phone_or_email, password)
            VALUES (1, 'Migration caregiver', 'migration@example.invalid', 'test');
            INSERT INTO patients (id, caregiver_id, name, age)
            VALUES (1, 1, 'A', 70), (2, 1, 'B', 71);
            INSERT INTO prescriptions (id, patient_id, doctor_name, note)
            VALUES (1, 1, 'Historical doctor', 'Historical note');
            INSERT INTO medicines (
                id, patient_id, prescription_id, name, dosage, frequency
            ) VALUES (1, 1, 1, 'Historical medicine', '1 tablet', 'Daily');
            """
        )
        connection.close()
        self.patient_a = 1
        self.patient_b = 2
        self.prescription_id = 1
        shutil.copy2(self.database_path, self.backup_path)

    def tearDown(self):
        self.temporary_directory.cleanup()
        self.assertEqual(self.database_signatures, _database_signatures())

    def test_migration_is_additive_idempotent_and_adds_integrity_triggers(self):
        first = migrate_prescription_foundation(
            self.database_path,
            self.backup_path,
        )
        second = migrate_prescription_foundation(
            self.database_path,
            self.backup_path,
        )
        self.assertTrue(first["record_ids_and_values_preserved"])
        self.assertTrue(second["record_ids_and_values_preserved"])
        self.assertTrue(first["applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(
            set(first["added_prescription_columns"]),
            {
                "image_original_name",
                "image_mime_type",
                "image_size_bytes",
                "image_sha256",
                "ocr_text",
                "ocr_status",
                "ocr_engine",
                "ocr_error",
                "confirmed_at",
                "confirmation_hash",
            },
        )
        self.assertEqual(
            set(first["added_medicine_columns"]),
            {"strength", "duration", "instructions"},
        )
        self.assertEqual(second["added_prescription_columns"], [])
        self.assertEqual(second["added_medicine_columns"], [])
        self.assertEqual(
            set(first["created_triggers"]),
            set(MEDICINE_PRESCRIPTION_TRIGGER_SQL),
        )

        connection = sqlite3.connect(self.database_path)
        historical = connection.execute(
            """
            SELECT p.id, p.doctor_name, p.note, m.id, m.name
            FROM prescriptions p
            JOIN medicines m ON m.prescription_id = p.id
            WHERE p.id = 1
            """
        ).fetchone()
        self.assertEqual(
            historical,
            (1, "Historical doctor", "Historical note", 1, "Historical medicine"),
        )
        self.assertEqual(
            {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list('prescriptions')"
                ).fetchall()
            },
            {"idx_prescriptions_patient_id"},
        )
        self.assertEqual(
            {
                row[1]
                for row in connection.execute("PRAGMA index_list('medicines')").fetchall()
            },
            {
                "idx_medicines_patient_id",
                "idx_medicines_prescription_id",
            },
        )
        prescription_types = {
            row[1]: row[2]
            for row in connection.execute(
                "PRAGMA table_info('prescriptions')"
            ).fetchall()
        }
        medicine_types = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info('medicines')").fetchall()
        }
        self.assertEqual(
            {name: prescription_types[name] for name in PRESCRIPTION_COLUMNS},
            PRESCRIPTION_COLUMNS,
        )
        self.assertEqual(
            {name: medicine_types[name] for name in MEDICINE_COLUMNS},
            MEDICINE_COLUMNS,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO medicines (patient_id, prescription_id, name)
                VALUES (?, ?, ?)
                """,
                (self.patient_b, self.prescription_id, "Cross-linked"),
            )
        connection.rollback()
        connection.execute(
            """
            INSERT INTO medicines (patient_id, prescription_id, name)
            VALUES (?, NULL, ?)
            """,
            (self.patient_b, "New standalone medicine"),
        )
        connection.commit()
        connection.close()

        before_rerun = hashlib.sha256(self.database_path.read_bytes()).hexdigest()
        after_new_records = migrate_prescription_foundation(
            self.database_path,
            self.backup_path,
        )
        after_rerun = hashlib.sha256(self.database_path.read_bytes()).hexdigest()
        self.assertFalse(after_new_records["applied"])
        self.assertEqual(before_rerun, after_rerun)

    def test_partial_migration_is_refused_without_further_changes(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "ALTER TABLE prescriptions ADD COLUMN image_original_name TEXT"
        )
        connection.commit()
        connection.close()
        before = hashlib.sha256(self.database_path.read_bytes()).hexdigest()

        with self.assertRaisesRegex(RuntimeError, "Partial"):
            migrate_prescription_foundation(
                self.database_path,
                self.backup_path,
            )

        self.assertEqual(
            before,
            hashlib.sha256(self.database_path.read_bytes()).hexdigest(),
        )

    def test_each_schema_mutation_rolls_back_to_exact_original_bytes(self):
        steps = [
            *(f"column:prescriptions.{name}" for name in PRESCRIPTION_COLUMNS),
            *(f"column:medicines.{name}" for name in MEDICINE_COLUMNS),
            *(f"trigger:{name}" for name in MEDICINE_PRESCRIPTION_TRIGGER_SQL),
            "marker:table",
            "marker:row",
        ]
        original_hash = hashlib.sha256(self.backup_path.read_bytes()).hexdigest()

        for step in steps:
            with self.subTest(step=step):
                shutil.copy2(self.backup_path, self.database_path)

                def fail_at_step(current_step, target=step):
                    if current_step == target:
                        raise RuntimeError(f"injected failure at {target}")

                with self.assertRaisesRegex(RuntimeError, "injected failure"):
                    migrate_prescription_foundation(
                        self.database_path,
                        self.backup_path,
                        failure_injector=fail_at_step,
                    )
                self.assertEqual(
                    original_hash,
                    hashlib.sha256(self.database_path.read_bytes()).hexdigest(),
                )

    def test_begin_immediate_is_held_before_image_preflight(self):
        original_image_manifest = prescription_foundation_migration._image_manifest
        lock_observed = []

        def inspect_lock(connection, database_path):
            if not lock_observed:
                contender = sqlite3.connect(database_path, timeout=0)
                try:
                    contender.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    lock_observed.append("locked" in str(exc).lower())
                else:
                    contender.rollback()
                    lock_observed.append(False)
                finally:
                    contender.close()
            return original_image_manifest(connection, database_path)

        with patch(
            "prescription_foundation_migration._image_manifest",
            side_effect=inspect_lock,
        ):
            migrate_prescription_foundation(self.database_path, self.backup_path)

        self.assertEqual(lock_observed, [True])

    def test_database_change_before_lock_is_detected_without_migration_writes(self):
        original_sha256_file = prescription_foundation_migration._sha256_file
        database_hash_calls = 0

        def change_after_initial_hash(path):
            nonlocal database_hash_calls
            result = original_sha256_file(path)
            if Path(path).resolve() == self.database_path.resolve():
                database_hash_calls += 1
                if database_hash_calls == 1:
                    writer = sqlite3.connect(self.database_path)
                    writer.execute(
                        "UPDATE prescriptions SET note = 'Concurrent writer' WHERE id = 1"
                    )
                    writer.commit()
                    writer.close()
            return result

        with patch(
            "prescription_foundation_migration._sha256_file",
            side_effect=change_after_initial_hash,
        ):
            with self.assertRaisesRegex(RuntimeError, "changed before"):
                migrate_prescription_foundation(self.database_path, self.backup_path)

        connection = sqlite3.connect(self.database_path)
        note = connection.execute(
            "SELECT note FROM prescriptions WHERE id = 1"
        ).fetchone()[0]
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('prescriptions')").fetchall()
        }
        connection.close()
        self.assertEqual(note, "Concurrent writer")
        self.assertTrue(set(PRESCRIPTION_COLUMNS).isdisjoint(columns))

    def test_historical_image_path_escape_is_refused_without_database_changes(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "UPDATE prescriptions SET image_path = '../outside.jpg' WHERE id = 1"
        )
        connection.commit()
        connection.close()
        shutil.copy2(self.database_path, self.backup_path)
        before = hashlib.sha256(self.database_path.read_bytes()).hexdigest()

        with self.assertRaisesRegex(RuntimeError, "outside storage"):
            migrate_prescription_foundation(self.database_path, self.backup_path)

        self.assertEqual(
            before,
            hashlib.sha256(self.database_path.read_bytes()).hexdigest(),
        )

    @unittest.skipUnless(PIL_AVAILABLE, "Pillow dependency is not installed")
    def test_invalid_historical_image_is_refused_without_database_changes(self):
        uploads = self.database_path.parent / "uploads"
        uploads.mkdir()
        (uploads / "invalid.jpg").write_bytes(b"not a decodable image")
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "UPDATE prescriptions SET image_path = 'uploads/invalid.jpg' WHERE id = 1"
        )
        connection.commit()
        connection.close()
        shutil.copy2(self.database_path, self.backup_path)
        before = hashlib.sha256(self.database_path.read_bytes()).hexdigest()

        with self.assertRaisesRegex(RuntimeError, "fully decoded"):
            migrate_prescription_foundation(self.database_path, self.backup_path)

        self.assertEqual(
            before,
            hashlib.sha256(self.database_path.read_bytes()).hexdigest(),
        )

    def test_oversized_historical_image_is_refused_without_database_changes(self):
        uploads = self.database_path.parent / "uploads"
        uploads.mkdir()
        with (uploads / "oversized.jpg").open("wb") as output:
            output.seek(image_storage.MAX_IMAGE_BYTES)
            output.write(b"x")
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "UPDATE prescriptions SET image_path = 'uploads/oversized.jpg' WHERE id = 1"
        )
        connection.commit()
        connection.close()
        shutil.copy2(self.database_path, self.backup_path)
        before = hashlib.sha256(self.database_path.read_bytes()).hexdigest()

        with self.assertRaisesRegex(RuntimeError, "byte limit"):
            migrate_prescription_foundation(self.database_path, self.backup_path)

        self.assertEqual(
            before,
            hashlib.sha256(self.database_path.read_bytes()).hexdigest(),
        )

    @unittest.skipUnless(PIL_AVAILABLE, "Pillow dependency is not installed")
    def test_valid_historical_image_is_fully_decoded_and_backfilled_atomically(self):
        from PIL import Image

        uploads = self.database_path.parent / "uploads"
        uploads.mkdir()
        image_path = uploads / "historical.jpg"
        Image.new("RGB", (7, 5), color=(15, 90, 60)).save(image_path, format="JPEG")
        expected_bytes = image_path.read_bytes()
        expected_sha256 = hashlib.sha256(expected_bytes).hexdigest()

        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "UPDATE prescriptions SET image_path = 'uploads/historical.jpg' WHERE id = 1"
        )
        connection.commit()
        connection.close()
        shutil.copy2(self.database_path, self.backup_path)
        original_hash = hashlib.sha256(self.database_path.read_bytes()).hexdigest()

        def fail_after_backfill(step):
            if step == "image_metadata:1":
                raise RuntimeError("injected image backfill failure")

        with self.assertRaisesRegex(RuntimeError, "image backfill failure"):
            migrate_prescription_foundation(
                self.database_path,
                self.backup_path,
                failure_injector=fail_after_backfill,
            )
        self.assertEqual(
            original_hash,
            hashlib.sha256(self.database_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(image_path.read_bytes(), expected_bytes)

        result = migrate_prescription_foundation(self.database_path, self.backup_path)
        self.assertTrue(result["applied"])
        connection = sqlite3.connect(self.database_path)
        metadata = connection.execute(
            """
            SELECT image_original_name, image_mime_type, image_size_bytes, image_sha256
            FROM prescriptions WHERE id = 1
            """
        ).fetchone()
        connection.close()
        self.assertEqual(
            metadata,
            (None, "image/jpeg", len(expected_bytes), expected_sha256),
        )
        self.assertEqual(image_path.read_bytes(), expected_bytes)

    def test_confirmed_prescription_trigger_closes_concurrent_insert_window(self):
        migrate_prescription_foundation(self.database_path, self.backup_path)
        setup = sqlite3.connect(self.database_path)
        setup.execute(
            "INSERT INTO prescriptions (id, patient_id, doctor_name) VALUES (2, 1, 'D')"
        )
        setup.commit()
        setup.close()

        confirming = sqlite3.connect(self.database_path, timeout=5)
        confirming.execute("PRAGMA foreign_keys = ON")
        confirming.execute("BEGIN IMMEDIATE")
        confirming.execute(
            """
            UPDATE prescriptions SET confirmation_hash = ?
            WHERE id = 2 AND confirmed_at IS NULL AND confirmation_hash IS NULL
            """,
            ("a" * 64,),
        )

        insert_started = threading.Event()

        def concurrent_insert():
            connection = sqlite3.connect(self.database_path, timeout=5)
            connection.execute("PRAGMA foreign_keys = ON")
            insert_started.set()
            try:
                connection.execute(
                    """
                    INSERT INTO medicines (patient_id, prescription_id, name)
                    VALUES (1, 2, 'Racing medicine')
                    """
                )
                connection.commit()
                return "inserted"
            except sqlite3.IntegrityError:
                connection.rollback()
                return "blocked"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(concurrent_insert)
            self.assertTrue(insert_started.wait(timeout=2))
            confirming.execute(
                """
                INSERT INTO medicines (patient_id, prescription_id, name)
                VALUES (1, 2, 'Confirmed medicine')
                """
            )
            confirming.execute(
                """
                UPDATE prescriptions
                SET confirmed_at = '2026-08-23T00:00:00', ocr_status = 'confirmed'
                WHERE id = 2 AND confirmation_hash = ?
                """,
                ("a" * 64,),
            )
            confirming.commit()
            confirming.close()
            self.assertEqual(future.result(timeout=5), "blocked")

        verification = sqlite3.connect(self.database_path)
        names = [
            row[0]
            for row in verification.execute(
                "SELECT name FROM medicines WHERE prescription_id = 2 ORDER BY id"
            ).fetchall()
        ]
        verification.close()
        self.assertEqual(names, ["Confirmed medicine"])

    def test_migration_refuses_secondary_database_name(self):
        secondary = Path(self.temporary_directory.name) / "eldercare_bd_2.db"
        shutil.copy2(self.database_path, secondary)
        with self.assertRaisesRegex(RuntimeError, "Refusing"):
            migrate_prescription_foundation(secondary, self.backup_path)

    def test_migration_refuses_hardlinked_backup_or_secondary(self):
        original_hash = hashlib.sha256(self.database_path.read_bytes()).hexdigest()
        self.backup_path.unlink()
        try:
            os.link(self.database_path, self.backup_path)
        except OSError as exc:
            self.skipTest(f"Hard links are unavailable: {exc}")

        with self.assertRaisesRegex(RuntimeError, "Backup must be a separate file"):
            migrate_prescription_foundation(self.database_path, self.backup_path)
        self.assertEqual(
            original_hash,
            hashlib.sha256(self.database_path.read_bytes()).hexdigest(),
        )

        self.backup_path.unlink()
        shutil.copy2(self.database_path, self.backup_path)
        secondary = self.database_path.with_name("eldercare_bd_2.db")
        os.link(self.database_path, secondary)
        with self.assertRaisesRegex(RuntimeError, "Secondary database must be a separate"):
            migrate_prescription_foundation(self.database_path, self.backup_path)
        self.assertEqual(
            original_hash,
            hashlib.sha256(self.database_path.read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
