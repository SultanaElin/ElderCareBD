"""Fixed-name, hash-verified loader for the Task 13B DiaBD v3 artifact."""

from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

import joblib

from .artifact import RiskModelArtifact


DIABD_DISEASE = "diabetes"
DIABD_ARTIFACT_FILENAME = "diabetes_model_v3_diabd.pkl"
DIABD_METADATA_FILENAME = "diabetes_model_v3_diabd.metadata.json"
DIABD_MODEL_VERSION = "3.0.0"
DIABD_ARTIFACT_SHA256 = (
    "9A02FFDEF3A4117BE48E734F9D44CE0FB31FEFA5839F912426B55EEAB66BDBF4"
)
DIABD_FEATURE_ORDER = (
    "age",
    "gender",
    "systolic_bp",
    "diastolic_bp",
    "glucose",
    "bmi",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def load_verified_diabd_artifact_bytes(
    *,
    metadata_bytes: bytes,
    artifact_bytes: bytes,
) -> tuple[RiskModelArtifact, dict[str, Any]]:
    """Verify and deserialize the exact immutable bytes supplied by the caller."""

    try:
        metadata = json.loads(metadata_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("DiaBD v3 metadata is not valid UTF-8 JSON.") from exc

    required_sections = {
        "schema_version",
        "model_version",
        "disease",
        "display_name",
        "created_at",
        "decision",
        "artifact",
        "training_dataset",
        "target",
        "feature_contract",
        "preprocessing",
        "classifier",
        "evaluation",
        "comparison_with_pima_v2",
        "runtime",
        "intended_use",
        "prohibited_use",
        "limitations",
        "task14_compatibility",
    }
    if set(metadata) != required_sections:
        missing = sorted(required_sections - set(metadata))
        unexpected = sorted(set(metadata) - required_sections)
        raise ValueError(
            "DiaBD v3 metadata schema mismatch: "
            f"missing={missing}, unexpected={unexpected}."
        )

    identity = metadata.get("artifact", {})
    expected_hash = identity.get("sha256")
    if (
        identity.get("filename") != DIABD_ARTIFACT_FILENAME
        or not isinstance(expected_hash, str)
        or len(expected_hash) != 64
        or expected_hash.upper() != DIABD_ARTIFACT_SHA256
    ):
        raise ValueError("DiaBD v3 metadata contains an invalid artifact identity.")
    actual_hash = _sha256_bytes(artifact_bytes)
    if actual_hash != DIABD_ARTIFACT_SHA256:
        raise ValueError(
            f"DiaBD v3 artifact hash mismatch: expected {DIABD_ARTIFACT_SHA256}, "
            f"got {actual_hash}."
        )

    artifact = joblib.load(io.BytesIO(artifact_bytes))
    if not isinstance(artifact, RiskModelArtifact):
        raise TypeError("Loaded object is not an ElderCareBD RiskModelArtifact.")
    metadata_order = tuple(
        metadata.get("feature_contract", {}).get("feature_order", [])
    )
    metadata_threshold = metadata.get("evaluation", {}).get(
        "classification_threshold"
    )
    if (
        metadata.get("schema_version") != "1.0.0"
        or metadata.get("model_version") != DIABD_MODEL_VERSION
        or artifact.model_version != DIABD_MODEL_VERSION
        or metadata.get("disease") != DIABD_DISEASE
        or artifact.disease != DIABD_DISEASE
        or metadata_order != DIABD_FEATURE_ORDER
        or artifact.feature_names != DIABD_FEATURE_ORDER
        or artifact.model_name != metadata.get("classifier", {}).get("display_name")
        or isinstance(metadata_threshold, bool)
        or not isinstance(metadata_threshold, (int, float))
        or not math.isclose(
            artifact.classification_threshold,
            float(metadata_threshold),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or artifact.contract_dict()["features"]
        != metadata.get("feature_contract", {}).get("features")
    ):
        raise ValueError("DiaBD v3 artifact and metadata contracts differ.")
    return artifact, metadata


def load_verified_diabd_artifact(
    *,
    ml_root: Path | None = None,
) -> tuple[RiskModelArtifact, dict[str, Any]]:
    """Verify the fixed repository artifact hash before deserializing its bytes."""

    root = (ml_root or Path(__file__).resolve().parents[1]).resolve()
    models_dir = (root / "models").resolve()
    metadata_path = (models_dir / DIABD_METADATA_FILENAME).resolve()
    artifact_path = (models_dir / DIABD_ARTIFACT_FILENAME).resolve()
    if (
        metadata_path.parent != models_dir
        or artifact_path.parent != models_dir
        or not metadata_path.is_file()
        or not artifact_path.is_file()
    ):
        raise FileNotFoundError("The fixed DiaBD v3 artifact or metadata is missing.")

    return load_verified_diabd_artifact_bytes(
        metadata_bytes=metadata_path.read_bytes(),
        artifact_bytes=artifact_path.read_bytes(),
    )
