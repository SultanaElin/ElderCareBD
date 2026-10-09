import unittest

from models import Assessment
from schemas import AssessmentCreate


class AssessmentContractTest(unittest.TestCase):
    def _base_payload(self):
        return {
            "patient_id": 1,
            "age": 72,
            "glucose": 165,
            "systolic_bp": 145,
            "diastolic_bp": 90,
            "bmi": 25.0,
            "diabetes_risk": "High",
            "heart_risk": "High",
            "overall_risk": "High",
            "recommendation": "Test recommendation",
        }

    def test_new_fields_are_optional_for_historical_payloads(self):
        assessment = AssessmentCreate(**self._base_payload())

        self.assertIsNone(assessment.height_cm)
        self.assertIsNone(assessment.weight_kg)
        self.assertIsNone(assessment.note)
        self.assertIsNone(assessment.diabetes_model_input)
        self.assertIsNone(assessment.heart_model_input)

    def test_new_fields_preserve_supplied_values(self):
        payload = self._base_payload()
        payload.update(
            {
                "height_cm": 163.5,
                "weight_kg": 67.25,
                "note": "TASK4_PERSISTENCE_TEST",
            }
        )

        assessment = AssessmentCreate(**payload)

        self.assertEqual(assessment.height_cm, 163.5)
        self.assertEqual(assessment.weight_kg, 67.25)
        self.assertEqual(assessment.note, "TASK4_PERSISTENCE_TEST")

    def test_database_columns_are_nullable(self):
        nullable_columns = {
            "height_cm",
            "weight_kg",
            "note",
            "diabetes_prediction_source",
            "diabetes_prediction_status",
            "diabetes_model_version",
            "diabetes_model_score",
            "diabetes_model_threshold",
            "diabetes_model_classification",
            "diabetes_gender",
            "diabetes_random_glucose_mmol_l",
            "diabetes_ogtt_glucose",
            "heart_prediction_source",
            "heart_prediction_status",
            "heart_model_version",
            "heart_model_score",
            "heart_model_threshold",
            "heart_model_classification",
            "heart_clinical_sex",
            "heart_chest_pain_type",
            "heart_resting_systolic_bp",
        }
        for column_name in nullable_columns:
            with self.subTest(column=column_name):
                self.assertTrue(Assessment.__table__.c[column_name].nullable)

    def test_model_input_must_match_the_persisted_assessment_values(self):
        payload = self._base_payload()
        payload["diabetes_model_input"] = {
            "age": 71,
            "gender": "Female",
            "systolic_bp": 145,
            "diastolic_bp": 90,
            "random_glucose_mmol_l": 7.2,
            "bmi": 25.0,
        }

        with self.assertRaises(ValueError):
            AssessmentCreate(**payload)


if __name__ == "__main__":
    unittest.main()
