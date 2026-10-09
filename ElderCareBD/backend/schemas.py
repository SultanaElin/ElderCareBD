import math
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OtpCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6}$"),
]
MedicineName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
ShortMedicineText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
LongMedicineText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
ObservationContext = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
]
ObservationSymptoms = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
ObservationNotes = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class CaregiverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonBlankText
    phone_or_email: NonBlankText
    password: NonBlankText
    channel: Optional[Literal["email", "sms"]] = None


class CaregiverLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_or_email: NonBlankText
    password: NonBlankText


class CaregiverOtpVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caregiver_id: int = Field(gt=0)
    channel: Literal["email", "sms"]
    otp: OtpCode


class CaregiverOtpResend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caregiver_id: int = Field(gt=0)
    channel: Literal["email", "sms"]


class PatientCreate(BaseModel):
    caregiver_id: int = Field(gt=0)
    name: NonBlankText
    age: int = Field(ge=1, le=120)
    gender: Literal["Male", "Female", "Other"]
    phone: Optional[str] = None
    address: Optional[str] = None
    emergency_contact: Optional[str] = None
    has_diabetes: bool = False
    has_heart_disease: bool = False
    has_hypertension: bool = False
    has_kidney_disease: bool = False
    has_stroke_history: bool = False
    disease_history: Optional[str] = None


class DailyObservationValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    systolic_bp: Optional[float] = Field(
        default=None,
        strict=True,
        ge=60,
        le=260,
        allow_inf_nan=False,
    )
    diastolic_bp: Optional[float] = Field(
        default=None,
        strict=True,
        ge=30,
        le=160,
        allow_inf_nan=False,
    )
    glucose_value: Optional[float] = Field(
        default=None,
        strict=True,
        allow_inf_nan=False,
    )
    glucose_unit: Optional[Literal["mg/dL", "mmol/L"]] = None
    glucose_context: Optional[ObservationContext] = None
    pulse_bpm: Optional[float] = Field(
        default=None,
        strict=True,
        ge=30,
        le=220,
        allow_inf_nan=False,
    )
    spo2_percent: Optional[float] = Field(
        default=None,
        strict=True,
        ge=0,
        le=100,
        allow_inf_nan=False,
    )
    temperature_value: Optional[float] = Field(
        default=None,
        strict=True,
        allow_inf_nan=False,
    )
    temperature_unit: Optional[Literal["C", "F"]] = None
    weight_kg: Optional[float] = Field(
        default=None,
        strict=True,
        gt=0,
        le=500,
        allow_inf_nan=False,
    )
    symptoms: Optional[ObservationSymptoms] = None
    notes: Optional[ObservationNotes] = None

    @field_validator(
        "systolic_bp",
        "diastolic_bp",
        "glucose_value",
        "pulse_bpm",
        "spo2_percent",
        "temperature_value",
        "weight_kg",
        mode="before",
    )
    @classmethod
    def sanitize_non_finite_numeric_input(cls, value):
        # FastAPI includes the rejected input in its 422 response. Replacing a
        # non-finite float with a harmless sentinel lets strict float parsing
        # reject it without making the JSON error response itself non-finite.
        if isinstance(value, float) and not math.isfinite(value):
            return "non-finite-number"
        return value

    @model_validator(mode="after")
    def validate_observation_values(self):
        if (
            self.systolic_bp is not None
            and self.diastolic_bp is not None
            and self.diastolic_bp >= self.systolic_bp
        ):
            raise ValueError("Diastolic BP must be lower than systolic BP")

        if self.glucose_value is None:
            if self.glucose_unit is not None or self.glucose_context is not None:
                raise ValueError(
                    "Glucose unit and context require a glucose value"
                )
        elif self.glucose_unit is None:
            raise ValueError("Glucose unit is required with a glucose value")
        elif self.glucose_unit == "mg/dL" and not 20 <= self.glucose_value <= 600:
            raise ValueError("Glucose must be between 20 and 600 mg/dL")
        elif self.glucose_unit == "mmol/L" and not 1.1 <= self.glucose_value <= 33.3:
            raise ValueError("Glucose must be between 1.1 and 33.3 mmol/L")

        if self.temperature_value is None:
            if self.temperature_unit is not None:
                raise ValueError("Temperature unit requires a temperature value")
        elif self.temperature_unit is None:
            raise ValueError("Temperature unit is required with a temperature value")
        elif self.temperature_unit == "C" and not 32 <= self.temperature_value <= 43:
            raise ValueError("Temperature must be between 32 and 43 C")
        elif self.temperature_unit == "F" and not 89.6 <= self.temperature_value <= 109.4:
            raise ValueError("Temperature must be between 89.6 and 109.4 F")
        return self


class DailyObservationCreate(DailyObservationValues):
    @model_validator(mode="after")
    def require_observation_value(self):
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("At least one observation value is required")
        return self


class DailyObservationUpdate(DailyObservationValues):
    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one observation field is required")
        return self


class DailyObservationResponse(DailyObservationValues):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    observation_date: date
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime


