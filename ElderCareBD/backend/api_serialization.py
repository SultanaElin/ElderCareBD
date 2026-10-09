from datetime import timezone


def serialize_utc_timestamp(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def serialize_medicine(medicine):
    return {
        "id": medicine.id,
        "patient_id": medicine.patient_id,
        "prescription_id": medicine.prescription_id,
        "name": medicine.name,
        "strength": medicine.strength,
        "dosage": medicine.dosage,
        "frequency": medicine.frequency,
        "duration": medicine.duration,
        "instructions": medicine.instructions,
        "quantity": medicine.quantity,
        "daily_dose": medicine.daily_dose,
        "start_date": medicine.start_date,
        "run_out_date": medicine.run_out_date,
        "alert_date": medicine.alert_date,
        "note": medicine.note,
        "created_at": serialize_utc_timestamp(medicine.created_at),
    }


def serialize_prescription(prescription):
    return {
        "id": prescription.id,
        "patient_id": prescription.patient_id,
        "doctor_name": prescription.doctor_name,
        "note": prescription.note,
        "has_image": bool(prescription.image_path),
        "ocr_status": prescription.ocr_status,
        "ocr_text": prescription.ocr_text,
        "ocr_engine": prescription.ocr_engine,
        "ocr_error": prescription.ocr_error,
        "confirmed_at": serialize_utc_timestamp(prescription.confirmed_at),
        "created_at": serialize_utc_timestamp(prescription.created_at),
        "medicines": [
            serialize_medicine(medicine) for medicine in prescription.medicines
        ],
    }
