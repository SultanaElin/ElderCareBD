import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base, get_db
from ml_model_service import (
    ModelContractError,
    ModelInferenceError,
    ModelUnavailableError,
    PredictionResult,
)
from routers import predictions
from test_core_workflow import FastApiRequestHarness


BACKEND_DIR = Path(__file__).resolve().parent
AUTHORITATIVE_DATABASES = (
    BACKEND_DIR / "eldercare_bd.db",
    BACKEND_DIR / "eldercare_bd_2.db",
)


def _database_signatures():
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        if path.exists()
        else None
        for path in AUTHORITATIVE_DATABASES
    }


class _FakeService:
    def __init__(self):
        self.diabetes_error = None
        self.heart_error = None
        self.diabetes_calls = []
        self.heart_calls = []

    def contracts(self):
        return {
            "models": {
                "diabetes": {
                    "disease": "diabetes",
                    "available": True,
                    "model_version": "3.0.0",
                    "model_name": "DiaBD screening model",
                    "prediction_source": "task13b_diabd_v3_model",
                    "threshold": 0.06,
                    "features": [],
                },
                "heart": {
                    "disease": "heart",
                    "available": True,
                    "model_version": "2.0.0",
                    "model_name": "Heart screening model",
                    "prediction_source": "task13_heart_v2_model",
                    "threshold": 0.53,
                    "features": [],
                },
            }
        }

    def predict_diabetes(self, **values):
        self.diabetes_calls.append(values)
        if self.diabetes_error is not None:
            raise self.diabetes_error
        return PredictionResult(
            disease="diabetes",
            prediction_source="task13b_diabd_v3_model",
            model_version="3.0.0",
            risk_score=0.42,
            classification="at_or_above_model_threshold",
            threshold=0.06,
            features_used={
                "age": values["age"],
                "gender": 0 if values["gender"] == "Female" else 1,
                "systolic_bp": values["systolic_bp"],
                "diastolic_bp": values["diastolic_bp"],
                "glucose": values["random_glucose_mmol_l"],
                "bmi": values["bmi"],
            },
            disclaimer="Research/demo screening score only.",
        )

    def predict_heart(self, **values):
        self.heart_calls.append(values)
        if self.heart_error is not None:
            raise self.heart_error
        return PredictionResult(
            disease="heart",
            prediction_source="task13_heart_v2_model",
            model_version="2.0.0",
            risk_score=0.2,
            classification="below_model_threshold",
            threshold=0.53,
            features_used={
                "age": values["age"],
                "sex": 1,
                "cp": 3,
                "trestbps": values["resting_systolic_bp_mm_hg"],
            },
            disclaimer="Research/demo screening score only.",
        )