class DiabetesAssessmentModelInput(BaseModel):
    """Exact DiaBD v3 values requested for a persisted prediction."""

    model_config = ConfigDict(extra="forbid")

    age: int = Field(strict=True, ge=21, le=80)
    gender: Literal["Female", "Male"]
    systolic_bp: int = Field(strict=True, ge=62, le=231)
    diastolic_bp: int = Field(strict=True, ge=45, le=119)
    random_glucose_mmol_l: float = Field(
        strict=True,
        ge=1.0,
        le=33.46,
        allow_inf_nan=False,
    )
    bmi: float = Field(strict=True, ge=11.47, le=54.08, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_blood_pressure_pair(self):
        if self.diastolic_bp >= self.systolic_bp:
            raise ValueError("Diastolic BP must be lower than systolic BP")
        return self


class HeartAssessmentModelInput(BaseModel):
    """Exact semantic values requested for a persisted heart prediction."""

    model_config = ConfigDict(extra="forbid")

    age: int = Field(strict=True, ge=1, le=120)
    clinical_sex: NonBlankText
    chest_pain_type: NonBlankText
    blood_pressure_context: Literal["resting_systolic"]
    resting_systolic_bp_mm_hg: int = Field(strict=True, ge=1, le=300)


class AssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: int = Field(gt=0)
    age: int = Field(ge=1, le=120)
    glucose: int = Field(ge=1, le=1000)
    systolic_bp: int = Field(ge=1, le=300)
    diastolic_bp: int = Field(ge=1, le=200)
    bmi: float = Field(ge=1, le=150, allow_inf_nan=False)
    height_cm: Optional[float] = Field(
        default=None,
        ge=30,
        le=300,
        allow_inf_nan=False,
    )
    weight_kg: Optional[float] = Field(
        default=None,
        ge=1,
        le=500,
        allow_inf_nan=False,
    )
    note: Optional[str] = None

    chest_pain: bool = False
    dizziness: bool = False
    shortness_of_breath: bool = False
    excessive_thirst: bool = False
    fatigue: bool = False
    blurred_vision: bool = False

    diabetes_risk: str
    heart_risk: str
    overall_risk: str
    recommendation: str

    diabetes_model_input: Optional[DiabetesAssessmentModelInput] = None
    heart_model_input: Optional[HeartAssessmentModelInput] = None

    @model_validator(mode="after")
    def validate_blood_pressure_relationship(self):
        if self.diastolic_bp >= self.systolic_bp:
            raise ValueError("Diastolic BP must be lower than systolic BP")

        diabetes_input = self.diabetes_model_input
        if diabetes_input is not None:
            if diabetes_input.age != self.age:
                raise ValueError(
                    "Diabetes model age must match the assessment age"
                )
            if abs(diabetes_input.bmi - self.bmi) > 1e-9:
                raise ValueError(
                    "Diabetes model BMI must match the assessment BMI"
                )
            if diabetes_input.systolic_bp != self.systolic_bp:
                raise ValueError(
                    "Diabetes model systolic BP must match the assessment "
                    "systolic BP"
                )
            if diabetes_input.diastolic_bp != self.diastolic_bp:
                raise ValueError(
                    "Diabetes model diastolic BP must match the assessment "
                    "diastolic BP"
                )

        heart_input = self.heart_model_input
        if heart_input is not None:
            if heart_input.age != self.age:
                raise ValueError("Heart model age must match the assessment age")
            if heart_input.resting_systolic_bp_mm_hg != self.systolic_bp:
                raise ValueError(
                    "Heart model resting systolic BP must match the assessment "
                    "systolic BP"
                )
        return self


class MedicineCreate(BaseModel):
    patient_id: int = Field(gt=0)
    prescription_id: Optional[int] = Field(default=None, gt=0)

    name: MedicineName
    strength: Optional[ShortMedicineText] = None
    dosage: Optional[ShortMedicineText] = None
    frequency: Optional[ShortMedicineText] = None
    duration: Optional[ShortMedicineText] = None
    instructions: Optional[LongMedicineText] = None

    quantity: Optional[int] = Field(default=None, gt=0)
    daily_dose: Optional[int] = Field(default=None, gt=0)
    start_date: Optional[str] = None
    run_out_date: Optional[str] = None
    alert_date: Optional[str] = None

    note: Optional[LongMedicineText] = None


class ReviewedMedicine(BaseModel):
    name: MedicineName
    strength: Optional[ShortMedicineText] = None
    dosage: Optional[ShortMedicineText] = None
    frequency: Optional[ShortMedicineText] = None
    duration: Optional[ShortMedicineText] = None
    instructions: Optional[LongMedicineText] = None

    quantity: Optional[int] = Field(default=None, gt=0)
    daily_dose: Optional[int] = Field(default=None, gt=0)
    start_date: Optional[str] = None
    run_out_date: Optional[str] = None
    alert_date: Optional[str] = None
    note: Optional[LongMedicineText] = None


class PrescriptionConfirm(BaseModel):
    medicines: list[ReviewedMedicine] = Field(min_length=1, max_length=100)


class ExtractedMedicineCandidate(BaseModel):
    name: MedicineName
    strength: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    source_line: str
    confidence: Literal["high", "medium", "low"]
    warnings: list[str]


class PrescriptionExtractionResponse(BaseModel):
    prescription_id: int
    ocr_status: Literal["ready", "failed"]
    ocr_engine: Optional[str]
    ocr_languages: list[str]
    ocr_text: Optional[str]
    candidates: list[ExtractedMedicineCandidate]
    warnings: list[str]
    reused: bool


class MedicineResponse(BaseModel):
    id: int
    patient_id: int
    prescription_id: Optional[int]
    name: str
    strength: Optional[str]
    dosage: Optional[str]
    frequency: Optional[str]
    duration: Optional[str]
    instructions: Optional[str]
    quantity: Optional[int]
    daily_dose: Optional[int]
    start_date: Optional[str]
    run_out_date: Optional[str]
    alert_date: Optional[str]
    note: Optional[str]
    created_at: Optional[datetime]


class PrescriptionResponse(BaseModel):
    id: int
    patient_id: int
    doctor_name: Optional[str]
    note: Optional[str]
    has_image: bool
    ocr_status: Optional[str]
    ocr_text: Optional[str]
    ocr_engine: Optional[str]
    ocr_error: Optional[str]
    confirmed_at: Optional[str]
    created_at: Optional[str]
    medicines: list[MedicineResponse]
