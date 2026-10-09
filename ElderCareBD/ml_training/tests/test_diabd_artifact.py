from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


ML_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ML_ROOT.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ml_training.eldercare_ml import diabd_loading  # noqa: E402


EXPECTED_ARTIFACT_FILENAME = "diabetes_model_v3_diabd.pkl"
EXPECTED_METADATA_FILENAME = "diabetes_model_v3_diabd.metadata.json"
EXPECTED_MODEL_VERSION = "3.0.0"
EXPECTED_ARTIFACT_SHA256 = (
    "9A02FFDEF3A4117BE48E734F9D44CE0FB31FEFA5839F912426B55EEAB66BDBF4"
)
EXPECTED_DISEASE = "diabetes"
EXPECTED_MODEL_NAME = "Logistic Regression"
EXPECTED_FEATURES = (
    "age",
    "gender",
    "systolic_bp",
    "diastolic_bp",
    "glucose",
    "bmi",
)
EXPECTED_NUMERIC_SUPPORT = {
    "age": (21, 80),
    "systolic_bp": (62, 231),
    "diastolic_bp": (45, 119),
    "glucose": (1.0, 33.46),
    "bmi": (11.47, 54.08),
}
VALID_ROW = {
    "age": 55,
    "gender": 1,
    "systolic_bp": 130,
    "diastolic_bp": 80,
    "glucose": 7.5,
    "bmi": 25.0,
}

