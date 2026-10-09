import unittest
from dataclasses import dataclass
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth_test_support import create_verified_caregiver_session
from database import Base, get_db
from ml_model_service import ModelUnavailableError
from routers import assessments, auth, patients
from test_core_workflow import FastApiRequestHarness, _database_signatures


@dataclass(frozen=True)
class _FakePrediction:
    disease: str
    score: float
    threshold: float

    def to_dict(self):
        is_diabetes = self.disease == "diabetes"
        return {
            "disease": self.disease,
            "prediction_source": (
                "task13b_diabd_v3_model"
                if is_diabetes
                else "task13_heart_v2_model"
            ),
            "model_version": "3.0.0" if is_diabetes else "2.0.0",
            "risk_score": self.score,
            "classification": (
                "at_or_above_model_threshold"
                if self.score >= self.threshold
                else "below_model_threshold"
            ),
            "threshold": self.threshold,
            "features_used": {},
            "disclaimer": "Research screening model output; not a diagnosis.",
        }


class _FakeModelService:
    def __init__(self, *, unavailable=False, malformed=False):
        self.unavailable = unavailable
        self.malformed = malformed
        self.diabetes_calls = []
        self.heart_calls = []

    def contracts(self):
        return {
            "models": {
                disease: {"available": not self.unavailable}
                for disease in ("diabetes", "heart")
            }
        }

    def predict_diabetes(self, **values):
        self.diabetes_calls.append(values)
        if self.unavailable:
            raise ModelUnavailableError("internal test detail")
        if self.malformed:
            return _FakePrediction("heart", 5.0, 0.31)
        return _FakePrediction("diabetes", 0.64, 0.06)

    def predict_heart(self, **values):
        self.heart_calls.append(values)
        if self.unavailable:
            raise ModelUnavailableError("internal test detail")
        return _FakePrediction("heart", 0.41, 0.53)