class PredictionApiTest(unittest.TestCase):
    def setUp(self):
        self.database_signatures = _database_signatures()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = sessionmaker(bind=self.engine)()

        caregiver_a = models.Caregiver(
            name="Caregiver A",
            phone_or_email="prediction-a@example.invalid",
            identity_normalized="prediction-a@example.invalid",
            password="unused",
            verification_status="verified",
            verified_at=now,
            primary_verification_channel="email",
            created_at=now,
        )
        caregiver_b = models.Caregiver(
            name="Caregiver B",
            phone_or_email="prediction-b@example.invalid",
            identity_normalized="prediction-b@example.invalid",
            password="unused",
            verification_status="verified",
            verified_at=now,
            primary_verification_channel="email",
            created_at=now,
        )
        self.session.add_all([caregiver_a, caregiver_b])
        self.session.flush()
        token_hash = hashlib.sha256(b"prediction-token-a").hexdigest()
        self.session.add(
            models.CaregiverSession(
                caregiver_id=caregiver_a.id,
                token_hash=token_hash,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        owned_patient = models.Patient(
            caregiver_id=caregiver_a.id,
            name="Owned patient",
            age=65,
            gender="Female",
            created_at=now,
        )
        foreign_patient = models.Patient(
            caregiver_id=caregiver_b.id,
            name="Foreign patient",
            age=65,
            gender="Male",
            created_at=now,
        )
        self.session.add_all([owned_patient, foreign_patient])
        self.session.commit()
        self.owned_patient_id = owned_patient.id
        self.foreign_patient_id = foreign_patient.id
        self.token = "prediction-token-a"

        app = FastAPI()
        app.include_router(predictions.router)

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = FastApiRequestHarness(app)
        self.service = _FakeService()

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.assertEqual(self.database_signatures, _database_signatures())

    def _diabetes_payload(self, patient_id=None):
        return {
            "patient_id": patient_id or self.owned_patient_id,
            "age": 65,
            "gender": "Female",
            "systolic_bp": 130,
            "diastolic_bp": 80,
            "random_glucose_mmol_l": 7.2,
            "bmi": 25.0,
        }

    def _heart_payload(self, patient_id=None):
        return {
            "patient_id": patient_id or self.owned_patient_id,
            "age": 65,
            "clinical_sex": "male",
            "chest_pain_type": "asymptomatic",
            "blood_pressure_context": "resting_systolic",
            "resting_systolic_bp_mm_hg": 130,
        }

    def test_authentication_and_ownership_precede_service_access(self):
        with patch.object(
            predictions,
            "get_ml_model_service",
            return_value=self.service,
        ) as service_getter:
            status, body = self.client.request(
                "POST",
                "/predictions/diabetes",
                self._diabetes_payload(),
            )
            self.assertEqual(status, 401)
            self.assertEqual(body["detail"], "Authentication required.")
            service_getter.assert_not_called()

            status, body = self.client.request(
                "POST",
                "/predictions/diabetes",
                self._diabetes_payload(self.foreign_patient_id),
                token=self.token,
            )
            self.assertEqual(status, 404)
            self.assertEqual(body["detail"], "Resource not found.")
            service_getter.assert_not_called()

    def test_heart_authentication_and_ownership_precede_service_access(self):
        with patch.object(
            predictions,
            "get_ml_model_service",
            return_value=self.service,
        ) as service_getter:
            status, body = self.client.request(
                "POST",
                "/predictions/heart",
                self._heart_payload(),
            )
            self.assertEqual(status, 401)
            self.assertEqual(body["detail"], "Authentication required.")
            service_getter.assert_not_called()

            status, body = self.client.request(
                "POST",
                "/predictions/heart",
                self._heart_payload(self.foreign_patient_id),
                token=self.token,
            )
            self.assertEqual(status, 404)
            self.assertEqual(body["detail"], "Resource not found.")
            service_getter.assert_not_called()

    def test_diabetes_prediction_uses_explicit_semantic_contract(self):
        with patch.object(
            predictions,
            "get_ml_model_service",
            return_value=self.service,
        ):
            status, body = self.client.request(
                "POST",
                "/predictions/diabetes",
                self._diabetes_payload(),
                token=self.token,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["patient_id"], self.owned_patient_id)
        self.assertEqual(body["disease"], "diabetes")
        self.assertEqual(body["prediction_source"], "task13b_diabd_v3_model")
        self.assertEqual(body["classification"], "at_or_above_model_threshold")
        self.assertEqual(body["features_used"]["glucose"], 7.2)
        self.assertEqual(
            self.service.diabetes_calls,
            [
                {
                    "age": 65,
                    "gender": "Female",
                    "systolic_bp": 130,
                    "diastolic_bp": 80,
                    "random_glucose_mmol_l": 7.2,
                    "bmi": 25.0,
                }
            ],
        )

    def test_heart_prediction_preserves_four_level_chest_pain_contract(self):
        with patch.object(
            predictions,
            "get_ml_model_service",
            return_value=self.service,
        ):
            status, body = self.client.request(
                "POST",
                "/predictions/heart",
                self._heart_payload(),
                token=self.token,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["disease"], "heart")
        self.assertEqual(body["classification"], "below_model_threshold")
        self.assertEqual(
            self.service.heart_calls[0]["chest_pain_type"],
            "asymptomatic",
        )

    def test_generic_or_fabricated_inputs_are_rejected_with_422(self):
        invalid_diabetes = self._diabetes_payload()
        invalid_diabetes.pop("random_glucose_mmol_l")
        invalid_diabetes["two_hour_ogtt_glucose_mg_dl"] = 140.0
        invalid_heart = self._heart_payload()
        invalid_heart["clinical_sex"] = "Other"
        invalid_heart["chest_pain"] = True

        with patch.object(
            predictions,
            "get_ml_model_service",
            return_value=self.service,
        ) as service_getter:
            status, body = self.client.request(
                "POST",
                "/predictions/diabetes",
                invalid_diabetes,
                token=self.token,
            )
            self.assertEqual(status, 422)
            self.assertIsInstance(body["detail"], list)

            status, body = self.client.request(
                "POST",
                "/predictions/heart",
                invalid_heart,
                token=self.token,
            )
            self.assertEqual(status, 422)
            self.assertIsInstance(body["detail"], list)
            service_getter.assert_not_called()

    def test_contract_model_and_inference_failures_are_sanitized(self):
        cases = (
            (ModelContractError("private contract detail"), 422),
            (ModelUnavailableError("C:\\private\\model.pkl"), 503),
            (ModelInferenceError("private sklearn detail"), 503),
        )
        for error, expected_status in cases:
            with self.subTest(error=type(error).__name__):
                self.service.diabetes_error = error
                with patch.object(
                    predictions,
                    "get_ml_model_service",
                    return_value=self.service,
                ):
                    status, body = self.client.request(
                        "POST",
                        "/predictions/diabetes",
                        self._diabetes_payload(),
                        token=self.token,
                    )
                self.assertEqual(status, expected_status)
                self.assertNotIn("private", str(body).lower())
                self.assertNotIn("model.pkl", str(body).lower())

    def test_authenticated_contract_endpoint_reports_both_models(self):
        with patch.object(
            predictions,
            "get_ml_model_service",
            return_value=self.service,
        ):
            status, body = self.client.request(
                "GET",
                "/predictions/contracts",
                token=self.token,
            )
        self.assertEqual(status, 200)
        self.assertEqual(set(body["models"]), {"diabetes", "heart"})
        self.assertEqual(body["models"]["diabetes"]["threshold"], 0.06)
        self.assertEqual(body["models"]["diabetes"]["model_version"], "3.0.0")

    def test_diabetes_contract_rejects_unsupported_values_before_inference(self):
        cases = []
        for field, value in (
            ("age", 20),
            ("gender", "Other"),
            ("random_glucose_mmol_l", 33.47),
            ("random_glucose_mmol_l", 130.0),
            ("diastolic_bp", 130),
        ):
            payload = self._diabetes_payload()
            payload[field] = value
            cases.append(payload)
        missing = self._diabetes_payload()
        missing.pop("gender")
        cases.append(missing)

        with patch.object(
            predictions,
            "get_ml_model_service",
            return_value=self.service,
        ) as service_getter:
            for payload in cases:
                with self.subTest(payload=payload):
                    status, _ = self.client.request(
                        "POST",
                        "/predictions/diabetes",
                        payload,
                        token=self.token,
                    )
                    self.assertEqual(status, 422)
            service_getter.assert_not_called()
        self.assertEqual(self.service.diabetes_calls, [])

    def test_known_diabetes_and_incompatible_profile_bypass_screening(self):
        patient = self.session.get(models.Patient, self.owned_patient_id)
        patient.has_diabetes = True
        self.session.commit()
        with patch.object(
            predictions,
            "get_ml_model_service",
            return_value=self.service,
        ) as service_getter:
            status, body = self.client.request(
                "POST",
                "/predictions/diabetes",
                self._diabetes_payload(),
                token=self.token,
            )
        self.assertEqual(status, 409)
        self.assertIn("already recorded", body["detail"])
        service_getter.assert_not_called()

        patient.has_diabetes = False
        patient.gender = "Other"
        self.session.commit()
        status, body = self.client.request(
            "POST",
            "/predictions/diabetes",
            self._diabetes_payload(),
            token=self.token,
        )
        self.assertEqual(status, 422)
        self.assertIn("exactly Female or Male", body["detail"])

    def test_kidney_prediction_route_is_not_deployed(self):
        status, _ = self.client.request(
            "POST",
            "/predictions/kidney",
            {"patient_id": self.owned_patient_id},
            token=self.token,
        )
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
