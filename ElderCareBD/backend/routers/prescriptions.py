import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from api_serialization import serialize_medicine, serialize_prescription
from database import get_db
from image_storage import (
    ImageValidationError,
    delete_private_image,
    resolve_image_path,
    validate_and_store_upload,
    validate_existing_image,
)
from ocr_engine import (
    MAX_OCR_TEXT_CHARACTERS,
    PrescriptionOcrEngine,
    PrescriptionOcrError,
    PrescriptionOcrResult,
    get_prescription_ocr_engine,
)
from prescription_parser import MAX_MEDICINE_CANDIDATES, PrescriptionMedicineParser
from resource_access import get_owned_patient, get_owned_prescription
from security import get_current_caregiver


router = APIRouter(prefix="/prescriptions", tags=["Prescriptions"])
medicine_parser = PrescriptionMedicineParser()


def _not_found():
    return HTTPException(status_code=404, detail="Resource not found.")


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _confirmation_hash(data):
    canonical_payload = [
        medicine.model_dump(mode="json", exclude_none=False)
        for medicine in data.medicines
    ]
    encoded = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _confirmation_response(prescription, already_confirmed):
    serialized = serialize_prescription(prescription)
    return {
        "message": "Prescription medicines confirmed successfully",
        "prescription_id": prescription.id,
        "patient_id": prescription.patient_id,
        "confirmed_at": serialized["confirmed_at"],
        "already_confirmed": already_confirmed,
        "medicines": serialized["medicines"],
    }


def _ocr_descriptor(engine_name, languages):
    language_suffix = "+".join(languages)
    return f"{engine_name}:{language_suffix}" if language_suffix else engine_name


def _split_ocr_descriptor(descriptor):
    if not descriptor:
        return None, []
    engine_name, separator, language_suffix = descriptor.partition(":")
    languages = language_suffix.split("+") if separator and language_suffix else []
    return engine_name, languages


def _ready_extraction_response(
    prescription_id,
    ocr_text,
    engine_name,
    languages,
    reused,
):
    candidates = medicine_parser.parse(ocr_text)
    warnings = [medicine_parser.review_warning]
    if not (ocr_text or "").strip():
        warnings.append(
            "OCR did not recognize readable text. Enter medicines manually."
        )
    elif not candidates:
        warnings.append(
            "No medicine candidates were recognized. Review the OCR text or "
            "enter medicines manually."
        )
    elif len(candidates) >= MAX_MEDICINE_CANDIDATES:
        warnings.append(
            f"Candidate output is limited to {MAX_MEDICINE_CANDIDATES} rows. "
            "Review the complete OCR text for additional medicines."
        )
    if any("\u0980" <= character <= "\u09ff" for character in (ocr_text or "")):
        warnings.append(
            "Bengali OCR text was retained, but automatic medicine parsing is "
            "currently limited to conservative English patterns."
        )
    return {
        "prescription_id": prescription_id,
        "ocr_status": "ready",
        "ocr_engine": engine_name,
        "ocr_languages": list(languages),
        "ocr_text": ocr_text,
        "candidates": candidates,
        "warnings": warnings,
        "reused": reused,
    }


def _failed_extraction_response(
    prescription_id,
    engine_name,
    languages,
    ocr_text,
    warning,
):
    return {
        "prescription_id": prescription_id,
        "ocr_status": "failed",
        "ocr_engine": engine_name,
        "ocr_languages": list(languages),
        "ocr_text": ocr_text,
        "candidates": [],
        "warnings": [warning, "The prescription image was preserved."],
        "reused": False,
    }


@router.post("/")
async def create_prescription(
    patient_id: int = Form(..., gt=0),
    doctor_name: Optional[str] = Form(None, max_length=200),
    note: Optional[str] = Form(None, max_length=2000),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    if get_owned_patient(db, caregiver.id, patient_id) is None:
        raise _not_found()

    stored_image = None
    if image is not None:
        try:
            stored_image = await validate_and_store_upload(image)
        except ImageValidationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail,
            ) from exc

    prescription = models.Prescription(
        patient_id=patient_id,
        doctor_name=doctor_name.strip() if doctor_name else None,
        note=note.strip() if note else None,
        image_path=stored_image.storage_key if stored_image else None,
        image_original_name=(stored_image.original_name if stored_image else None),
        image_mime_type=stored_image.mime_type if stored_image else None,
        image_size_bytes=stored_image.size_bytes if stored_image else None,
        image_sha256=stored_image.sha256 if stored_image else None,
        ocr_status="uploaded" if stored_image else None,
    )

    try:
        db.add(prescription)
        db.flush()
        prescription_id = prescription.id
        db.commit()
    except Exception as exc:
        db.rollback()
        if stored_image is not None:
            delete_private_image(stored_image.storage_key)
        raise HTTPException(
            status_code=500,
            detail="Unable to save prescription.",
        ) from exc

    return {
        "message": "Prescription saved successfully",
        "prescription_id": prescription_id,
        "patient_id": patient_id,
        "has_image": stored_image is not None,
        "ocr_status": "uploaded" if stored_image else None,
    }


