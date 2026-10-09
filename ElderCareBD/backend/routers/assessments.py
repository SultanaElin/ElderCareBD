import math
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from ml_model_service import (
    ModelContractError,
    ModelInferenceError,
    ModelUnavailableError,
    PREDICTION_SOURCES,
    get_ml_model_service,
)
from security import get_current_caregiver

router = APIRouter(prefix="/assessments", tags=["Assessments"])

_MODEL_DISCLAIMER = (
    "Research screening model output; not a diagnosis or a validated personal "
    "disease probability."
)
_HEURISTIC_DISCLAIMER = (
    "Demonstration heuristic fallback; not a diagnosis or validated clinical "
    "risk estimate."
)


def _serialize_utc_timestamp(value):
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    return value.isoformat().replace("+00:00", "Z")


def _serialize_assessment(assessment):
    data = jsonable_encoder(assessment)
    data["created_at"] = _serialize_utc_timestamp(assessment.created_at)
    return data


def _get_owned_patient(db, caregiver_id, patient_id):
    return db.query(models.Patient).filter(
        models.Patient.id == patient_id,
        models.Patient.caregiver_id == caregiver_id,
    ).first()


def _fallback_prediction(disease, status):
    return {
        "disease": disease,
        "prediction_source": "heuristic_demo_v1",
        "prediction_status": status,
        "model_version": None,
        "risk_score": None,
        "threshold": None,
        "classification": None,
        "disclaimer": _HEURISTIC_DISCLAIMER,
    }


def _known_diabetes_prediction():
    return {
        "disease": "diabetes",
        "prediction_source": "known_condition",
        "prediction_status": "not_applicable_known_diabetes",
        "model_version": None,
        "risk_score": None,
        "threshold": None,
        "classification": None,
        "disclaimer": (
            "DiaBD screening was not run because diabetes is already recorded "
            "for this patient."
        ),
    }


def _completed_prediction(result, expected_disease):
    serialized = result.to_dict()
    score = serialized["risk_score"]
    threshold = serialized["threshold"]
    classification = serialized["classification"]
    expected_classification = (
        "at_or_above_model_threshold"
        if score >= threshold
        else "below_model_threshold"
    )
    if (
        serialized["disease"] != expected_disease
        or serialized["prediction_source"] != PREDICTION_SOURCES[expected_disease]
        or not isinstance(serialized["model_version"], str)
        or not serialized["model_version"].strip()
        or isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 0 <= score <= 1
        or isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
        or classification != expected_classification
    ):
        raise ModelInferenceError("The model returned an invalid result.")
    return {
        "disease": serialized["disease"],
        "prediction_source": serialized["prediction_source"],
        "prediction_status": "predicted",
        "model_version": serialized["model_version"],
        "risk_score": score,
        "threshold": threshold,
        "classification": classification,
        "disclaimer": serialized.get("disclaimer", _MODEL_DISCLAIMER),
    }


def _prediction_failure_status(error):
    if isinstance(error, ModelContractError):
        return "unsupported_model_input"
    if isinstance(error, ModelUnavailableError):
        return "model_unavailable"
    return "inference_failed"


def _status_without_model_input(model_service, disease):
    try:
        model_contract = model_service.contracts()["models"][disease]
    except Exception:
        return "model_unavailable"
    return (
        "skipped_missing_model_input"
        if model_contract.get("available") is True
        else "model_unavailable"
    )


def _apply_diabetes_prediction(assessment, model_input, model_service, patient):
    assessment.diabetes_prediction_source = "heuristic_demo_v1"
    if patient.has_diabetes:
        assessment.diabetes_prediction_source = "known_condition"
        assessment.diabetes_prediction_status = "not_applicable_known_diabetes"
        return _known_diabetes_prediction()

    if model_input is None:
        assessment.diabetes_prediction_status = _status_without_model_input(
            model_service,
            "diabetes",
        )
        return _fallback_prediction(
            "diabetes",
            assessment.diabetes_prediction_status,
        )

    if (
        patient.gender not in {"Female", "Male"}
        or model_input.gender != patient.gender
    ):
        assessment.diabetes_prediction_status = "unsupported_model_input"
        return _fallback_prediction(
            "diabetes",
            assessment.diabetes_prediction_status,
        )

    assessment.diabetes_gender = model_input.gender
    assessment.diabetes_random_glucose_mmol_l = (
        model_input.random_glucose_mmol_l
    )
    if model_service is None:
        assessment.diabetes_prediction_status = "model_unavailable"
        return _fallback_prediction(
            "diabetes",
            assessment.diabetes_prediction_status,
        )
    try:
        result = model_service.predict_diabetes(
            age=model_input.age,
            gender=model_input.gender,
            systolic_bp=model_input.systolic_bp,
            diastolic_bp=model_input.diastolic_bp,
            random_glucose_mmol_l=model_input.random_glucose_mmol_l,
            bmi=model_input.bmi,
        )
        completed = _completed_prediction(result, "diabetes")
    except (ModelContractError, ModelUnavailableError, ModelInferenceError) as error:
        assessment.diabetes_prediction_status = _prediction_failure_status(error)
        return _fallback_prediction(
            "diabetes",
            assessment.diabetes_prediction_status,
        )
    except Exception:
        assessment.diabetes_prediction_status = "inference_failed"
        return _fallback_prediction(
            "diabetes",
            assessment.diabetes_prediction_status,
        )

    assessment.diabetes_prediction_source = completed["prediction_source"]
    assessment.diabetes_prediction_status = completed["prediction_status"]
    assessment.diabetes_model_version = completed["model_version"]
    assessment.diabetes_model_score = completed["risk_score"]
    assessment.diabetes_model_threshold = completed["threshold"]
    assessment.diabetes_model_classification = completed["classification"]
    return completed


