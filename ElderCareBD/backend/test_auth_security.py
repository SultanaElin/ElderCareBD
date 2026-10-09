import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base, get_db
from migrate_auth_security import migrate_auth_security
from otp_delivery import CaptureOtpDeliveryProvider
from routers import assessments, auth, patients
from security import is_password_hash, verify_password
from test_core_workflow import FastApiRequestHarness, _database_signatures


TEST_OTP_SECRET = "task15-auth-test-hmac-secret-32-characters-minimum"


class AuthenticationSecurityTest(unittest.TestCase):
    def setUp(self):
        self.database_signatures = _database_signatures()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
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

    def _assert_no_stored_secrets(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                self.assertNotIn(
                    key,
                    {
                        "password",
                        "password_hash",
                        "token_hash",
                        "otp",
                        "otp_digest",
                        "otp_salt",
                    },
                )
                self._assert_no_stored_secrets(child)
        elif isinstance(value, list):
            for child in value:
                self._assert_no_stored_secrets(child)

    def _register(self, label):
        password = f"secure-password-{label.lower()}"
        status, body = self.client.request(
            "POST",
            "/auth/register-caregiver",
            {
                "name": f"Secure Caregiver {label}",
                "phone_or_email": f"secure-{label.lower()}@example.invalid",
                "password": password,
            },
        )
        self.assertEqual(status, 202)
        self._assert_no_stored_secrets(body)
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
        self._assert_no_stored_secrets(verification)
        self.assertNotIn("access_token", verification)
        status, login = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": f"secure-{label.lower()}@example.invalid",
                "password": password,
            },
        )
        self.assertEqual(status, 200)
        self._assert_no_stored_secrets(login)
        return login, password

    def _create_patient(self, caregiver_id, token, label):
        status, body = self.client.request(
            "POST",
            "/patients/",
            {
                "caregiver_id": caregiver_id,
                "name": f"Owned Patient {label}",
                "age": 72,
                "gender": "Other",
            },
            token=token,
        )
        self.assertEqual(status, 200)
        return body["patient_id"]

    def _assessment_payload(self, patient_id):
        return {
            "patient_id": patient_id,
            "age": 72,
            "glucose": 165,
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
            "note": "Security ownership test note",
            "diabetes_risk": "High",
            "heart_risk": "Moderate",
            "overall_risk": "High",
            "recommendation": "Arrange a clinical review.",
        }

    def test_registration_hashes_password_and_session_token(self):
        body, password = self._register("Hash")
        caregiver = self.session.get(models.Caregiver, body["caregiver_id"])

        self.assertNotEqual(caregiver.password, password)
        self.assertTrue(is_password_hash(caregiver.password))
        self.assertTrue(verify_password(password, caregiver.password))

        stored_session = self.session.query(models.CaregiverSession).one()
        self.assertNotEqual(stored_session.token_hash, body["access_token"])
        self.assertEqual(
            stored_session.token_hash,
            hashlib.sha256(body["access_token"].encode("utf-8")).hexdigest(),
        )

        status, login = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "secure-hash@example.invalid",
                "password": password,
            },
        )
        self.assertEqual(status, 200)
        self._assert_no_stored_secrets(login)

        status, logout = self.client.request(
            "POST",
            "/auth/logout",
            {},
            token=login["access_token"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(logout["message"], "Logout successful")

        status, _ = self.client.request(
            "GET",
            "/patients/",
            token=login["access_token"],
        )
        self.assertEqual(status, 401)

        status, failure = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "secure-hash@example.invalid",
                "password": "incorrect-password",
            },
        )
        self.assertEqual(status, 401)
        self.assertEqual(failure["detail"], "Invalid login credentials")

    def test_legacy_plaintext_password_is_upgraded_after_successful_login(self):
        legacy_password = "legacy-password"
        caregiver = models.Caregiver(
            name="Legacy Caregiver",
            phone_or_email="legacy@example.invalid",
            password=legacy_password,
            verification_status="verified",
        )
        self.session.add(caregiver)
        self.session.commit()
        self.session.refresh(caregiver)

        status, _ = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "legacy@example.invalid",
                "password": "incorrect-password",
            },
        )
        self.assertEqual(status, 401)
        self.assertEqual(caregiver.password, legacy_password)

        status, body = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "legacy@example.invalid",
                "password": legacy_password,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["access_token"])
        self.assertNotEqual(caregiver.password, legacy_password)
        self.assertTrue(is_password_hash(caregiver.password))
        self.assertTrue(verify_password(legacy_password, caregiver.password))

    def test_authentication_and_cross_caregiver_ownership_are_enforced(self):
        caregiver_a, _ = self._register("A")
        caregiver_b, _ = self._register("B")
        caregiver_a_id = caregiver_a["caregiver_id"]
        caregiver_b_id = caregiver_b["caregiver_id"]
        token_a = caregiver_a["access_token"]
        token_b = caregiver_b["access_token"]
        patient_a = self._create_patient(caregiver_a_id, token_a, "A")

        status, _ = self.client.request(
            "GET",
            f"/patients/caregiver/{caregiver_a_id}",
        )
        self.assertEqual(status, 401)

        status, _ = self.client.request(
            "GET",
            f"/patients/caregiver/{caregiver_a_id}",
            token="invalid-token",
        )
        self.assertEqual(status, 401)

        status, owned_patient = self.client.request(
            "GET",
            f"/patients/{patient_a}",
            token=token_a,
        )
        self.assertEqual(status, 200)
        self.assertEqual(owned_patient["caregiver_id"], caregiver_a_id)

        status, _ = self.client.request(
            "GET",
            f"/patients/{patient_a}",
            token=token_b,
        )
        self.assertEqual(status, 404)

        status, _ = self.client.request(
            "GET",
            f"/patients/caregiver/{caregiver_a_id}",
            token=token_b,
        )
        self.assertEqual(status, 404)

        patient_count = self.session.query(models.Patient).count()
        status, _ = self.client.request(
            "POST",
            "/patients/",
            {
                "caregiver_id": caregiver_b_id,
                "name": "Manipulated owner",
                "age": 72,
                "gender": "Other",
            },
            token=token_a,
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.session.query(models.Patient).count(), patient_count)

        assessment_payload = self._assessment_payload(patient_a)
        status, assessment = self.client.request(
            "POST",
            "/assessments/",
            assessment_payload,
            token=token_a,
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(assessment["assessment_id"], int)

        status, _ = self.client.request(
            "POST",
            "/assessments/",
            assessment_payload,
            token=token_b,
        )
        self.assertEqual(status, 404)

        status, history = self.client.request(
            "GET",
            f"/assessments/patient/{patient_a}",
            token=token_a,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(history), 1)

        status, _ = self.client.request(
            "GET",
            f"/assessments/patient/{patient_a}",
            token=token_b,
        )
        self.assertEqual(status, 404)

        status, caregiver_b_assessments = self.client.request(
            "GET",
            "/assessments/",
            token=token_b,
        )
        self.assertEqual(status, 200)
        self.assertEqual(caregiver_b_assessments, [])

    def test_auth_migration_hashes_legacy_rows_in_a_disposable_database(self):
        with tempfile.TemporaryDirectory(prefix="eldercare-task10-") as temp_dir:
            database_path = Path(temp_dir) / "eldercare_bd.db"
            backup_path = Path(temp_dir) / "eldercare_bd.backup.db"
            migration_engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(bind=migration_engine)
            migration_session = sessionmaker(bind=migration_engine)()
            legacy = models.Caregiver(
                name="Migration Caregiver",
                phone_or_email="migration@example.invalid",
                password="migration-password",
                verification_status="verified",
            )
            migration_session.add(legacy)
            migration_session.commit()
            legacy_id = legacy.id
            migration_session.close()
            models.CaregiverSession.__table__.drop(bind=migration_engine)
            migration_engine.dispose()
            shutil.copy2(database_path, backup_path)

            result = migrate_auth_security(database_path, backup_path)

            verification_engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                connect_args={"check_same_thread": False},
            )
            verification_session = sessionmaker(bind=verification_engine)()
            migrated = verification_session.get(models.Caregiver, legacy_id)
            self.assertEqual(result["migrated_passwords"], 1)
            self.assertEqual(result["integrity"], "ok")
            self.assertEqual(result["foreign_key_issues"], 0)
            self.assertNotEqual(migrated.password, "migration-password")
            self.assertTrue(verify_password("migration-password", migrated.password))
            self.assertTrue(inspect(verification_engine).has_table("caregiver_sessions"))
            verification_session.close()
            verification_engine.dispose()


if __name__ == "__main__":
    unittest.main()
