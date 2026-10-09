from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


ML_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ML_ROOT.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ml_training.eldercare_ml.artifact import RiskModelArtifact  # noqa: E402
from ml_training.eldercare_ml.data import sha256_file  # noqa: E402
from ml_training.eldercare_ml.loading import load_verified_artifact  # noqa: E402
from ml_training.eldercare_ml.training import LEGACY_ARTIFACTS  # noqa: E402


VALID_ROWS = {
    "diabetes": {"Age": 55, "Glucose": 130, "BMI": 31.5},
    "heart": {"age": 60, "sex": 1, "cp": 2, "trestbps": 130},
}


class ArtifactContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifacts: dict[str, RiskModelArtifact] = {}
        cls.metadata: dict[str, dict] = {}
        for disease in ("diabetes", "heart"):
            artifact_path = ML_ROOT / "models" / f"{disease}_model_v2.pkl"
            metadata_path = ML_ROOT / "models" / f"{disease}_model_v2.metadata.json"
            if not artifact_path.is_file() or not metadata_path.is_file():
                raise RuntimeError(
                    "Run train_models_v2.py before the artifact contract tests."
                )
            cls.artifacts[disease] = joblib.load(artifact_path)
            cls.metadata[disease] = json.loads(metadata_path.read_text(encoding="utf-8"))

    def test_selected_artifacts_load_and_match_metadata_hashes(self) -> None:
        for disease, artifact in self.artifacts.items():
            with self.subTest(disease=disease):
                self.assertIsInstance(artifact, RiskModelArtifact)
                metadata = self.metadata[disease]
                artifact_path = ML_ROOT / "models" / f"{disease}_model_v2.pkl"
                self.assertEqual(
                    sha256_file(artifact_path), metadata["artifact"]["sha256"]
                )
                self.assertEqual(artifact.model_version, metadata["model_version"])

    def test_supported_loader_verifies_and_loads_contract(self) -> None:
        for disease in ("diabetes", "heart"):
            with self.subTest(disease=disease):
                artifact, metadata = load_verified_artifact(disease, ml_root=ML_ROOT)
                self.assertEqual(artifact.disease, disease)
                self.assertEqual(
                    list(artifact.feature_names),
                    metadata["feature_contract"]["feature_order"],
                )

    def test_fresh_process_loads_from_repository_root_without_path_injection(self) -> None:
        command = (
            "from ml_training.eldercare_ml.loading import load_verified_artifact; "
            "d, dm = load_verified_artifact('diabetes'); "
            "h, hm = load_verified_artifact('heart'); "
            "assert list(d.feature_names) == dm['feature_contract']['feature_order']; "
            "assert list(h.feature_names) == hm['feature_contract']['feature_order']; "
            "print(d.model_version + '/' + h.model_version)"
        )
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "2.0.0/2.0.0")

    def test_loader_rejects_unsupported_disease_and_tampered_artifact(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported disease"):
            load_verified_artifact("kidney", ml_root=ML_ROOT)

        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            temporary_models = temporary_root / "models"
            temporary_models.mkdir()
            for suffix in ("pkl", "metadata.json"):
                filename = f"diabetes_model_v2.{suffix}"
                shutil.copyfile(
                    ML_ROOT / "models" / filename,
                    temporary_models / filename,
                )
            artifact_path = temporary_models / "diabetes_model_v2.pkl"
            artifact_path.write_bytes(artifact_path.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_verified_artifact("diabetes", ml_root=temporary_root)

    def test_loader_rejects_metadata_contract_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            temporary_models = temporary_root / "models"
            temporary_models.mkdir()
            for suffix in ("pkl", "metadata.json"):
                filename = f"heart_model_v2.{suffix}"
                shutil.copyfile(
                    ML_ROOT / "models" / filename,
                    temporary_models / filename,
                )
            metadata_path = temporary_models / "heart_model_v2.metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["evaluation"]["classification_threshold"] = 0.99
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "threshold differs"):
                load_verified_artifact("heart", ml_root=temporary_root)

    def test_exact_feature_contract_matches_metadata_and_pipeline(self) -> None:
        for disease, artifact in self.artifacts.items():
            with self.subTest(disease=disease):
                metadata_order = tuple(
                    self.metadata[disease]["feature_contract"]["feature_order"]
                )
                self.assertEqual(artifact.feature_names, metadata_order)
                schema = artifact.pipeline.named_steps["schema"]
                self.assertEqual(tuple(schema.required_features), metadata_order)

    def test_one_valid_row_has_binary_probability_shape_and_range(self) -> None:
        for disease, artifact in self.artifacts.items():
            with self.subTest(disease=disease):
                probabilities = artifact.predict_proba(VALID_ROWS[disease])
                predictions = artifact.predict(VALID_ROWS[disease])
                self.assertEqual(probabilities.shape, (1, 2))
                self.assertEqual(predictions.shape, (1,))
                self.assertTrue(np.isfinite(probabilities).all())
                self.assertTrue(((probabilities >= 0) & (probabilities <= 1)).all())
                np.testing.assert_allclose(probabilities.sum(axis=1), [1.0])
                self.assertIn(int(predictions[0]), (0, 1))

    def test_missing_required_feature_is_rejected(self) -> None:
        for disease, artifact in self.artifacts.items():
            row = dict(VALID_ROWS[disease])
            row.pop(next(iter(row)))
            with self.subTest(disease=disease):
                with self.assertRaisesRegex(ValueError, "Missing required features"):
                    artifact.predict_proba(row)

    def test_unexpected_feature_is_rejected(self) -> None:
        for disease, artifact in self.artifacts.items():
            row = {**VALID_ROWS[disease], "fabricated_default": 0}
            with self.subTest(disease=disease):
                with self.assertRaisesRegex(ValueError, "Unexpected features"):
                    artifact.predict_proba(row)

    def test_non_numeric_non_finite_and_boolean_values_are_rejected(self) -> None:
        artifact = self.artifacts["diabetes"]
        for invalid in ("unknown", "55", float("nan"), float("inf"), True):
            row = {**VALID_ROWS["diabetes"], "Age": invalid}
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    artifact.predict_proba(row)

    def test_out_of_training_support_is_rejected(self) -> None:
        cases = [
            ("diabetes", {**VALID_ROWS["diabetes"], "Age": 90}),
            ("diabetes", {**VALID_ROWS["diabetes"], "Glucose": 0}),
            ("heart", {**VALID_ROWS["heart"], "age": 85}),
            ("heart", {**VALID_ROWS["heart"], "trestbps": 250}),
        ]
        for disease, row in cases:
            with self.subTest(disease=disease, row=row):
                with self.assertRaises(ValueError):
                    self.artifacts[disease].predict_proba(row)

    def test_unknown_heart_categories_and_other_gender_are_rejected(self) -> None:
        artifact = self.artifacts["heart"]
        for field, invalid in (("sex", 2), ("sex", "Other"), ("cp", 4)):
            row = {**VALID_ROWS["heart"], field: invalid}
            with self.subTest(field=field, invalid=invalid):
                with self.assertRaises(ValueError):
                    artifact.predict_proba(row)

    def test_column_order_is_normalized_without_changing_prediction(self) -> None:
        for disease, artifact in self.artifacts.items():
            row = VALID_ROWS[disease]
            ordered = pd.DataFrame([row], columns=list(artifact.feature_names))
            reversed_frame = ordered.loc[:, list(reversed(artifact.feature_names))]
            with self.subTest(disease=disease):
                np.testing.assert_allclose(
                    artifact.predict_proba(ordered),
                    artifact.predict_proba(reversed_frame),
                )

    def test_reloading_is_prediction_reproducible(self) -> None:
        for disease, artifact in self.artifacts.items():
            path = ML_ROOT / "models" / f"{disease}_model_v2.pkl"
            second_load = joblib.load(path)
            with self.subTest(disease=disease):
                np.testing.assert_array_equal(
                    artifact.predict_proba(VALID_ROWS[disease]),
                    second_load.predict_proba(VALID_ROWS[disease]),
                )

    def test_threshold_is_finite_and_applied_to_positive_score(self) -> None:
        for disease, artifact in self.artifacts.items():
            score = artifact.predict_risk_score(VALID_ROWS[disease])
            predicted = artifact.predict(VALID_ROWS[disease])
            with self.subTest(disease=disease):
                self.assertTrue(math.isfinite(artifact.classification_threshold))
                self.assertGreater(artifact.classification_threshold, 0)
                self.assertLess(artifact.classification_threshold, 1)
                self.assertEqual(
                    int(predicted[0]),
                    int(score[0] >= artifact.classification_threshold),
                )

    def test_legacy_artifact_hashes_remain_unchanged(self) -> None:
        for disease, expected in LEGACY_ARTIFACTS.items():
            with self.subTest(disease=disease):
                self.assertEqual(
                    sha256_file(ML_ROOT / "models" / expected["filename"]),
                    expected["sha256"],
                )


if __name__ == "__main__":
    unittest.main()
