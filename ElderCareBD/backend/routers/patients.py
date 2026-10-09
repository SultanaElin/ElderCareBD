from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from security import get_current_caregiver

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.post("/")
def create_patient(
    patient: schemas.PatientCreate,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    if patient.caregiver_id != caregiver.id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to access this resource.",
        )

    patient_data = patient.model_dump()
    patient_data["caregiver_id"] = caregiver.id
    new_patient = models.Patient(**patient_data)

    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)

    return {
        "message": "Patient created successfully",
        "patient_id": new_patient.id,
        "name": new_patient.name,
        "caregiver_id": new_patient.caregiver_id,
    }


@router.get("/")
def get_patients(
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    return db.query(models.Patient).filter(
        models.Patient.caregiver_id == caregiver.id
    ).all()


@router.get("/caregiver/{caregiver_id}")
def get_patients_by_caregiver(
    caregiver_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    if caregiver_id != caregiver.id:
        raise HTTPException(status_code=404, detail="Resource not found.")

    return db.query(models.Patient).filter(
        models.Patient.caregiver_id == caregiver.id
    ).all()


@router.get("/{patient_id}")
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    patient = db.query(models.Patient).filter(
        models.Patient.id == patient_id,
        models.Patient.caregiver_id == caregiver.id,
    ).first()

    if patient is None:
        raise HTTPException(status_code=404, detail="Resource not found.")

    return patient