@router.get("/")
def get_prescriptions(
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    prescriptions = (
        db.query(models.Prescription)
        .join(models.Patient)
        .filter(models.Patient.caregiver_id == caregiver.id)
        .order_by(models.Prescription.created_at.desc(), models.Prescription.id.desc())
        .all()
    )
    return [serialize_prescription(prescription) for prescription in prescriptions]


@router.get("/patient/{patient_id}")
def get_patient_prescriptions(
    patient_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    if get_owned_patient(db, caregiver.id, patient_id) is None:
        raise _not_found()
    prescriptions = (
        db.query(models.Prescription)
        .filter(models.Prescription.patient_id == patient_id)
        .order_by(models.Prescription.created_at.desc(), models.Prescription.id.desc())
        .all()
    )
    return [serialize_prescription(prescription) for prescription in prescriptions]


@router.get("/{prescription_id}/image")
def get_prescription_image(
    prescription_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    prescription = get_owned_prescription(db, caregiver.id, prescription_id)
    if prescription is None:
        raise _not_found()

    image_path = resolve_image_path(prescription.image_path)
    if image_path is None or not image_path.is_file():
        raise _not_found()
    media_type = validate_existing_image(image_path)
    if media_type is None:
        raise _not_found()

    return FileResponse(
        image_path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{prescription_id}/extract",
    response_model=schemas.PrescriptionExtractionResponse,
)
def extract_prescription_medicines(
    prescription_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
    ocr_engine: PrescriptionOcrEngine = Depends(get_prescription_ocr_engine),
):
    prescription = get_owned_prescription(db, caregiver.id, prescription_id)
    if prescription is None:
        raise _not_found()

    image_path = resolve_image_path(prescription.image_path)
    if (
        image_path is None
        or not image_path.is_file()
        or validate_existing_image(image_path) is None
    ):
        raise HTTPException(
            status_code=409,
            detail="Prescription does not have a valid stored image.",
        )

    if prescription.confirmed_at is not None or prescription.ocr_status == "confirmed":
        raise HTTPException(
            status_code=409,
            detail="Confirmed prescriptions cannot be extracted again.",
        )
    if prescription.ocr_status == "ready" and prescription.ocr_text is not None:
        engine_name, languages = _split_ocr_descriptor(prescription.ocr_engine)
        return _ready_extraction_response(
            prescription.id,
            prescription.ocr_text,
            engine_name,
            languages,
            reused=True,
        )
    if prescription.ocr_status == "processing":
        raise HTTPException(
            status_code=409,
            detail="Prescription extraction is already in progress.",
        )
    if prescription.ocr_status not in (None, "uploaded", "failed", "ready"):
        raise HTTPException(
            status_code=409,
            detail="Prescription is not available for extraction.",
        )

    try:
        claimed = (
            db.query(models.Prescription)
            .filter(
                models.Prescription.id == prescription_id,
                models.Prescription.confirmed_at.is_(None),
                models.Prescription.confirmation_hash.is_(None),
                or_(
                    models.Prescription.ocr_status.is_(None),
                    models.Prescription.ocr_status.in_(("uploaded", "failed")),
                ),
            )
            .update(
                {
                    models.Prescription.ocr_status: "processing",
                    models.Prescription.ocr_error: None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to start prescription extraction.",
        ) from exc

    if claimed != 1:
        prescription = get_owned_prescription(db, caregiver.id, prescription_id)
        if prescription is None:
            raise _not_found()
        if prescription.confirmed_at is not None:
            raise HTTPException(
                status_code=409,
                detail="Confirmed prescriptions cannot be extracted again.",
            )
        if prescription.ocr_status == "ready" and prescription.ocr_text is not None:
            engine_name, languages = _split_ocr_descriptor(prescription.ocr_engine)
            return _ready_extraction_response(
                prescription.id,
                prescription.ocr_text,
                engine_name,
                languages,
                reused=True,
            )
        raise HTTPException(
            status_code=409,
            detail="Prescription extraction is already in progress.",
        )

    engine_name = ocr_engine.name
    languages = tuple(ocr_engine.languages)
    engine_descriptor = _ocr_descriptor(engine_name, languages)
    try:
        result = ocr_engine.extract_text(image_path)
        if (
            not isinstance(result, PrescriptionOcrResult)
            or not isinstance(result.text, str)
            or len(result.text) > MAX_OCR_TEXT_CHARACTERS
        ):
            raise PrescriptionOcrError()
    except Exception as exc:
        failure = exc if isinstance(exc, PrescriptionOcrError) else PrescriptionOcrError()
        try:
            failed = (
                db.query(models.Prescription)
                .filter(
                    models.Prescription.id == prescription_id,
                    models.Prescription.confirmed_at.is_(None),
                    models.Prescription.confirmation_hash.is_(None),
                    models.Prescription.ocr_status == "processing",
                )
                .update(
                    {
                        models.Prescription.ocr_status: "failed",
                        models.Prescription.ocr_engine: engine_descriptor,
                        models.Prescription.ocr_error: failure.user_message,
                    },
                    synchronize_session=False,
                )
            )
            if failed != 1:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Prescription state changed during extraction.",
                )
            db.commit()
        except HTTPException:
            raise
        except Exception as database_error:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Unable to save prescription extraction status.",
            ) from database_error
        prescription = get_owned_prescription(db, caregiver.id, prescription_id)
        return _failed_extraction_response(
            prescription_id,
            engine_name,
            languages,
            prescription.ocr_text,
            failure.user_message,
        )

    result_descriptor = _ocr_descriptor(result.engine, result.languages)
    try:
        completed = (
            db.query(models.Prescription)
            .filter(
                models.Prescription.id == prescription_id,
                models.Prescription.confirmed_at.is_(None),
                models.Prescription.confirmation_hash.is_(None),
                models.Prescription.ocr_status == "processing",
            )
            .update(
                {
                    models.Prescription.ocr_text: result.text,
                    models.Prescription.ocr_status: "ready",
                    models.Prescription.ocr_engine: result_descriptor,
                    models.Prescription.ocr_error: None,
                },
                synchronize_session=False,
            )
        )
        if completed != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Prescription state changed during extraction.",
            )
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to save prescription extraction.",
        ) from exc

    return _ready_extraction_response(
        prescription_id,
        result.text,
        result.engine,
        result.languages,
        reused=False,
    )


@router.post("/{prescription_id}/confirm")
def confirm_prescription(
    prescription_id: int,
    data: schemas.PrescriptionConfirm,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    caregiver_id = caregiver.id
    prescription = get_owned_prescription(db, caregiver_id, prescription_id)
    if prescription is None:
        raise _not_found()

    payload_hash = _confirmation_hash(data)
    if prescription.confirmed_at is not None:
        if prescription.confirmation_hash != payload_hash:
            raise HTTPException(
                status_code=409,
                detail="Prescription was already confirmed with different medicines.",
            )
        return _confirmation_response(prescription, already_confirmed=True)

    if prescription.medicines:
        raise HTTPException(
            status_code=409,
            detail=(
                "Prescription already has manually saved medicines and cannot "
                "be atomically confirmed."
            ),
        )

    try:
        claimed = (
            db.query(models.Prescription)
            .filter(
                models.Prescription.id == prescription_id,
                models.Prescription.confirmed_at.is_(None),
                models.Prescription.confirmation_hash.is_(None),
            )
            .update(
                {
                    models.Prescription.confirmation_hash: payload_hash,
                },
                synchronize_session=False,
            )
        )
        if claimed != 1:
            db.rollback()
            prescription = get_owned_prescription(db, caregiver_id, prescription_id)
            if prescription is None:
                raise _not_found()
            if (
                prescription.confirmed_at is None
                or prescription.confirmation_hash != payload_hash
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Prescription confirmation could not be claimed.",
                )
            return _confirmation_response(prescription, already_confirmed=True)

        db.expire(prescription, ["medicines"])
        if prescription.medicines:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Prescription already has manually saved medicines and cannot "
                    "be atomically confirmed."
                ),
            )

        for reviewed_medicine in data.medicines:
            db.add(
                models.Medicine(
                    patient_id=prescription.patient_id,
                    prescription_id=prescription.id,
                    **reviewed_medicine.model_dump(),
                )
            )
        db.flush()

        finalized = (
            db.query(models.Prescription)
            .filter(
                models.Prescription.id == prescription_id,
                models.Prescription.confirmed_at.is_(None),
                models.Prescription.confirmation_hash == payload_hash,
            )
            .update(
                {
                    models.Prescription.confirmed_at: _utc_now(),
                    models.Prescription.ocr_status: "confirmed",
                },
                synchronize_session=False,
            )
        )
        if finalized != 1:
            raise HTTPException(
                status_code=409,
                detail="Prescription confirmation could not be finalized.",
            )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to confirm prescription medicines.",
        ) from exc

    prescription = get_owned_prescription(db, caregiver_id, prescription_id)
    return _confirmation_response(prescription, already_confirmed=False)


@router.get("/{prescription_id}")
def get_prescription(
    prescription_id: int,
    db: Session = Depends(get_db),
    caregiver: models.Caregiver = Depends(get_current_caregiver),
):
    prescription = get_owned_prescription(db, caregiver.id, prescription_id)
    if prescription is None:
        raise _not_found()
    return serialize_prescription(prescription)
