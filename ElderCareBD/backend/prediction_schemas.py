"""Strict HTTP contracts for Task 14 model inference."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


ModelCategoryLabel = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        strict=True,
    ),
]


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DiabetesPredictionRequest(_StrictRequest):
    patient_id: int = Field(gt=0)
    age: int = Field(ge=21, le=80)
    gender: Literal["Female", "Male"]
    systolic_bp: int = Field(ge=62, le=231)
    diastolic_bp: int = Field(ge=45, le=119)
    random_glucose_mmol_l: float = Field(
        ge=1.0,
        le=33.46,
        allow_inf_nan=False,
    )
    bmi: float = Field(ge=11.47, le=54.08, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_blood_pressure_pair(self):
        if self.diastolic_bp >= self.systolic_bp:
            raise ValueError("Diastolic BP must be lower than systolic BP")
        return self


class HeartPredictionRequest(_StrictRequest):
    patient_id: int = Field(gt=0)
    age: int = Field(ge=29, le=77)
    # The trusted metadata is the single source of supported category labels;
    # the HTTP schema deliberately does not duplicate its numeric mapping.
    clinical_sex: ModelCategoryLabel
    chest_pain_type: ModelCategoryLabel
    blood_pressure_context: Literal["resting_systolic"]
    resting_systolic_bp_mm_hg: int = Field(ge=94, le=200)


class PredictionResponse(BaseModel):
    patient_id: int
    disease: Literal["diabetes", "heart"]
    prediction_source: Literal[
        "task13b_diabd_v3_model",
        "task13_heart_v2_model",
    ]
    model_version: str
    risk_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    classification: Literal[
        "below_model_threshold",
        "at_or_above_model_threshold",
    ]
    threshold: float = Field(ge=0, le=1, allow_inf_nan=False)
    features_used: dict[str, int | float]
    disclaimer: str

    @model_validator(mode="after")
    def validate_prediction_source_matches_disease(self):
        expected_source = {
            "diabetes": "task13b_diabd_v3_model",
            "heart": "task13_heart_v2_model",
        }[self.disease]
        if self.prediction_source != expected_source:
            raise ValueError("Prediction source does not match disease")
        return self


class DiseaseContract(BaseModel):
    disease: Literal["diabetes", "heart"]
    available: bool
    model_version: str | None
    model_name: str | None = None
    prediction_source: str | None = None
    threshold: float | None
    features: list[dict[str, Any]]


class PredictionContractsResponse(BaseModel):
    models: dict[Literal["diabetes", "heart"], DiseaseContract]