DIABD_FILENAME = (
    "DiaBD_A Diabetes Dataset for Enhanced Risk Analysis and Research in "
    "Bangladesh.csv"
)
DIABD_SHA256 = "D9F868C9CE8EEFE545294156ED1626F60FDB33F507F9CA021FD34FA4B575741A"
KIDNEY_FILENAME = "kidney_disease_dataset.csv"
KIDNEY_SHA256 = "4A73DF2405F6E102257887502329CC5EC79DB3BD4729D00DA9C96698D8C05199"
PIMA_V2_FILENAME = "diabetes_model_v2.pkl"
PIMA_V2_SHA256 = "2CF6B92BEF3A452DD680A9B37E1FAE5B788BADCB55B4A4EE6A4CFB90F46DCA07"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class DiaBDArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact_path = ML_ROOT / "models" / EXPECTED_ARTIFACT_FILENAME
        cls.metadata_path = ML_ROOT / "models" / EXPECTED_METADATA_FILENAME
        if not cls.artifact_path.is_file() or not cls.metadata_path.is_file():
            raise RuntimeError(
                "Run the Task 13B training entry point before the DiaBD artifact "
                "contract tests."
            )
        cls.artifact, cls.metadata = (
            diabd_loading.load_verified_diabd_artifact(ml_root=ML_ROOT)
        )

    def test_fixed_v3_identity_and_feature_order(self) -> None:
        self.assertEqual(
            diabd_loading.DIABD_ARTIFACT_FILENAME,
            EXPECTED_ARTIFACT_FILENAME,
        )
        self.assertEqual(
            diabd_loading.DIABD_METADATA_FILENAME,
            EXPECTED_METADATA_FILENAME,
        )
        self.assertEqual(diabd_loading.DIABD_MODEL_VERSION, EXPECTED_MODEL_VERSION)
        self.assertEqual(
            diabd_loading.DIABD_ARTIFACT_SHA256,
            EXPECTED_ARTIFACT_SHA256,
        )
        self.assertEqual(self.artifact.model_version, EXPECTED_MODEL_VERSION)
        self.assertEqual(self.artifact.disease, EXPECTED_DISEASE)
        self.assertEqual(self.artifact.model_name, EXPECTED_MODEL_NAME)
        self.assertEqual(self.artifact.feature_names, EXPECTED_FEATURES)
        self.assertEqual(
            tuple(self.metadata["feature_contract"]["feature_order"]),
            EXPECTED_FEATURES,
        )

    def test_fixed_feature_types_ranges_categories_and_units(self) -> None:
        specs = {spec.name: spec for spec in self.artifact.feature_specs}
        self.assertEqual(tuple(specs), EXPECTED_FEATURES)
        for name, (minimum, maximum) in EXPECTED_NUMERIC_SUPPORT.items():
            with self.subTest(feature=name):
                self.assertEqual(specs[name].minimum, minimum)
                self.assertEqual(specs[name].maximum, maximum)

        self.assertEqual(specs["age"].data_type, "integer")
        self.assertEqual(specs["age"].unit, "years")
        self.assertEqual(specs["gender"].data_type, "integer")
        self.assertEqual(specs["gender"].allowed_values, (0, 1))
        self.assertEqual(specs["gender"].value_labels, {0: "Female", 1: "Male"})
        self.assertEqual(specs["systolic_bp"].unit, "mmHg")
        self.assertEqual(specs["diastolic_bp"].unit, "mmHg")
        self.assertEqual(specs["glucose"].unit, "mmol/L")
        self.assertIn("random", specs["glucose"].measurement_context.lower())
        self.assertEqual(specs["bmi"].unit, "kg/m^2")

    def test_metadata_matches_exact_artifact_hash_and_contract(self) -> None:
        metadata = self.metadata
        self.assertEqual(metadata["artifact"]["filename"], EXPECTED_ARTIFACT_FILENAME)
        self.assertEqual(
            _sha256_file(self.artifact_path),
            EXPECTED_ARTIFACT_SHA256,
        )
        self.assertEqual(
            metadata["artifact"]["sha256"].upper(),
            EXPECTED_ARTIFACT_SHA256,
        )
        self.assertEqual(metadata["model_version"], self.artifact.model_version)
        self.assertEqual(metadata["disease"], self.artifact.disease)
        self.assertEqual(
            metadata["classifier"]["display_name"],
            self.artifact.model_name,
        )
        self.assertEqual(
            metadata["feature_contract"]["features"],
            self.artifact.contract_dict()["features"],
        )
        self.assertTrue(
            math.isclose(
                float(metadata["evaluation"]["classification_threshold"]),
                self.artifact.classification_threshold,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )

    def test_valid_one_row_output_shape_range_and_threshold_application(self) -> None:
        probabilities = self.artifact.predict_proba(VALID_ROW)
        scores = self.artifact.predict_risk_score(VALID_ROW)
        predictions = self.artifact.predict(VALID_ROW)

        self.assertEqual(probabilities.shape, (1, 2))
        self.assertEqual(scores.shape, (1,))
        self.assertEqual(predictions.shape, (1,))
        self.assertTrue(np.isfinite(probabilities).all())
        self.assertTrue(((probabilities >= 0.0) & (probabilities <= 1.0)).all())
        np.testing.assert_allclose(probabilities.sum(axis=1), [1.0])
        self.assertEqual(scores[0], probabilities[0, 1])
        self.assertEqual(
            int(predictions[0]),
            int(scores[0] >= self.artifact.classification_threshold),
        )

    def test_positive_class_order_and_threshold_are_explicit(self) -> None:
        classes = self.artifact.pipeline.named_steps["classifier"].classes_

        np.testing.assert_array_equal(classes, [0, 1])
        self.assertTrue(math.isfinite(self.artifact.classification_threshold))
        self.assertGreater(self.artifact.classification_threshold, 0.0)
        self.assertLess(self.artifact.classification_threshold, 1.0)

    def test_fresh_process_loads_from_repository_root_and_scores(self) -> None:
        program = """
import json
from ml_training.eldercare_ml.diabd_loading import load_verified_diabd_artifact

artifact, metadata = load_verified_diabd_artifact()
row = {
    "age": 55,
    "gender": 1,
    "systolic_bp": 130,
    "diastolic_bp": 80,
    "glucose": 7.5,
    "bmi": 25.0,
}
print(json.dumps({
    "version": metadata["model_version"],
    "score": float(artifact.predict_risk_score(row)[0]),
}))
"""
        completed = subprocess.run(
            [sys.executable, "-B", "-c", program],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["version"], EXPECTED_MODEL_VERSION)
        self.assertGreaterEqual(result["score"], 0.0)
        self.assertLessEqual(result["score"], 1.0)

    def test_supported_loader_is_deterministic_across_reloads(self) -> None:
        first, first_metadata = diabd_loading.load_verified_diabd_artifact(
            ml_root=ML_ROOT
        )
        second, second_metadata = diabd_loading.load_verified_diabd_artifact(
            ml_root=ML_ROOT
        )

        np.testing.assert_array_equal(
            first.predict_proba(VALID_ROW),
            second.predict_proba(VALID_ROW),
        )
        self.assertEqual(first.contract_dict(), second.contract_dict())
        self.assertEqual(first_metadata, second_metadata)

    def test_missing_and_extra_inputs_are_rejected(self) -> None:
        missing = dict(VALID_ROW)
        missing.pop("glucose")
        with self.assertRaisesRegex(ValueError, "Missing required features"):
            self.artifact.predict_proba(missing)

        extra = {**VALID_ROW, "fabricated_default": 0}
        with self.assertRaisesRegex(ValueError, "Unexpected features"):
            self.artifact.predict_proba(extra)

    def test_text_boolean_and_non_finite_inputs_are_rejected(self) -> None:
        invalid_values = ("55", True, float("nan"), float("inf"), float("-inf"))
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                row = {**VALID_ROW, "age": invalid}
                with self.assertRaises(ValueError):
                    self.artifact.predict_proba(row)

    def test_every_numeric_feature_rejects_values_outside_support(self) -> None:
        for name, (minimum, maximum) in EXPECTED_NUMERIC_SUPPORT.items():
            for boundary, invalid in (
                ("below", minimum - 1),
                ("above", maximum + 1),
            ):
                with self.subTest(feature=name, boundary=boundary):
                    row = {**VALID_ROW, name: invalid}
                    with self.assertRaises(ValueError):
                        self.artifact.predict_proba(row)

    def test_unsupported_gender_values_are_rejected(self) -> None:
        for invalid in (-1, 2, "Other", None):
            with self.subTest(invalid=invalid):
                row = {**VALID_ROW, "gender": invalid}
                with self.assertRaises(ValueError):
                    self.artifact.predict_proba(row)

    def test_tampered_artifact_is_rejected_before_deserialization(self) -> None:
        metadata_bytes = self.metadata_path.read_bytes()
        tampered_artifact_bytes = self.artifact_path.read_bytes() + b"tampered"

        with patch.object(
            diabd_loading.joblib,
            "load",
            side_effect=AssertionError("unverified bytes reached joblib.load"),
        ) as deserialize:
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                diabd_loading.load_verified_diabd_artifact_bytes(
                    metadata_bytes=metadata_bytes,
                    artifact_bytes=tampered_artifact_bytes,
                )

        deserialize.assert_not_called()

    def test_raw_datasets_and_pima_v2_artifact_are_unchanged(self) -> None:
        raw_data = ML_ROOT / "data"
        expected_hashes = {
            raw_data / DIABD_FILENAME: DIABD_SHA256,
            raw_data / KIDNEY_FILENAME: KIDNEY_SHA256,
            ML_ROOT / "models" / PIMA_V2_FILENAME: PIMA_V2_SHA256,
        }
        for path, expected_hash in expected_hashes.items():
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())
                self.assertEqual(_sha256_file(path), expected_hash)

        self.assertEqual(
            self.metadata["training_dataset"]["sha256"].upper(),
            DIABD_SHA256,
        )


if __name__ == "__main__":
    unittest.main()
