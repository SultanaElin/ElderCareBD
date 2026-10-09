"""Trusted, hash-verified loading contract for Task 14 and offline inspection."""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from .artifact import RiskModelArtifact
SUPPORTED_DISEASES = ("diabetes", "heart")


@dataclass(frozen=True)
class RuntimeModelTrustAnchor:
    """Code-pinned identity for one application runtime model."""

    artifact_filename: str
    artifact_sha256: str
    metadata_filename: str
    metadata_sha256: str


RUNTIME_MODEL_TRUST_ANCHORS = {
    "diabetes": RuntimeModelTrustAnchor(
        artifact_filename="diabetes_model_v3_diabd.pkl",
        artifact_sha256=(
            "9A02FFDEF3A4117BE48E734F9D44CE0FB31FEFA5839F912426B55EEAB66BDBF4"
        ),
        metadata_filename="diabetes_model_v3_diabd.metadata.json",
        metadata_sha256=(
            "53A33B967D807F94A0B37EB11CA616E7A1EF72A879DC2FE9FC5FA8BB169492BB"
        ),
    ),
    "heart": RuntimeModelTrustAnchor(
        artifact_filename="heart_model_v2.pkl",
        artifact_sha256=(
            "E0007FA3135DBF97B5E15D2C9B0BEAF385928DE54D814566F4877D712FE4A103"
        ),
        metadata_filename="heart_model_v2.metadata.json",
        metadata_sha256=(
            "EE32EC47562066C63B82B50071DA0D715EC3B43BFC71F29FAC33379D7B41EE90"
        ),
    ),
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def load_verified_artifact_bytes(
    disease: str,
    *,
    metadata_bytes: bytes,
    artifact_bytes: bytes,
) -> tuple[RiskModelArtifact, dict[str, Any]]:
    """Validate and deserialize the exact bytes already held by the caller.

    Keeping verification and deserialization on the same immutable byte string
    prevents a path from being swapped between a successful hash check and
    pickle execution. A deployment trust anchor should separately pin the
    metadata bytes, as the ElderCareBD backend does.
    """

    if disease not in SUPPORTED_DISEASES:
        raise ValueError(
            f"Unsupported disease '{disease}'. Expected one of "
            f"{list(SUPPORTED_DISEASES)}."
        )
    try:
        metadata = json.loads(metadata_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Model metadata is not valid UTF-8 JSON.") from exc

    artifact_name = metadata.get("artifact", {}).get("filename")
    expected_hash = metadata.get("artifact", {}).get("sha256")
    fixed_name = f"{disease}_model_v2.pkl"
    if artifact_name != fixed_name or not isinstance(expected_hash, str):
        raise ValueError("Model metadata contains an invalid artifact identity.")
    actual_hash = _sha256_bytes(artifact_bytes)
    if actual_hash != expected_hash.upper():
        raise ValueError(
            f"Model artifact hash mismatch: expected {expected_hash}, "
            f"got {actual_hash}."
        )

    artifact = joblib.load(io.BytesIO(artifact_bytes))
    if not isinstance(artifact, RiskModelArtifact):
        raise TypeError("Loaded object is not an ElderCareBD RiskModelArtifact.")
    metadata_order = tuple(metadata.get("feature_contract", {}).get("feature_order", []))
    if artifact.disease != disease or artifact.feature_names != metadata_order:
        raise ValueError("Loaded artifact identity/feature contract differs from metadata.")
    if artifact.model_version != metadata.get("model_version"):
        raise ValueError("Loaded artifact model version differs from metadata.")
    metadata_model_name = metadata.get("classifier", {}).get("display_name")
    if artifact.model_name != metadata_model_name:
        raise ValueError("Loaded artifact model identity differs from metadata.")
    metadata_threshold = metadata.get("evaluation", {}).get(
        "classification_threshold"
    )
    if not isinstance(metadata_threshold, (int, float)) or not math.isclose(
        artifact.classification_threshold,
        float(metadata_threshold),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("Loaded artifact classification threshold differs from metadata.")
    metadata_features = metadata.get("feature_contract", {}).get("features")
    if artifact.contract_dict()["features"] != metadata_features:
        raise ValueError("Loaded artifact feature specifications differ from metadata.")
    return artifact, metadata


def load_verified_artifact(
    disease: str,
    *,
    ml_root: Path | None = None,
) -> tuple[RiskModelArtifact, dict[str, Any]]:
    """Verify metadata and SHA-256 before deserializing one repository-owned model.

    Joblib uses pickle semantics. This function deliberately accepts only the two fixed
    repository artifact names and validates the expected hash before `joblib.load`.
    """

    if disease not in SUPPORTED_DISEASES:
        raise ValueError(
            f"Unsupported disease '{disease}'. Expected one of {list(SUPPORTED_DISEASES)}."
        )
    root = (ml_root or Path(__file__).resolve().parents[1]).resolve()
    models_dir = (root / "models").resolve()
    metadata_path = models_dir / f"{disease}_model_v2.metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Model metadata does not exist: {metadata_path}")

    fixed_name = f"{disease}_model_v2.pkl"
    artifact_path = (models_dir / fixed_name).resolve()
    if artifact_path.parent != models_dir or not artifact_path.is_file():
        raise FileNotFoundError(f"Model artifact does not exist: {artifact_path}")
    return load_verified_artifact_bytes(
        disease,
        metadata_bytes=metadata_path.read_bytes(),
        artifact_bytes=artifact_path.read_bytes(),
    )


def load_verified_runtime_artifact_bytes(
    disease: str,
    *,
    metadata_bytes: bytes,
    artifact_bytes: bytes,
) -> tuple[RiskModelArtifact, dict[str, Any]]:
    """Load one final application model only after both byte hashes are trusted.

    This is intentionally separate from :func:`load_verified_artifact`, which
    remains the Task 13 research-comparator loader for the two v2 artifacts.
    Hashing the same immutable byte strings that are later parsed/deserialized
    closes the check/use gap inherent in verifying a path and reopening it.
    """

    anchor = RUNTIME_MODEL_TRUST_ANCHORS.get(disease)
    if anchor is None:
        raise ValueError(
            f"Unsupported runtime disease '{disease}'. Expected one of "
            f"{list(RUNTIME_MODEL_TRUST_ANCHORS)}."
        )

    actual_metadata_hash = _sha256_bytes(metadata_bytes)
    if actual_metadata_hash != anchor.metadata_sha256:
        raise ValueError(
            "Runtime model metadata hash mismatch: expected "
            f"{anchor.metadata_sha256}, got {actual_metadata_hash}."
        )
    actual_artifact_hash = _sha256_bytes(artifact_bytes)
    if actual_artifact_hash != anchor.artifact_sha256:
        raise ValueError(
            "Runtime model artifact hash mismatch: expected "
            f"{anchor.artifact_sha256}, got {actual_artifact_hash}."
        )

    if disease == "diabetes":
        from .diabd_loading import load_verified_diabd_artifact_bytes

        return load_verified_diabd_artifact_bytes(
            metadata_bytes=metadata_bytes,
            artifact_bytes=artifact_bytes,
        )
    return load_verified_artifact_bytes(
        disease,
        metadata_bytes=metadata_bytes,
        artifact_bytes=artifact_bytes,
    )


def load_verified_runtime_artifact(
    disease: str,
) -> tuple[RiskModelArtifact, dict[str, Any]]:
    """Load a final model from its sole fixed repository-owned location.

    No caller-controlled root or path is accepted. A symlink that resolves out
    of the repository models directory is rejected before any bytes are read.
    """

    anchor = RUNTIME_MODEL_TRUST_ANCHORS.get(disease)
    if anchor is None:
        raise ValueError(
            f"Unsupported runtime disease '{disease}'. Expected one of "
            f"{list(RUNTIME_MODEL_TRUST_ANCHORS)}."
        )

    models_dir = (Path(__file__).resolve().parents[1] / "models").resolve()
    metadata_path = (models_dir / anchor.metadata_filename).resolve()
    artifact_path = (models_dir / anchor.artifact_filename).resolve()
    if (
        metadata_path.parent != models_dir
        or artifact_path.parent != models_dir
        or not metadata_path.is_file()
        or not artifact_path.is_file()
    ):
        raise FileNotFoundError("The fixed runtime model artifact or metadata is missing.")

    return load_verified_runtime_artifact_bytes(
        disease,
        metadata_bytes=metadata_path.read_bytes(),
        artifact_bytes=artifact_path.read_bytes(),
    )