class AssessmentPredictionPersistenceTest(unittest.TestCase):
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

        caregiver_id, self.token = create_verified_caregiver_session(
            self.session,
            name="Task14 Test Caregiver",
            identity="task14-persistence@example.invalid",
            password="task14-test-password",
        )
        status, patient = self.client.request(
            "POST",
            "/patients/",
            {
                "caregiver_id": caregiver_id,
                "name": "TASK14_SYNTHETIC_PATIENT",
                "age": 55,
                "gender": "Female",
            },
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.patient_id = patient["patient_id"]

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.assertEqual(self.database_signatures, _database_signatures())

    def _payload(self):
        return {
            "patient_id": self.patient_id,
            "age": 55,
            "glucose": 118,
            "systolic_bp": 130,
            "diastolic_bp": 80,
            "bmi": 31.5,
            "height_cm": 160.0,
            "weight_kg": 80.64,
            "note": "TASK14_SYNTHETIC_ASSESSMENT",
            "chest_pain": False,
            "dizziness": False,
            "shortness_of_breath": False,
            "excessive_thirst": False,
            "fatigue": False,
            "blurred_vision": False,
            "diabetes_risk": "Medium",
            "heart_risk": "Low",
            "overall_risk": "Medium",
            "recommendation": "Demo heuristic recommendation.",
        }

    def test_backend_recomputes_and_history_returns_model_provenance(self):
        payload = self._payload()
        payload["diabetes_model_input"] = {
            "age": 55,
            "gender": "Female",
            "systolic_bp": 130,
            "diastolic_bp": 80,
            "random_glucose_mmol_l": 7.2,
            "bmi": 31.5,
        }
        payload["heart_model_input"] = {
            "age": 55,
            "clinical_sex": "male",
            "chest_pain_type": "non-anginal pain",
            "blood_pressure_context": "resting_systolic",
            "resting_systolic_bp_mm_hg": 130,
        }
        service = _FakeModelService()

        with patch(
            "routers.assessments.get_ml_model_service",
            return_value=service,
        ):
            status, body = self.client.request(
                "POST",
                "/assessments/",
                payload,
                token=self.token,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["predictions"]["diabetes"]["risk_score"], 0.64)
        self.assertEqual(
            body["predictions"]["heart"]["classification"],
            "below_model_threshold",
        )
        self.assertEqual(len(service.diabetes_calls), 1)
        self.assertEqual(len(service.heart_calls), 1)

        assessment = self.session.get(models.Assessment, body["assessment_id"])
        self.assertEqual(
            assessment.diabetes_prediction_source,
            "task13b_diabd_v3_model",
        )
        self.assertEqual(assessment.diabetes_prediction_status, "predicted")
        self.assertEqual(assessment.diabetes_model_version, "3.0.0")
        self.assertEqual(assessment.diabetes_model_score, 0.64)
        self.assertEqual(assessment.diabetes_model_threshold, 0.06)
        self.assertEqual(assessment.diabetes_gender, "Female")
        self.assertEqual(assessment.diabetes_random_glucose_mmol_l, 7.2)
        self.assertIsNone(assessment.diabetes_ogtt_glucose)
        self.assertEqual(assessment.heart_clinical_sex, "male")
        self.assertEqual(
            assessment.heart_chest_pain_type,
            "non-anginal pain",
        )
        self.assertEqual(assessment.heart_resting_systolic_bp, 130)

        status, history = self.client.request(
            "GET",
            f"/assessments/patient/{self.patient_id}",
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(history[0]["diabetes_model_score"], 0.64)
        self.assertEqual(
            history[0]["heart_model_classification"],
            "below_model_threshold",
        )

    def test_missing_model_inputs_save_explicit_heuristic_fallback(self):
        with patch(
            "routers.assessments.get_ml_model_service",
            return_value=_FakeModelService(),
        ) as getter:
            status, body = self.client.request(
                "POST",
                "/assessments/",
                self._payload(),
                token=self.token,
            )

        self.assertEqual(status, 200)
        getter.assert_called_once_with()
        self.assertEqual(
            body["predictions"]["diabetes"]["prediction_status"],
            "skipped_missing_model_input",
        )
        row = self.session.get(models.Assessment, body["assessment_id"])
        self.assertEqual(row.diabetes_prediction_source, "heuristic_demo_v1")
        self.assertIsNone(row.diabetes_model_score)
        self.assertEqual(row.heart_prediction_source, "heuristic_demo_v1")

    def test_model_unavailable_does_not_prevent_assessment_save(self):
        payload = self._payload()
        payload["diabetes_model_input"] = {
            "age": 55,
            "gender": "Female",
            "systolic_bp": 130,
            "diastolic_bp": 80,
            "random_glucose_mmol_l": 7.2,
            "bmi": 31.5,
        }
        with patch(
            "routers.assessments.get_ml_model_service",
            return_value=_FakeModelService(unavailable=True),
        ):
            status, body = self.client.request(
                "POST",
                "/assessments/",
                payload,
                token=self.token,
            )

        self.assertEqual(status, 200)
        self.assertEqual(
            body["predictions"]["diabetes"]["prediction_status"],
            "model_unavailable",
        )
        self.assertNotIn("internal test detail", str(body))
        row = self.session.get(models.Assessment, body["assessment_id"])
        self.assertEqual(row.diabetes_prediction_source, "heuristic_demo_v1")
        self.assertIsNone(row.diabetes_model_score)

    def test_malformed_model_result_does_not_prevent_assessment_save(self):
        payload = self._payload()
        payload["diabetes_model_input"] = {
            "age": 55,
            "gender": "Female",
            "systolic_bp": 130,
            "diastolic_bp": 80,
            "random_glucose_mmol_l": 7.2,
            "bmi": 31.5,
        }
        with patch(
            "routers.assessments.get_ml_model_service",
            return_value=_FakeModelService(malformed=True),
        ):
            status, body = self.client.request(
                "POST",
                "/assessments/",
                payload,
                token=self.token,
            )

        self.assertEqual(status, 200)
        self.assertEqual(
            body["predictions"]["diabetes"]["prediction_status"],
            "inference_failed",
        )
        self.assertIsNone(
            self.session.get(
                models.Assessment,
                body["assessment_id"],
            ).diabetes_model_score
        )

    def test_known_diabetes_bypasses_model_without_fabricating_result(self):
        patient = self.session.get(models.Patient, self.patient_id)
        patient.has_diabetes = True
        self.session.commit()
        payload = self._payload()
        payload["diabetes_model_input"] = {
            "age": 55,
            "gender": "Female",
            "systolic_bp": 130,
            "diastolic_bp": 80,
            "random_glucose_mmol_l": 7.2,
            "bmi": 31.5,
        }
        service = _FakeModelService()
        with patch(
            "routers.assessments.get_ml_model_service",
            return_value=service,
        ):
            status, body = self.client.request(
                "POST",
                "/assessments/",
                payload,
                token=self.token,
            )

        self.assertEqual(status, 200)
        prediction = body["predictions"]["diabetes"]
        self.assertEqual(prediction["prediction_source"], "known_condition")
        self.assertEqual(
            prediction["prediction_status"],
            "not_applicable_known_diabetes",
        )
        self.assertIsNone(prediction["risk_score"])
        self.assertEqual(service.diabetes_calls, [])
        row = self.session.get(models.Assessment, body["assessment_id"])
        self.assertIsNone(row.diabetes_gender)
        self.assertIsNone(row.diabetes_random_glucose_mmol_l)
        self.assertIsNone(row.diabetes_model_score)

    def test_client_cannot_forge_model_provenance(self):
        payload = self._payload()
        payload["diabetes_model_score"] = 0.99
        payload["diabetes_prediction_source"] = "forged"

        status, body = self.client.request(
            "POST",
            "/assessments/",
            payload,
            token=self.token,
        )

        self.assertEqual(status, 422)
        self.assertIsInstance(body["detail"], list)
        self.assertEqual(self.session.query(models.Assessment).count(), 0)


if __name__ == "__main__":
    unittest.main()
