from __future__ import annotations

import inspect
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ML_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ML_ROOT.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ml_training.eldercare_ml import loading  # noqa: E402


class RuntimeLoadingTests(unittest.TestCase):
    def test_final_runtime_trust_anchors_are_exact(self) -> None:
        diabetes = loading.RUNTIME_MODEL_TRUST_ANCHORS["diabetes"]
        heart = loading.RUNTIME_MODEL_TRUST_ANCHORS["heart"]

        self.assertEqual(diabetes.artifact_filename, "diabetes_model_v3_diabd.pkl")
        self.assertEqual(
            diabetes.artifact_sha256,
            "9A02FFDEF3A4117BE48E734F9D44CE0FB31FEFA5839F912426B55EEAB66BDBF4",
        )
        self.assertEqual(
            diabetes.metadata_sha256,
            "53A33B967D807F94A0B37EB11CA616E7A1EF72A879DC2FE9FC5FA8BB169492BB",
        )
        self.assertEqual(heart.artifact_filename, "heart_model_v2.pkl")
        self.assertEqual(
            heart.artifact_sha256,
            "E0007FA3135DBF97B5E15D2C9B0BEAF385928DE54D814566F4877D712FE4A103",
        )
        self.assertEqual(
            heart.metadata_sha256,
            "EE32EC47562066C63B82B50071DA0D715EC3B43BFC71F29FAC33379D7B41EE90",
        )

    def test_final_diabetes_and_heart_load_from_fixed_repository_files(self) -> None:
        diabetes, diabetes_metadata = loading.load_verified_runtime_artifact(
            "diabetes"
        )
        heart, heart_metadata = loading.load_verified_runtime_artifact("heart")

        self.assertEqual(diabetes.model_version, "3.0.0")
        self.assertEqual(
            diabetes.feature_names,
            ("age", "gender", "systolic_bp", "diastolic_bp", "glucose", "bmi"),
        )
        self.assertEqual(diabetes.classification_threshold, 0.06)
        self.assertEqual(diabetes_metadata["model_version"], "3.0.0")
        self.assertEqual(heart.model_version, "2.0.0")
        self.assertEqual(heart.feature_names, ("age", "sex", "cp", "trestbps"))
        self.assertEqual(heart.classification_threshold, 0.53)
        self.assertEqual(heart_metadata["model_version"], "2.0.0")

    def test_tampered_metadata_is_rejected_before_deserialization(self) -> None:
        anchor = loading.RUNTIME_MODEL_TRUST_ANCHORS["diabetes"]
        metadata = (ML_ROOT / "models" / anchor.metadata_filename).read_bytes()
        artifact = (ML_ROOT / "models" / anchor.artifact_filename).read_bytes()

        with mock.patch.object(
            loading.joblib,
            "load",
            side_effect=AssertionError("deserialization must not run"),
        ) as deserialize:
            with self.assertRaisesRegex(ValueError, "metadata hash mismatch"):
                loading.load_verified_runtime_artifact_bytes(
                    "diabetes",
                    metadata_bytes=metadata + b" ",
                    artifact_bytes=artifact,
                )
        deserialize.assert_not_called()

    def test_tampered_artifact_is_rejected_before_deserialization(self) -> None:
        anchor = loading.RUNTIME_MODEL_TRUST_ANCHORS["heart"]
        metadata = (ML_ROOT / "models" / anchor.metadata_filename).read_bytes()
        artifact = (ML_ROOT / "models" / anchor.artifact_filename).read_bytes()

        with mock.patch.object(
            loading.joblib,
            "load",
            side_effect=AssertionError("deserialization must not run"),
        ) as deserialize:
            with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
                loading.load_verified_runtime_artifact_bytes(
                    "heart",
                    metadata_bytes=metadata,
                    artifact_bytes=artifact + b"tampered",
                )
        deserialize.assert_not_called()

    def test_runtime_loader_rejects_unsupported_models_and_caller_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported runtime disease"):
            loading.load_verified_runtime_artifact("kidney")
        self.assertNotIn(
            "ml_root",
            inspect.signature(loading.load_verified_runtime_artifact).parameters,
        )
        with self.assertRaises(TypeError):
            loading.load_verified_runtime_artifact(  # type: ignore[call-arg]
                "diabetes", ml_root=ML_ROOT
            )

    def test_fresh_process_loads_only_final_runtime_models(self) -> None:
        command = (
            "from ml_training.eldercare_ml.loading import "
            "load_verified_runtime_artifact; "
            "d, _ = load_verified_runtime_artifact('diabetes'); "
            "h, _ = load_verified_runtime_artifact('heart'); "
            "assert d.feature_names == "
            "('age','gender','systolic_bp','diastolic_bp','glucose','bmi'); "
            "assert h.feature_names == ('age','sex','cp','trestbps'); "
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
        self.assertEqual(completed.stdout.strip(), "3.0.0/2.0.0")


if __name__ == "__main__":
    unittest.main()
