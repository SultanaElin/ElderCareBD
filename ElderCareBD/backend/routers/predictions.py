"""Authenticated, ownership-scoped disease-risk prediction endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db
from ml_model_service import (
    ModelContractError,
    ModelInferenceError,
    ModelUnavailableError,
    get_ml_model_service,
)
from prediction_schemas import (
    DiabetesPredictionRequest,
    HeartPredictionRequest,
    PredictionContractsResponse,
    PredictionResponse,
)
from resource_access import get_owned_patient
from security import get_current_caregiver


router = APIRouter(prefix="/predictions", tags=["Predictions"])


def _require_owned_patient(
    db: Session,
    caregiver_id: int,
    patient_id: int,
) -> models.Patient:
    patient = get_owned_patient(db, caregiver_id, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return patient


def _service_after_authorization():
    try:
        return get_ml_model_service()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Risk prediction is temporarily unavailable.",
        ) from exc


def _prediction_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ModelContractError):
        return HTTPException(
            status_code=422,
            detail="Prediction input does not match the supported model contract.",
        )
    if isinstance(exc, (ModelUnavailableError, ModelInferenceError)):
        return HTTPException(
            status_code=503,
            detail="Risk prediction is temporarily unavailable.",
        )
    return HTTPException(
        status_code=503,
        detail="Risk prediction is temporarily unavailable.",
    )


@router.get("/contracts", response_model=PredictionContractsResponse)
def get_prediction_contracts(
    _caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    service = _service_after_authorization()
    try:
        return service.contracts()
    except Exception as exc:
        raise _prediction_error(exc) from exc


@router.post("/diabetes", response_model=PredictionResponse)
def predict_diabetes(
    data: DiabetesPredictionRequest,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    patient = _require_owned_patient(db, caregiver.id, data.patient_id)
    if patient.has_diabetes:
        raise HTTPException(
            status_code=409,
            detail=(
                "Diabetes screening is not applicable because diabetes is "
                "already recorded for this patient."
            ),
        )
    if patient.gender not in {"Female", "Male"} or data.gender != patient.gender:
        raise HTTPException(
            status_code=422,
            detail=(
                "DiaBD screening requires the patient's recorded gender to be "
                "exactly Female or Male and to match the request."
            ),
        )
    service = _service_after_authorization()
    try:
        result = service.predict_diabetes(
            age=data.age,
            gender=data.gender,
            systolic_bp=data.systolic_bp,
            diastolic_bp=data.diastolic_bp,
            random_glucose_mmol_l=data.random_glucose_mmol_l,
            bmi=data.bmi,
        )
    except Exception as exc:
        raise _prediction_error(exc) from exc
    return PredictionResponse(patient_id=data.patient_id, **result.to_dict())


@router.post("/heart", response_model=PredictionResponse)
def predict_heart(
    data: HeartPredictionRequest,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    _require_owned_patient(db, caregiver.id, data.patient_id)
    service = _service_after_authorization()
    try:
        result = service.predict_heart(
            age=data.age,
            clinical_sex=data.clinical_sex,
            chest_pain_type=data.chest_pain_type,
            resting_systolic_bp_mm_hg=data.resting_systolic_bp_mm_hg,
        )
    except Exception as exc:
        raise _prediction_error(exc) from exc
    return PredictionResponse(patient_id=data.patient_id, **result.to_dict())
