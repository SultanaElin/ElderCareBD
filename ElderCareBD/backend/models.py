from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DDL,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import relationship

from database import Base
from prescription_integrity import MEDICINE_PRESCRIPTION_TRIGGER_SQL


class Caregiver(Base):
    __tablename__ = "caregivers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone_or_email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    identity_normalized = Column(String(320), unique=True, index=True, nullable=True)
    verification_status = Column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    verified_at = Column(DateTime, nullable=True)
    primary_verification_channel = Column(String(5), nullable=True)

    patients = relationship(
        "Patient",
        back_populates="caregiver",
        passive_deletes=True,
    )
    sessions = relationship(
        "CaregiverSession",
        back_populates="caregiver",
        cascade="all, delete-orphan",
    )
    verifications = relationship(
        "CaregiverVerification",
        back_populates="caregiver",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CaregiverSession(Base):
    __tablename__ = "caregiver_sessions"

    id = Column(Integer, primary_key=True, index=True)
    caregiver_id = Column(Integer, ForeignKey("caregivers.id"), nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)

    caregiver = relationship("Caregiver", back_populates="sessions")


class CaregiverVerification(Base):
    __tablename__ = "caregiver_verifications"
    __table_args__ = (
        Index(
            "ix_caregiver_verifications_active_lookup",
            "caregiver_id",
            "channel",
            "consumed_at",
            "invalidated_at",
            "created_at",
        ),
        Index(
            "ux_caregiver_verifications_active_caregiver",
            "caregiver_id",
            unique=True,
            sqlite_where=text(
                "consumed_at IS NULL AND invalidated_at IS NULL"
            ),
        ),
    )

    id = Column(Integer, primary_key=True)
    caregiver_id = Column(
        Integer,
        ForeignKey("caregivers.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel = Column(String(5), nullable=False)
    destination_normalized = Column(String(320), nullable=False)
    otp_digest = Column(String(64), nullable=False)
    otp_salt = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    resend_available_at = Column(DateTime, nullable=False)
    resend_window_started_at = Column(DateTime, nullable=False)
    failed_attempts = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    max_attempts = Column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
    )
    resend_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    delivery_status = Column(
        String(16),
        nullable=False,
        default="sent",
        server_default="sent",
    )
    consumed_at = Column(DateTime, nullable=True)
    invalidated_at = Column(DateTime, nullable=True)

    caregiver = relationship("Caregiver", back_populates="verifications")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)

    caregiver_id = Column(
        Integer,
        ForeignKey(
            "caregivers.id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    emergency_contact = Column(String, nullable=True)

    has_diabetes = Column(Boolean, default=False)
    has_heart_disease = Column(Boolean, default=False)
    has_hypertension = Column(Boolean, default=False)
    has_kidney_disease = Column(Boolean, default=False)
    has_stroke_history = Column(Boolean, default=False)

    disease_history = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    caregiver = relationship("Caregiver", back_populates="patients")
    assessments = relationship("Assessment", back_populates="patient")
    prescriptions = relationship(
        "Prescription",
        back_populates="patient",
        passive_deletes=True,
    )
    medicines = relationship(
        "Medicine",
        back_populates="patient",
        passive_deletes=True,
    )
    daily_observations = relationship(
        "PatientDailyObservation",
        back_populates="patient",
        passive_deletes=True,
    )


class PatientDailyObservation(Base):
    __tablename__ = "patient_daily_observations"
    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "observation_date",
            name="ux_patient_daily_observations_patient_date",
        ),
        Index(
            "ix_patient_daily_observations_patient_date",
            "patient_id",
            "observation_date",
        ),
    )

    id = Column(Integer, primary_key=True)
    patient_id = Column(
        Integer,
        ForeignKey(
            "patients.id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    observation_date = Column(Date, nullable=False)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    systolic_bp = Column(Float, nullable=True)
    diastolic_bp = Column(Float, nullable=True)
    glucose_value = Column(Float, nullable=True)
    glucose_unit = Column(String(16), nullable=True)
    glucose_context = Column(String(50), nullable=True)
    pulse_bpm = Column(Float, nullable=True)
    spo2_percent = Column(Float, nullable=True)
    temperature_value = Column(Float, nullable=True)
    temperature_unit = Column(String(1), nullable=True)
    weight_kg = Column(Float, nullable=True)
    symptoms = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    patient = relationship("Patient", back_populates="daily_observations")


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)

    age = Column(Integer, nullable=False)
    glucose = Column(Integer, nullable=False)
    systolic_bp = Column(Integer, nullable=False)
    diastolic_bp = Column(Integer, nullable=False)
    bmi = Column(Float, nullable=False)
    height_cm = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)
    note = Column(String, nullable=True)

    chest_pain = Column(Boolean, default=False)
    dizziness = Column(Boolean, default=False)
    shortness_of_breath = Column(Boolean, default=False)
    excessive_thirst = Column(Boolean, default=False)
    fatigue = Column(Boolean, default=False)
    blurred_vision = Column(Boolean, default=False)

    diabetes_risk = Column(String, nullable=True)
    heart_risk = Column(String, nullable=True)
    overall_risk = Column(String, nullable=True)
    recommendation = Column(String, nullable=True)

    # Task 14 model provenance. These columns intentionally remain nullable so
    # assessments created before the validated models were integrated continue
    # to deserialize without a fabricated source or result.
    diabetes_prediction_source = Column(String, nullable=True)
    diabetes_prediction_status = Column(String, nullable=True)
    diabetes_model_version = Column(String, nullable=True)
    diabetes_model_score = Column(Float, nullable=True)
    diabetes_model_threshold = Column(Float, nullable=True)
    diabetes_model_classification = Column(String, nullable=True)
    diabetes_gender = Column(String, nullable=True)
    diabetes_random_glucose_mmol_l = Column(Float, nullable=True)
    # Legacy Task 14/Pima provenance. DiaBD v3 never populates this column.
    diabetes_ogtt_glucose = Column(Float, nullable=True)

    heart_prediction_source = Column(String, nullable=True)
    heart_prediction_status = Column(String, nullable=True)
    heart_model_version = Column(String, nullable=True)
    heart_model_score = Column(Float, nullable=True)
    heart_model_threshold = Column(Float, nullable=True)
    heart_model_classification = Column(String, nullable=True)
    heart_clinical_sex = Column(String, nullable=True)
    heart_chest_pain_type = Column(String, nullable=True)
    heart_resting_systolic_bp = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="assessments")


