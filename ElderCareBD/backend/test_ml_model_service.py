import hashlib
import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ml_model_service import (
    ModelContractError,
    ModelInferenceError,
    MlModelService,
    _TRUSTED_MODELS,
    _verify_repository_files,
    get_ml_model_service,
)


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


def _metadata(disease, *, sex_labels=None, chest_pain_labels=None):
    if disease == "diabetes":
        feature_order = [
            "age",
            "gender",
            "systolic_bp",
            "diastolic_bp",
            "glucose",
            "bmi",
        ]
        features = [
            {"name": "age", "value_labels": None, "allowed_values": None},
            {
                "name": "gender",
                "value_labels": {"0": "Female", "1": "Male"},
                "allowed_values": [0, 1],
            },
            {"name": "systolic_bp", "value_labels": None, "allowed_values": None},
            {"name": "diastolic_bp", "value_labels": None, "allowed_values": None},
            {"name": "glucose", "value_labels": None, "allowed_values": None},
            {"name": "bmi", "value_labels": None, "allowed_values": None},
        ]
        threshold = 0.06
        model_version = "3.0.0"
    else:
        feature_order = ["age", "sex", "cp", "trestbps"]
        sex_labels = sex_labels or {"0": "female", "1": "male"}
        chest_pain_labels = chest_pain_labels or {
            "0": "typical angina",
            "1": "atypical angina",
            "2": "non-anginal pain",
            "3": "asymptomatic",
        }
        features = [
            {"name": "age", "value_labels": None, "allowed_values": None},
            {
                "name": "sex",
                "value_labels": sex_labels,
                "allowed_values": [int(value) for value in sex_labels],
            },
            {
                "name": "cp",
                "value_labels": chest_pain_labels,
                "allowed_values": [int(value) for value in chest_pain_labels],
            },
            {"name": "trestbps", "value_labels": None, "allowed_values": None},
        ]
        threshold = 0.53
        model_version = "2.0.0"
    metadata = {
        "disease": disease,
        "model_version": model_version,
        "evaluation": {"classification_threshold": threshold},
        "feature_contract": {
            "feature_order": feature_order,
            "features": features,
        },
    }
    if disease == "diabetes":
        metadata["target"] = {"positive_class": 1}
    else:
        metadata["positive_class"] = 1
    return metadata


class _FakeArtifact:
    def __init__(self, disease, score=0.6, *, raises=None):
        self.disease = disease
        self.model_version = "3.0.0" if disease == "diabetes" else "2.0.0"
        self.feature_names = (
            (
                "age",
                "gender",
                "systolic_bp",
                "diastolic_bp",
                "glucose",
                "bmi",
            )
            if disease == "diabetes"
            else ("age", "sex", "cp", "trestbps")
        )
        self.classification_threshold = 0.06 if disease == "diabetes" else 0.53
        self.pipeline = SimpleNamespace(classes_=[0, 1])
        self.score = score
        self.raises = raises
        self.last_features = None

    def predict_risk_score(self, features):
        self.last_features = dict(features)
        if self.raises is not None:
            raise self.raises
        return [self.score]