def _apply_heart_prediction(assessment, model_input, model_service):
    assessment.heart_prediction_source = "heuristic_demo_v1"
    if model_input is None:
        assessment.heart_prediction_status = _status_without_model_input(
            model_service,
            "heart",
        )
        return _fallback_prediction(
            "heart",
            assessment.heart_prediction_status,
        )

    assessment.heart_clinical_sex = model_input.clinical_sex
    assessment.heart_chest_pain_type = model_input.chest_pain_type
    assessment.heart_resting_systolic_bp = (
        model_input.resting_systolic_bp_mm_hg
    )
    if model_service is None:
        assessment.heart_prediction_status = "model_unavailable"
        return _fallback_prediction(
            "heart",
            assessment.heart_prediction_status,
        )
    try:
        result = model_service.predict_heart(
            age=model_input.age,
            clinical_sex=model_input.clinical_sex,
            chest_pain_type=model_input.chest_pain_type,
            resting_systolic_bp_mm_hg=(
                model_input.resting_systolic_bp_mm_hg
            ),
        )
        completed = _completed_prediction(result, "heart")
    except (ModelContractError, ModelUnavailableError, ModelInferenceError) as error:
        assessment.heart_prediction_status = _prediction_failure_status(error)
        return _fallback_prediction(
            "heart",
            assessment.heart_prediction_status,
        )
    except Exception:
        assessment.heart_prediction_status = "inference_failed"
        return _fallback_prediction(
            "heart",
            assessment.heart_prediction_status,
        )

    assessment.heart_prediction_source = completed["prediction_source"]
    assessment.heart_prediction_status = completed["prediction_status"]
    assessment.heart_model_version = completed["model_version"]
    assessment.heart_model_score = completed["risk_score"]
    assessment.heart_model_threshold = completed["threshold"]
    assessment.heart_model_classification = completed["classification"]
    return completed


@router.post("/")
def create_assessment(
    data: schemas.AssessmentCreate,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    patient = _get_owned_patient(db, caregiver.id, data.patient_id)
    if patient is None:
        raise HTTPException(
            status_code=404,
            detail="Resource not found.",
        )

    record_data = data.model_dump(
        exclude={"diabetes_model_input", "heart_model_input"}
    )
    assessment = models.Assessment(**record_data)

    try:
        model_service = get_ml_model_service()
    except Exception:
        model_service = None

    diabetes_prediction = _apply_diabetes_prediction(
        assessment,
        data.diabetes_model_input,
        model_service,
        patient,
    )
    heart_prediction = _apply_heart_prediction(
        assessment,
        data.heart_model_input,
        model_service,
    )

    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    return {
        "message": "Assessment saved successfully",
        "assessment_id": assessment.id,
        "overall_risk": assessment.overall_risk,
        "predictions": {
            "diabetes": diabetes_prediction,
            "heart": heart_prediction,
        },
    }


@router.get("/")
def get_assessments(
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    assessments = (
        db.query(models.Assessment)
        .join(models.Patient)
        .filter(models.Patient.caregiver_id == caregiver.id)
        .order_by(models.Assessment.created_at.desc())
        .all()
    )
    return [_serialize_assessment(assessment) for assessment in assessments]


@router.get("/patient/{patient_id}")
def get_patient_assessments(
    patient_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    if _get_owned_patient(db, caregiver.id, patient_id) is None:
        raise HTTPException(status_code=404, detail="Resource not found.")

    assessments = db.query(models.Assessment).filter(
        models.Assessment.patient_id == patient_id
    ).order_by(models.Assessment.created_at.desc()).all()

    return [_serialize_assessment(assessment) for assessment in assessments]
