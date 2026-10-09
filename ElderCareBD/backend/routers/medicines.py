from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from api_serialization import serialize_medicine
from database import get_db
from resource_access import get_owned_patient, get_owned_prescription
from security import get_current_caregiver

router = APIRouter(prefix="/medicines", tags=["Medicines"])


@router.post("/")
def create_medicine(
    data: schemas.MedicineCreate,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    if get_owned_patient(db, caregiver.id, data.patient_id) is None:
        raise HTTPException(status_code=404, detail="Resource not found.")

    if data.prescription_id is not None:
        prescription = get_owned_prescription(
            db,
            caregiver.id,
            data.prescription_id,
        )
        if prescription is None or prescription.patient_id != data.patient_id:
            raise HTTPException(status_code=404, detail="Resource not found.")
        if prescription.confirmed_at is not None:
            raise HTTPException(
                status_code=409,
                detail="Confirmed prescription medicines cannot be changed.",
            )

    medicine = models.Medicine(**data.model_dump())

    try:
        db.add(medicine)
        db.flush()
        medicine_id = medicine.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if data.prescription_id is not None:
            current_prescription = get_owned_prescription(
                db,
                caregiver.id,
                data.prescription_id,
            )
            if (
                current_prescription is not None
                and current_prescription.confirmed_at is not None
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Confirmed prescription medicines cannot be changed.",
                ) from exc
        raise HTTPException(
            status_code=500,
            detail="Unable to save medicine.",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to save medicine.",
        ) from exc

    return {
        "message": "Medicine record saved successfully",
        "medicine_id": medicine_id,
        "name": data.name,
    }


@router.get("/")
def get_medicines(
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    medicines = (
        db.query(models.Medicine)
        .join(models.Patient)
        .filter(models.Patient.caregiver_id == caregiver.id)
        .order_by(models.Medicine.created_at.desc(), models.Medicine.id.desc())
        .all()
    )
    return [serialize_medicine(medicine) for medicine in medicines]


@router.get("/prescription/{prescription_id}")
def get_prescription_medicines(
    prescription_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    prescription = get_owned_prescription(db, caregiver.id, prescription_id)
    if prescription is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return [serialize_medicine(medicine) for medicine in prescription.medicines]


@router.get("/patient/{patient_id}")
def get_patient_medicines(
    patient_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    if get_owned_patient(db, caregiver.id, patient_id) is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    medicines = (
        db.query(models.Medicine)
        .filter(models.Medicine.patient_id == patient_id)
        .order_by(models.Medicine.created_at.desc(), models.Medicine.id.desc())
        .all()
    )

    return [serialize_medicine(medicine) for medicine in medicines]
