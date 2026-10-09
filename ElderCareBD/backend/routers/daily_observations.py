from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from resource_access import get_owned_patient
from security import get_current_caregiver


router = APIRouter(
    prefix="/patients/{patient_id}/observations",
    tags=["Daily observations"],
)


def _require_owned_patient(db, caregiver_id, patient_id):
    patient = get_owned_patient(db, caregiver_id, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return patient


def _get_owned_observation(db, caregiver_id, patient_id, observation_id):
    _require_owned_patient(db, caregiver_id, patient_id)
    observation = db.query(models.PatientDailyObservation).filter(
        models.PatientDailyObservation.id == observation_id,
        models.PatientDailyObservation.patient_id == patient_id,
    ).first()
    if observation is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return observation


@router.get("", response_model=list[schemas.DailyObservationResponse])
def list_patient_observations(
    patient_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    _require_owned_patient(db, caregiver.id, patient_id)
    return db.query(models.PatientDailyObservation).filter(
        models.PatientDailyObservation.patient_id == patient_id
    ).order_by(
        models.PatientDailyObservation.observation_date.desc(),
        models.PatientDailyObservation.id.desc(),
    ).all()


@router.get("/today", response_model=schemas.DailyObservationResponse)
def get_todays_observation(
    patient_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    _require_owned_patient(db, caregiver.id, patient_id)
    observation = db.query(models.PatientDailyObservation).filter(
        models.PatientDailyObservation.patient_id == patient_id,
        models.PatientDailyObservation.observation_date == datetime.utcnow().date(),
    ).first()
    if observation is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return observation


@router.post(
    "/today",
    response_model=schemas.DailyObservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_todays_observation(
    patient_id: int,
    payload: schemas.DailyObservationCreate,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    _require_owned_patient(db, caregiver.id, patient_id)
    now = datetime.utcnow()
    today = now.date()
    existing = db.query(models.PatientDailyObservation.id).filter(
        models.PatientDailyObservation.patient_id == patient_id,
        models.PatientDailyObservation.observation_date == today,
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="An observation already exists for this patient today.",
        )

    observation = models.PatientDailyObservation(
        patient_id=patient_id,
        observation_date=today,
        recorded_at=now,
        created_at=now,
        updated_at=now,
        **payload.model_dump(),
    )
    db.add(observation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An observation already exists for this patient today.",
        )
    db.refresh(observation)
    return observation


@router.patch(
    "/{observation_id}",
    response_model=schemas.DailyObservationResponse,
)
def update_observation(
    patient_id: int,
    observation_id: int,
    payload: schemas.DailyObservationUpdate,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    observation = _get_owned_observation(
        db,
        caregiver.id,
        patient_id,
        observation_id,
    )
    changes = payload.model_dump(exclude_unset=True)
    candidate = {
        field_name: changes.get(field_name, getattr(observation, field_name))
        for field_name in schemas.DailyObservationValues.model_fields
    }
    validated = schemas.DailyObservationValues(**candidate)
    for field_name in changes:
        setattr(observation, field_name, getattr(validated, field_name))
    observation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(observation)
    return observation
