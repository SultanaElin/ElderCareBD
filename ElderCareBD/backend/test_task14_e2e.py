import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from auth_test_support import create_verified_caregiver_session

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ml_training.eldercare_ml.loading import load_verified_runtime_artifact
from routers import assessments, auth, patients, predictions
from test_core_workflow import FastApiRequestHarness, _database_signatures


class Task14EndToEndTest(unittest.TestCase):
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
        app.include_router(predictions.router)
        app.include_router(assessments.router)

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = FastApiRequestHarness(app)
        self.caregiver_id, self.token = create_verified_caregiver_session(
            self.session,
            name="TASK14_SYNTHETIC_E2E_CAREGIVER",
            identity="task14-e2e@example.invalid",
            password="task14-e2e-password",
        )

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.assertEqual(self.database_signatures, _database_signatures())

    def _create_patient(self, name, age, *, gender="Female", has_diabetes=False):
        status, body = self.client.request(
            "POST",
            "/patients/",
            {
                "caregiver_id": self.caregiver_id,
                "name": name,
                "age": age,
                "gender": gender,
                "has_diabetes": has_diabetes,
            },
            token=self.token,
        )
        self.assertEqual(status, 200)
        return body["patient_id"]

    @staticmethod
    def _base_assessment(patient_id, age, bmi, systolic_bp):
        return {
            "patient_id": patient_id,
            "age": age,
            "glucose": 118,
            "systolic_bp": systolic_bp,
            "diastolic_bp": 80,
            "bmi": bmi,
            "height_cm": 160.0,
            "weight_kg": round(bmi * 2.56, 2),
            "note": "TASK14_SYNTHETIC_E2E_ONLY",
            "chest_pain": False,
            "dizziness": False,
            "shortness_of_breath": False,
            "excessive_thirst": False,
            "fatigue": False,
            "blurred_vision": False,
            "diabetes_risk": "Low",
            "heart_risk": "Low",
            "overall_risk": "Low",
            "recommendation": "Synthetic heuristic fallback text.",
        }

    def test_diabetes_and_heart_api_save_history_match_direct_artifacts(self):
        diabetes_patient = self._create_patient(
            "TASK14_SYNTHETIC_DIABETES_PATIENT",
            55,
        )
        diabetes_request = {
            "patient_id": diabetes_patient,
            "age": 55,
            "gender": "Female",
            "systolic_bp": 130,
            "diastolic_bp": 80,
            "random_glucose_mmol_l": 7.2,
            "bmi": 31.5,
        }
        status, diabetes_api = self.client.request(
            "POST",
            "/predictions/diabetes",
            diabetes_request,
            token=self.token,
        )
        self.assertEqual(status, 200)
        diabetes_artifact, _ = load_verified_runtime_artifact("diabetes")
        direct_diabetes = float(
            diabetes_artifact.predict_risk_score(
                {
                    "age": 55,
                    "gender": 0,
                    "systolic_bp": 130,
                    "diastolic_bp": 80,
                    "glucose": 7.2,
                    "bmi": 31.5,
                }
            )[0]
        )
        self.assertAlmostEqual(
            diabetes_api["risk_score"],
            direct_diabetes,
            places=15,
        )
        self.assertEqual(
            diabetes_api["classification"],
            (
                "at_or_above_model_threshold"
                if direct_diabetes >= 0.06
                else "below_model_threshold"
            ),
        )

        diabetes_assessment = self._base_assessment(
            diabetes_patient,
            55,
            31.5,
            130,
        )
        diabetes_assessment["diabetes_model_input"] = {
            key: value
            for key, value in diabetes_request.items()
            if key != "patient_id"
        }
        status, saved_diabetes = self.client.request(
            "POST",
            "/assessments/",
            diabetes_assessment,
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.assertAlmostEqual(
            saved_diabetes["predictions"]["diabetes"]["risk_score"],
            direct_diabetes,
            places=15,
        )
        status, diabetes_history = self.client.request(
            "GET",
            f"/assessments/patient/{diabetes_patient}",
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(diabetes_history), 1)
        self.assertAlmostEqual(
            diabetes_history[0]["diabetes_model_score"],
            direct_diabetes,
            places=15,
        )
        self.assertEqual(
            diabetes_history[0]["diabetes_prediction_source"],
            "task13b_diabd_v3_model",
        )
        self.assertEqual(diabetes_history[0]["diabetes_gender"], "Female")
        self.assertEqual(
            diabetes_history[0]["diabetes_random_glucose_mmol_l"],
            7.2,
        )
        self.assertIsNone(diabetes_history[0]["diabetes_ogtt_glucose"])

        heart_patient = self._create_patient(
            "TASK14_SYNTHETIC_HEART_PATIENT",
            60,
        )
        heart_request = {
            "patient_id": heart_patient,
            "age": 60,
            "clinical_sex": "male",
            "chest_pain_type": "non-anginal pain",
            "blood_pressure_context": "resting_systolic",
            "resting_systolic_bp_mm_hg": 130,
        }
        status, heart_api = self.client.request(
            "POST",
            "/predictions/heart",
            heart_request,
            token=self.token,
        )
        self.assertEqual(status, 200)
        heart_artifact, _ = load_verified_runtime_artifact("heart")
        direct_heart = float(
            heart_artifact.predict_risk_score(
                {"age": 60, "sex": 1, "cp": 2, "trestbps": 130}
            )[0]
        )
        self.assertAlmostEqual(heart_api["risk_score"], direct_heart, places=15)
        self.assertEqual(
            heart_api["classification"],
            "below_model_threshold",
        )

        heart_assessment = self._base_assessment(
            heart_patient,
            60,
            25.0,
            130,
        )
        heart_assessment["heart_model_input"] = {
            key: value for key, value in heart_request.items() if key != "patient_id"
        }
        status, saved_heart = self.client.request(
            "POST",
            "/assessments/",
            heart_assessment,
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.assertAlmostEqual(
            saved_heart["predictions"]["heart"]["risk_score"],
            direct_heart,
            places=15,
        )
        status, heart_history = self.client.request(
            "GET",
            f"/assessments/patient/{heart_patient}",
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(heart_history), 1)
        self.assertAlmostEqual(
            heart_history[0]["heart_model_score"],
            direct_heart,
            places=15,
        )
        self.assertEqual(
            heart_history[0]["heart_prediction_source"],
            "task13_heart_v2_model",
        )

    def test_invalid_semantics_never_reach_a_model(self):
        patient_id = self._create_patient("TASK14_SYNTHETIC_INVALID", 60)
        invalid_requests = [
            (
                "/predictions/diabetes",
                {
                    "patient_id": patient_id,
                    "age": 60,
                    "gender": "Female",
                    "systolic_bp": 130,
                    "diastolic_bp": 80,
                    "glucose": 7.2,
                    "bmi": 25.0,
                },
            ),
            (
                "/predictions/diabetes",
                {
                    "patient_id": patient_id,
                    "age": 60,
                    "gender": "Other",
                    "systolic_bp": 130,
                    "diastolic_bp": 80,
                    "random_glucose_mmol_l": 7.2,
                    "bmi": 25.0,
                },
            ),
            (
                "/predictions/diabetes",
                {
                    "patient_id": patient_id,
                    "age": 60,
                    "gender": "Female",
                    "systolic_bp": 100,
                    "diastolic_bp": 100,
                    "random_glucose_mmol_l": 7.2,
                    "bmi": 25.0,
                },
            ),
            (
                "/predictions/heart",
                {
                    "patient_id": patient_id,
                    "age": 60,
                    "clinical_sex": "Other",
                    "chest_pain_type": "non-anginal pain",
                    "blood_pressure_context": "resting_systolic",
                    "resting_systolic_bp_mm_hg": 130,
                },
            ),
            (
                "/predictions/heart",
                {
                    "patient_id": patient_id,
                    "age": 60,
                    "clinical_sex": "male",
                    "blood_pressure_context": "resting_systolic",
                    "resting_systolic_bp_mm_hg": 130,
                },
            ),
            (
                "/predictions/heart",
                {
                    "patient_id": patient_id,
                    "age": 60,
                    "clinical_sex": "male",
                    "chest_pain_type": "yes",
                    "blood_pressure_context": "resting_systolic",
                    "resting_systolic_bp_mm_hg": 130,
                    "chest_pain": True,
                },
            ),
        ]
        for path, payload in invalid_requests:
            with self.subTest(path=path, payload=payload):
                status, body = self.client.request(
                    "POST",
                    path,
                    payload,
                    token=self.token,
                )
                self.assertEqual(status, 422)
                self.assertTrue(
                    isinstance(body["detail"], list)
                    or body["detail"]
                    == "Prediction input does not match the supported model contract."
                )

    def test_known_diabetes_incompatible_gender_and_cross_owner_are_safe(self):
        known_patient = self._create_patient(
            "TASK14_SYNTHETIC_KNOWN_DIABETES",
            55,
            has_diabetes=True,
        )
        request = {
            "patient_id": known_patient,
            "age": 55,
            "gender": "Female",
            "systolic_bp": 130,
            "diastolic_bp": 80,
            "random_glucose_mmol_l": 7.2,
            "bmi": 25.0,
        }
        status, body = self.client.request(
            "POST",
            "/predictions/diabetes",
            request,
            token=self.token,
        )
        self.assertEqual(status, 409)
        self.assertIn("already recorded", body["detail"])

        assessment = self._base_assessment(known_patient, 55, 25.0, 130)
        assessment["diabetes_model_input"] = {
            key: value for key, value in request.items() if key != "patient_id"
        }
        status, body = self.client.request(
            "POST",
            "/assessments/",
            assessment,
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            body["predictions"]["diabetes"]["prediction_status"],
            "not_applicable_known_diabetes",
        )
        self.assertIsNone(body["predictions"]["diabetes"]["risk_score"])

        other_gender_patient = self._create_patient(
            "TASK14_SYNTHETIC_OTHER_GENDER",
            55,
            gender="Other",
        )
        request["patient_id"] = other_gender_patient
        status, _ = self.client.request(
            "POST",
            "/predictions/diabetes",
            request,
            token=self.token,
        )
        self.assertEqual(status, 422)

        second_caregiver_id, second_token = create_verified_caregiver_session(
            self.session,
            name="TASK14_SYNTHETIC_SECOND_CAREGIVER",
            identity="task14-e2e-second@example.invalid",
            password="task14-e2e-password",
        )
        status, foreign_patient = self.client.request(
            "POST",
            "/patients/",
            {
                "caregiver_id": second_caregiver_id,
                "name": "TASK14_SYNTHETIC_FOREIGN_PATIENT",
                "age": 55,
                "gender": "Female",
            },
            token=second_token,
        )
        self.assertEqual(status, 200)
        request["patient_id"] = foreign_patient["patient_id"]
        status, _ = self.client.request(
            "POST",
            "/predictions/diabetes",
            request,
            token=self.token,
        )
        self.assertEqual(status, 404)

        status, _ = self.client.request(
            "POST",
            "/predictions/kidney",
            {"patient_id": known_patient},
            token=self.token,
        )
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
