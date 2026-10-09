import models


def get_owned_patient(db, caregiver_id, patient_id):
    return db.query(models.Patient).filter(
        models.Patient.id == patient_id,
        models.Patient.caregiver_id == caregiver_id,
    ).first()


def get_owned_prescription(db, caregiver_id, prescription_id):
    return (
        db.query(models.Prescription)
        .join(models.Patient)
        .filter(
            models.Prescription.id == prescription_id,
            models.Patient.caregiver_id == caregiver_id,
        )
        .first()
    )