class Prescription(Base):
    __tablename__ = "prescriptions"
    __table_args__ = (Index("idx_prescriptions_patient_id", "patient_id"),)

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(
        Integer,
        ForeignKey(
            "patients.id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )

    doctor_name = Column(String, nullable=True)
    note = Column(String, nullable=True)
    image_path = Column(String, nullable=True)
    image_original_name = Column(String, nullable=True)
    image_mime_type = Column(String, nullable=True)
    image_size_bytes = Column(Integer, nullable=True)
    image_sha256 = Column(String(64), nullable=True)

    ocr_text = Column(Text, nullable=True)
    ocr_status = Column(String, nullable=True)
    ocr_engine = Column(String, nullable=True)
    ocr_error = Column(Text, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    confirmation_hash = Column(String(64), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="prescriptions")
    medicines = relationship(
        "Medicine",
        back_populates="prescription",
        passive_deletes=True,
        order_by="Medicine.id",
    )


class Medicine(Base):
    __tablename__ = "medicines"
    __table_args__ = (
        Index("idx_medicines_patient_id", "patient_id"),
        Index("idx_medicines_prescription_id", "prescription_id"),
    )

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(
        Integer,
        ForeignKey(
            "patients.id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    prescription_id = Column(
        Integer,
        ForeignKey(
            "prescriptions.id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    name = Column(String, nullable=False)
    strength = Column(String, nullable=True)
    dosage = Column(String, nullable=True)
    frequency = Column(String, nullable=True)
    duration = Column(String, nullable=True)
    instructions = Column(Text, nullable=True)

    quantity = Column(Integer, nullable=True)
    daily_dose = Column(Integer, nullable=True)

    start_date = Column(String, nullable=True)
    run_out_date = Column(String, nullable=True)
    alert_date = Column(String, nullable=True)

    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="medicines")
    prescription = relationship("Prescription", back_populates="medicines")


for _trigger_sql in MEDICINE_PRESCRIPTION_TRIGGER_SQL.values():
    event.listen(
        Medicine.__table__,
        "after_create",
        DDL(_trigger_sql).execute_if(dialect="sqlite"),
    )
