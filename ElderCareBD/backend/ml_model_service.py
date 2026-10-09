"""Trusted, process-cached inference access for ElderCareBD's final ML models.

The serialized models are repository-owned pickle/joblib artifacts.  This module
therefore fixes their locations and pins both metadata and artifact hashes in
code before the Task 13 loader is imported or deserialization is attempted.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import logging
import math
import platform
import sys
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)

PREDICTION_SOURCES = {
    "diabetes": "task13b_diabd_v3_model",
    "heart": "task13_heart_v2_model",
}
PREDICTION_DISCLAIMER = (
    "Research/demo screening score only; this is not a diagnosis or an "
    "individual disease probability. Seek advice from a qualified clinician."
)

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
_ML_ROOT = (_REPOSITORY_ROOT / "ml_training").resolve()
_MODELS_DIRECTORY = (_ML_ROOT / "models").resolve()

_TRUSTED_MODELS = {
    "diabetes": {
        "artifact_name": "diabetes_model_v3_diabd.pkl",
        "artifact_size": 6332,
        "artifact_sha256": (
            "9A02FFDEF3A4117BE48E734F9D44CE0FB31FEFA5839F912426B55EEAB66BDBF4"
        ),
        "metadata_name": "diabetes_model_v3_diabd.metadata.json",
        "metadata_size": 133891,
        "metadata_sha256": (
            "53A33B967D807F94A0B37EB11CA616E7A1EF72A879DC2FE9FC5FA8BB169492BB"
        ),
        "model_version": "3.0.0",
        "feature_order": (
            "age",
            "gender",
            "systolic_bp",
            "diastolic_bp",
            "glucose",
            "bmi",
        ),
    },
    "heart": {
        "artifact_name": "heart_model_v2.pkl",
        "artifact_size": 2742,
        "artifact_sha256": (
            "E0007FA3135DBF97B5E15D2C9B0BEAF385928DE54D814566F4877D712FE4A103"
        ),
        "metadata_name": "heart_model_v2.metadata.json",
        "metadata_size": 20889,
        "metadata_sha256": (
            "EE32EC47562066C63B82B50071DA0D715EC3B43BFC71F29FAC33379D7B41EE90"
        ),
        "model_version": "2.0.0",
        "feature_order": ("age", "sex", "cp", "trestbps"),
    },
}

_INFERENCE_RUNTIME = {
    "joblib": ("joblib", "1.5.3"),
    "numpy": ("numpy", "2.5.1"),
    "pandas": ("pandas", "3.0.3"),
    "scikit_learn": ("scikit-learn", "1.9.0"),
    "scipy": ("scipy", "1.18.0"),
}
_EXPECTED_PYTHON_VERSION = "3.13.6"


class ModelUnavailableError(RuntimeError):
    """The requested trusted model is not available in this process."""


class ModelContractError(ValueError):
    """Inputs do not satisfy the verified model feature contract."""


class ModelInferenceError(RuntimeError):
    """A loaded model could not safely produce a valid score."""


@dataclass(frozen=True)
class PredictionResult:
    disease: str
    prediction_source: str
    model_version: str
    risk_score: float
    classification: str
    threshold: float
    features_used: dict[str, int | float]
    disclaimer: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "disease": self.disease,
            "prediction_source": self.prediction_source,
            "model_version": self.model_version,
            "risk_score": self.risk_score,
            "classification": self.classification,
            "threshold": self.threshold,
            "features_used": dict(self.features_used),
            "disclaimer": self.disclaimer,
        }


@dataclass(frozen=True)
class _LoadedModel:
    artifact: Any
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _ModelState:
    loaded: _LoadedModel | None

    @property
    def available(self) -> bool:
        return self.loaded is not None


@dataclass(frozen=True)
class _VerifiedModelFiles:
    metadata: dict[str, Any]
    metadata_bytes: bytes
    artifact_bytes: bytes


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _read_exact_file(path: Path, expected_size: int) -> bytes:
    try:
        with path.open("rb") as handle:
            value = handle.read(expected_size + 1)
    except OSError as exc:
        raise ModelUnavailableError("Trusted model files are unavailable.") from exc
    if len(value) != expected_size:
        raise ModelUnavailableError("Trusted model file size verification failed.")
    return value


def _read_verified_repository_files(disease: str) -> _VerifiedModelFiles:
    """Read each fixed file once, then verify the exact immutable byte strings."""

    spec = _TRUSTED_MODELS.get(disease)
    if spec is None:
        raise ModelUnavailableError("Unsupported model.")

    metadata_path = (_MODELS_DIRECTORY / spec["metadata_name"]).resolve()
    artifact_path = (_MODELS_DIRECTORY / spec["artifact_name"]).resolve()
    if (
        metadata_path.parent != _MODELS_DIRECTORY
        or artifact_path.parent != _MODELS_DIRECTORY
        or not metadata_path.is_file()
        or not artifact_path.is_file()
    ):
        raise ModelUnavailableError("Trusted model files are unavailable.")

    metadata_bytes = _read_exact_file(metadata_path, spec["metadata_size"])
    artifact_bytes = _read_exact_file(artifact_path, spec["artifact_size"])
    if _sha256_bytes(metadata_bytes) != spec["metadata_sha256"]:
        raise ModelUnavailableError("Trusted model metadata verification failed.")
    if _sha256_bytes(artifact_bytes) != spec["artifact_sha256"]:
        raise ModelUnavailableError("Trusted model artifact verification failed.")

    try:
        metadata = json.loads(metadata_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ModelUnavailableError("Trusted model metadata is invalid.") from exc

    artifact_identity = metadata.get("artifact", {})
    feature_order = tuple(
        metadata.get("feature_contract", {}).get("feature_order", [])
    )
    if (
        metadata.get("schema_version") != "1.0.0"
        or metadata.get("model_version") != spec["model_version"]
        or metadata.get("disease") != disease
        or artifact_identity.get("filename") != spec["artifact_name"]
        or str(artifact_identity.get("sha256", "")).upper()
        != spec["artifact_sha256"]
        or feature_order != spec["feature_order"]
    ):
        raise ModelUnavailableError("Trusted model identity verification failed.")
    return _VerifiedModelFiles(
        metadata=metadata,
        metadata_bytes=metadata_bytes,
        artifact_bytes=artifact_bytes,
    )


def _verify_repository_files(disease: str) -> dict[str, Any]:
    """Verify both fixed trust anchors without importing pickle dependencies."""

    return _read_verified_repository_files(disease).metadata


def _validate_runtime(metadata: dict[str, Any]) -> None:
    declared_runtime = metadata.get("runtime")
    if not isinstance(declared_runtime, dict):
        raise ModelUnavailableError("Model runtime metadata is unavailable.")

    if (
        declared_runtime.get("python") != _EXPECTED_PYTHON_VERSION
        or platform.python_version() != _EXPECTED_PYTHON_VERSION
    ):
        raise ModelUnavailableError("The model runtime is incompatible.")

    for metadata_key, (distribution_name, expected_version) in _INFERENCE_RUNTIME.items():
        if declared_runtime.get(metadata_key) != expected_version:
            raise ModelUnavailableError("The model runtime metadata is incompatible.")
        try:
            installed_version = importlib.metadata.version(distribution_name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ModelUnavailableError("A model runtime dependency is unavailable.") from exc
        if installed_version != expected_version:
            raise ModelUnavailableError("A model runtime dependency is incompatible.")


def _validate_binary_classifier(artifact: Any) -> None:
    classes = getattr(getattr(artifact, "pipeline", None), "classes_", None)
    if classes is None:
        raise ModelUnavailableError("The model classifier contract is unavailable.")
    try:
        normalized_classes = list(classes)
    except TypeError as exc:
        raise ModelUnavailableError("The model classifier contract is invalid.") from exc
    if normalized_classes != [0, 1]:
        raise ModelUnavailableError("The model classifier classes are incompatible.")


def _validate_loaded_model(
    disease: str,
    artifact: Any,
    metadata: dict[str, Any],
) -> None:
    spec = _TRUSTED_MODELS[disease]
    metadata_order = tuple(
        metadata.get("feature_contract", {}).get("feature_order", [])
    )
    artifact_order = tuple(getattr(artifact, "feature_names", ()))
    metadata_threshold = metadata.get("evaluation", {}).get(
        "classification_threshold"
    )
    artifact_threshold = getattr(artifact, "classification_threshold", None)
    if (
        getattr(artifact, "disease", None) != disease
        or artifact_order != spec["feature_order"]
        or metadata_order != spec["feature_order"]
        or getattr(artifact, "model_version", None) != metadata.get("model_version")
        or metadata.get(
            "positive_class",
            metadata.get("target", {}).get("positive_class"),
        )
        != 1
        or isinstance(metadata_threshold, bool)
        or not isinstance(metadata_threshold, (int, float))
        or isinstance(artifact_threshold, bool)
        or not isinstance(artifact_threshold, (int, float))
        or not math.isfinite(float(metadata_threshold))
        or not 0.0 <= float(metadata_threshold) <= 1.0
        or not math.isclose(
            float(artifact_threshold),
            float(metadata_threshold),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ModelUnavailableError("The loaded model contract is incompatible.")
    _validate_binary_classifier(artifact)


def _smoke_loaded_model(artifact: Any, metadata: dict[str, Any]) -> None:
    """Run one metadata-derived prediction before a model becomes available."""

    contract = metadata.get("feature_contract", {})
    feature_order = contract.get("feature_order")
    raw_features = contract.get("features")
    if not isinstance(feature_order, list) or not isinstance(raw_features, list):
        raise ModelUnavailableError("The model smoke-test contract is unavailable.")
    feature_specs = {
        item.get("name"): item for item in raw_features if isinstance(item, dict)
    }
    smoke_features: dict[str, int | float] = {}
    for name in feature_order:
        spec = feature_specs.get(name)
        if not isinstance(spec, dict):
            raise ModelUnavailableError("The model smoke-test contract is invalid.")
        allowed_values = spec.get("allowed_values")
        if isinstance(allowed_values, list) and allowed_values:
            value = allowed_values[0]
        else:
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if (
                isinstance(minimum, bool)
                or isinstance(maximum, bool)
                or not isinstance(minimum, (int, float))
                or not isinstance(maximum, (int, float))
                or not math.isfinite(float(minimum))
                or not math.isfinite(float(maximum))
                or minimum > maximum
            ):
                raise ModelUnavailableError("The model smoke-test range is invalid.")
            midpoint = (float(minimum) + float(maximum)) / 2.0
            value = round(midpoint) if spec.get("type") == "integer" else midpoint
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ModelUnavailableError("The model smoke-test value is invalid.")
        smoke_features[name] = value

    try:
        raw_scores = artifact.predict_risk_score(smoke_features)
        if len(raw_scores) != 1:
            raise ValueError("unexpected score shape")
        score = float(raw_scores[0])
    except Exception as exc:
        raise ModelUnavailableError("The model smoke prediction failed.") from exc
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ModelUnavailableError("The model smoke prediction was invalid.")


def _load_trusted_model(disease: str) -> tuple[Any, dict[str, Any]]:
    verified = _read_verified_repository_files(disease)
    _validate_runtime(verified.metadata)

    repository_root_text = str(_REPOSITORY_ROOT)
    sys.path[:] = [entry for entry in sys.path if entry != repository_root_text]
    sys.path.insert(0, repository_root_text)

    # Import only after the code-level metadata and artifact pins are verified.
    from ml_training.eldercare_ml import loading as trusted_loading

    expected_loader_path = (_ML_ROOT / "eldercare_ml" / "loading.py").resolve()
    actual_loader_path = Path(trusted_loading.__file__).resolve()
    if actual_loader_path != expected_loader_path:
        raise ModelUnavailableError("The trusted model loader is unavailable.")

    artifact, loaded_metadata = trusted_loading.load_verified_runtime_artifact_bytes(
        disease,
        metadata_bytes=verified.metadata_bytes,
        artifact_bytes=verified.artifact_bytes,
    )
    if loaded_metadata != verified.metadata:
        raise ModelUnavailableError("Loaded model metadata is inconsistent.")
    _validate_loaded_model(disease, artifact, loaded_metadata)
    _smoke_loaded_model(artifact, loaded_metadata)
    return artifact, loaded_metadata


class MlModelService:
    """Load each disease independently and retain one state per process."""

    def __init__(
        self,
        loader: Callable[[str], tuple[Any, dict[str, Any]]] | None = None,
    ) -> None:
        self._loader = loader or _load_trusted_model
        self._states: dict[str, _ModelState] = {}
        self._lock = threading.RLock()

    def warm(self) -> None:
        for disease in _TRUSTED_MODELS:
            self._ensure_state(disease)

    def _ensure_state(self, disease: str) -> _ModelState:
        if disease not in _TRUSTED_MODELS:
            raise ModelUnavailableError("Unsupported model.")
        with self._lock:
            existing = self._states.get(disease)
            if existing is not None:
                return existing
            try:
                artifact, metadata = self._loader(disease)
                _validate_loaded_model(disease, artifact, metadata)
                state = _ModelState(_LoadedModel(artifact=artifact, metadata=metadata))
            except Exception as exc:  # A failed model must not stop the API process.
                logger.warning(
                    "Risk model disabled: disease=%s error_type=%s",
                    disease,
                    type(exc).__name__,
                )
                state = _ModelState(None)
            self._states[disease] = state
            return state

    def _require_loaded(self, disease: str) -> _LoadedModel:
        state = self._ensure_state(disease)
        if state.loaded is None:
            raise ModelUnavailableError(f"The {disease} model is unavailable.")
        return state.loaded

    @staticmethod
    def _label_code(
        metadata: dict[str, Any],
        feature_name: str,
        label: str,
    ) -> int:
        features = metadata.get("feature_contract", {}).get("features", [])
        feature = next(
            (
                item
                for item in features
                if isinstance(item, dict) and item.get("name") == feature_name
            ),
            None,
        )
        labels = feature.get("value_labels") if feature is not None else None
        allowed_values = feature.get("allowed_values") if feature is not None else None
        if not isinstance(labels, dict) or not isinstance(allowed_values, list):
            raise ModelUnavailableError("The model category contract is unavailable.")

        matches = [raw_code for raw_code, value in labels.items() if value == label]
        if len(matches) != 1:
            raise ModelContractError(
                f"Unsupported {feature_name.replace('_', ' ')} category."
            )
        try:
            code = int(matches[0])
        except (TypeError, ValueError) as exc:
            raise ModelUnavailableError("The model category contract is invalid.") from exc
        if code not in allowed_values:
            raise ModelUnavailableError("The model category contract is inconsistent.")
        return code

    def _predict(
        self,
        disease: str,
        features: dict[str, int | float],
    ) -> PredictionResult:
        loaded = self._require_loaded(disease)
        try:
            raw_scores = loaded.artifact.predict_risk_score(features)
            score = float(raw_scores[0])
        except (TypeError, ValueError, IndexError) as exc:
            raise ModelContractError(
                "Prediction input is outside the verified model contract."
            ) from exc
        except Exception as exc:
            raise ModelInferenceError("The model could not produce a score.") from exc

        threshold = float(loaded.artifact.classification_threshold)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ModelInferenceError("The model produced an invalid score.")
        classification = (
            "at_or_above_model_threshold"
            if score >= threshold
            else "below_model_threshold"
        )
        return PredictionResult(
            disease=disease,
            prediction_source=PREDICTION_SOURCES[disease],
            model_version=str(loaded.artifact.model_version),
            risk_score=score,
            classification=classification,
            threshold=threshold,
            features_used=dict(features),
            disclaimer=PREDICTION_DISCLAIMER,
        )

    def predict_diabetes(
        self,
        age: int,
        gender: str,
        systolic_bp: int,
        diastolic_bp: int,
        random_glucose_mmol_l: int | float,
        bmi: int | float,
    ) -> PredictionResult:
        if diastolic_bp >= systolic_bp:
            raise ModelContractError(
                "Diastolic blood pressure must be below systolic blood pressure."
            )
        loaded = self._require_loaded("diabetes")
        gender_code = self._label_code(loaded.metadata, "gender", gender)
        return self._predict(
            "diabetes",
            {
                "age": age,
                "gender": gender_code,
                "systolic_bp": systolic_bp,
                "diastolic_bp": diastolic_bp,
                "glucose": random_glucose_mmol_l,
                "bmi": bmi,
            },
        )

    def predict_heart(
        self,
        age: int,
        clinical_sex: str,
        chest_pain_type: str,
        resting_systolic_bp_mm_hg: int,
    ) -> PredictionResult:
        loaded = self._require_loaded("heart")
        sex_code = self._label_code(loaded.metadata, "sex", clinical_sex)
        chest_pain_code = self._label_code(
            loaded.metadata,
            "cp",
            chest_pain_type,
        )
        return self._predict(
            "heart",
            {
                "age": age,
                "sex": sex_code,
                "cp": chest_pain_code,
                "trestbps": resting_systolic_bp_mm_hg,
            },
        )

    def contracts(self) -> dict[str, Any]:
        models: dict[str, dict[str, Any]] = {}
        for disease in _TRUSTED_MODELS:
            state = self._ensure_state(disease)
            if state.loaded is None:
                models[disease] = {
                    "disease": disease,
                    "available": False,
                    "model_version": None,
                    "model_name": None,
                    "prediction_source": PREDICTION_SOURCES[disease],
                    "threshold": None,
                    "features": [],
                }
                continue
            metadata = state.loaded.metadata
            models[disease] = {
                "disease": disease,
                "available": True,
                "model_version": metadata["model_version"],
                "model_name": metadata.get("display_name"),
                "prediction_source": PREDICTION_SOURCES[disease],
                "threshold": float(state.loaded.artifact.classification_threshold),
                "features": copy.deepcopy(
                    metadata.get("feature_contract", {}).get("features", [])
                ),
            }
        return {"models": models}


@lru_cache(maxsize=1)
def get_ml_model_service() -> MlModelService:
    service = MlModelService()
    service.warm()
    return service


def warm_ml_models() -> None:
    """Best-effort startup warm-up; unavailable models remain isolated fallbacks."""

    get_ml_model_service()