class MlModelServiceTest(unittest.TestCase):
    def setUp(self):
        self.database_signatures = _database_signatures()
        get_ml_model_service.cache_clear()

    def tearDown(self):
        get_ml_model_service.cache_clear()
        self.assertEqual(self.database_signatures, _database_signatures())

    def test_repository_metadata_and_artifact_trust_pins_match(self):
        for disease, trusted in _TRUSTED_MODELS.items():
            metadata = _verify_repository_files(disease)
            self.assertEqual(metadata["disease"], disease)
            self.assertEqual(
                metadata["artifact"]["sha256"],
                trusted["artifact_sha256"],
            )
            self.assertEqual(
                tuple(metadata["feature_contract"]["feature_order"]),
                trusted["feature_order"],
            )

    def test_models_load_once_for_a_cached_process_service(self):
        artifacts = {
            disease: _FakeArtifact(disease) for disease in ("diabetes", "heart")
        }
        calls = []

        def loader(disease):
            calls.append(disease)
            return artifacts[disease], _metadata(disease)

        with patch("ml_model_service._load_trusted_model", side_effect=loader):
            first = get_ml_model_service()
            second = get_ml_model_service()

        self.assertIs(first, second)
        self.assertEqual(calls, ["diabetes", "heart"])

    def test_heart_human_labels_are_mapped_only_from_verified_metadata(self):
        heart = _FakeArtifact("heart", score=0.53)
        custom_metadata = _metadata(
            "heart",
            sex_labels={"9": "female", "7": "male"},
            chest_pain_labels={
                "10": "typical angina",
                "11": "atypical angina",
                "12": "non-anginal pain",
                "13": "asymptomatic",
            },
        )

        def loader(disease):
            if disease == "heart":
                return heart, custom_metadata
            return _FakeArtifact("diabetes"), _metadata("diabetes")

        service = MlModelService(loader=loader)
        result = service.predict_heart(
            age=65,
            clinical_sex="male",
            chest_pain_type="non-anginal pain",
            resting_systolic_bp_mm_hg=130,
        )

        self.assertEqual(
            heart.last_features,
            {"age": 65, "sex": 7, "cp": 12, "trestbps": 130},
        )
        self.assertEqual(result.classification, "at_or_above_model_threshold")
        self.assertEqual(result.prediction_source, "task13_heart_v2_model")
        self.assertEqual(result.to_dict()["features_used"], heart.last_features)

    def test_unknown_heart_label_is_a_contract_error(self):
        def loader(disease):
            return _FakeArtifact(disease), _metadata(disease)

        service = MlModelService(loader=loader)
        with self.assertRaises(ModelContractError):
            service.predict_heart(
                age=65,
                clinical_sex="unknown",
                chest_pain_type="asymptomatic",
                resting_systolic_bp_mm_hg=130,
            )

    def test_models_degrade_independently(self):
        heart = _FakeArtifact("heart", score=0.2)

        def loader(disease):
            if disease == "diabetes":
                raise RuntimeError("private installation detail")
            return heart, _metadata("heart")

        service = MlModelService(loader=loader)
        contracts = service.contracts()["models"]
        self.assertFalse(contracts["diabetes"]["available"])
        self.assertTrue(contracts["heart"]["available"])
        self.assertNotIn("private installation detail", str(contracts))
        self.assertEqual(
            service.predict_heart(
                age=65,
                clinical_sex="female",
                chest_pain_type="asymptomatic",
                resting_systolic_bp_mm_hg=130,
            ).classification,
            "below_model_threshold",
        )

    def test_invalid_score_is_an_inference_error(self):
        def loader(disease):
            score = math.nan if disease == "diabetes" else 0.5
            return _FakeArtifact(disease, score=score), _metadata(disease)

        service = MlModelService(loader=loader)
        with self.assertRaises(ModelInferenceError):
            service.predict_diabetes(
                age=65,
                gender="Female",
                systolic_bp=130,
                diastolic_bp=80,
                random_glucose_mmol_l=7.2,
                bmi=25.0,
            )

    def test_real_models_match_direct_verified_artifact_scores_when_available(self):
        service = MlModelService()
        contracts = service.contracts()["models"]
        if not all(contract["available"] for contract in contracts.values()):
            self.skipTest("Exact Task 13 inference runtime is not installed.")

        repository_root = Path(__file__).resolve().parent.parent
        if str(repository_root) not in __import__("sys").path:
            __import__("sys").path.insert(0, str(repository_root))
        from ml_training.eldercare_ml.loading import load_verified_runtime_artifact

        diabetes_features = {
            "age": 65,
            "gender": 0,
            "systolic_bp": 130,
            "diastolic_bp": 80,
            "glucose": 7.2,
            "bmi": 25.0,
        }
        diabetes_artifact, _ = load_verified_runtime_artifact("diabetes")
        diabetes_expected = float(
            diabetes_artifact.predict_risk_score(diabetes_features)[0]
        )
        diabetes_actual = service.predict_diabetes(
            age=65,
            gender="Female",
            systolic_bp=130,
            diastolic_bp=80,
            random_glucose_mmol_l=7.2,
            bmi=25.0,
        )
        self.assertAlmostEqual(diabetes_actual.risk_score, diabetes_expected, places=14)

        heart_features = {"age": 65, "sex": 0, "cp": 3, "trestbps": 130}
        heart_artifact, _ = load_verified_runtime_artifact("heart")
        heart_expected = float(heart_artifact.predict_risk_score(heart_features)[0])
        heart_actual = service.predict_heart(
            age=65,
            clinical_sex="female",
            chest_pain_type="asymptomatic",
            resting_systolic_bp_mm_hg=130,
        )
        self.assertAlmostEqual(heart_actual.risk_score, heart_expected, places=14)


if __name__ == "__main__":
    unittest.main()
