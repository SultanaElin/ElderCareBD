import unittest

from pydantic import ValidationError

from prediction_schemas import PredictionResponse


def _response_payload(*, disease: str, prediction_source: str):
    return {
        "patient_id": 73,
        "disease": disease,
        "prediction_source": prediction_source,
        "model_version": "3.0.0" if disease == "diabetes" else "2.0.0",
        "risk_score": 0.64,
        "classification": "at_or_above_model_threshold",
        "threshold": 0.06 if disease == "diabetes" else 0.53,
        "features_used": {"age": 72},
        "disclaimer": "Non-diagnostic research screening only.",
    }


class PredictionResponseSchemaTest(unittest.TestCase):
    def test_final_model_source_must_match_disease(self):
        valid_pairs = (
            ("diabetes", "task13b_diabd_v3_model"),
            ("heart", "task13_heart_v2_model"),
        )
        for disease, source in valid_pairs:
            with self.subTest(disease=disease):
                parsed = PredictionResponse.model_validate(
                    _response_payload(disease=disease, prediction_source=source)
                )
                self.assertEqual(parsed.prediction_source, source)

        with self.assertRaises(ValidationError):
            PredictionResponse.model_validate(
                _response_payload(
                    disease="diabetes",
                    prediction_source="task13_heart_v2_model",
                )
            )


if __name__ == "__main__":
    unittest.main()
