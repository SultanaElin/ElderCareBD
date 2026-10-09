import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from routers.assessments import create_assessment
from routers.patients import create_patient
from schemas import AssessmentCreate, CaregiverCreate, PatientCreate


class ValidationApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = sessionmaker(bind=self.engine)()

        caregiver = models.Caregiver(
            name="Validation Caregiver",
            phone_or_email="validation@example.invalid",
            password="test-password",
        )
        self.session.add(caregiver)
        self.session.commit()
        self.session.refresh(caregiver)
        self.caregiver = caregiver
        self.caregiver_id = caregiver.id

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _patient_payload(self, **overrides):
        payload = {
            "caregiver_id": self.caregiver_id,
            "name": "Validation Patient",
            "age": 72,
            "gender": "Other",
        }
        payload.update(overrides)
        return payload

    def _create_patient(self):
        response = create_patient(
            PatientCreate(**self._patient_payload()),
            self.session,
            self.caregiver,
        )
        return response["patient_id"]

    def _assessment_payload(self, patient_id, **overrides):
        payload = {
            "patient_id": patient_id,
            "age": 72,
            "glucose": 165,
            "systolic_bp": 145,
            "diastolic_bp": 90,
            "bmi": 25.0,
            "height_cm": 160.0,
            "weight_kg": 64.0,
            "note": "Validation test note",
            "diabetes_risk": "High",
            "heart_risk": "High",
            "overall_risk": "High",
            "recommendation": "Test recommendation",
        }
        payload.update(overrides)
        return payload

    def test_blank_authentication_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            CaregiverCreate(
                name="   ",
                phone_or_email="   ",
                password="   ",
            )

    def test_invalid_patient_age_is_rejected(self):
        for age in (0, -1, 121, "not-a-number"):
            with self.subTest(age=age), self.assertRaises(ValidationError):
                PatientCreate(**self._patient_payload(age=age))

    def test_blank_patient_name_and_invalid_gender_are_rejected(self):
        with self.assertRaises(ValidationError):
            PatientCreate(**self._patient_payload(name="   "))

        with self.assertRaises(ValidationError):
            PatientCreate(**self._patient_payload(gender="Unknown"))

    def test_patient_rejects_a_mismatched_authenticated_caregiver(self):
        patient = PatientCreate(**self._patient_payload(caregiver_id=99999))

        with self.assertRaises(HTTPException) as context:
            create_patient(patient, self.session, self.caregiver)

        self.assertEqual(context.exception.status_code, 403)
        self.assertEqual(
            context.exception.detail,
            "Not authorized to access this resource.",
        )

    def test_valid_patient_age_boundaries_are_accepted(self):
        minimum = create_patient(
            PatientCreate(**self._patient_payload(name="Minimum Age", age=1)),
            self.session,
            self.caregiver,
        )
        maximum = create_patient(
            PatientCreate(**self._patient_payload(name="Maximum Age", age=120)),
            self.session,
            self.caregiver,
        )

        self.assertIsInstance(minimum["patient_id"], int)
        self.assertIsInstance(maximum["patient_id"], int)

    def test_invalid_assessment_age_is_rejected(self):
        patient_id = self._create_patient()

        for age in (0, -1, 121, "not-a-number"):
            with self.subTest(age=age), self.assertRaises(ValidationError):
                AssessmentCreate(**self._assessment_payload(patient_id, age=age))

    def test_invalid_measurements_are_rejected(self):
        patient_id = self._create_patient()
        invalid_values = {
            "glucose": -1,
            "systolic_bp": -1,
            "diastolic_bp": -1,
            "bmi": 0,
            "height_cm": 0,
            "weight_kg": -1,
        }

        for field, value in invalid_values.items():
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(ValidationError),
            ):
                AssessmentCreate(
                    **self._assessment_payload(patient_id, **{field: value})
                )

    def test_impossible_blood_pressure_relationship_is_rejected(self):
        patient_id = self._create_patient()

        for diastolic_bp in (120, 130):
            with (
                self.subTest(diastolic_bp=diastolic_bp),
                self.assertRaises(ValidationError),
            ):
                AssessmentCreate(
                    **self._assessment_payload(
                        patient_id,
                        systolic_bp=120,
                        diastolic_bp=diastolic_bp,
                    )
                )

    def test_assessment_requires_an_existing_patient(self):
        assessment = AssessmentCreate(**self._assessment_payload(99999))

        with self.assertRaises(HTTPException) as context:
            create_assessment(assessment, self.session, self.caregiver)

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(
            context.exception.detail,
            "Resource not found.",
        )

    def test_existing_style_assessment_remains_accepted(self):
        patient_id = self._create_patient()
        payload = self._assessment_payload(patient_id)
        payload.pop("height_cm")
        payload.pop("weight_kg")
        payload.pop("note")

        response = create_assessment(
            AssessmentCreate(**payload),
            self.session,
            self.caregiver,
        )

        self.assertEqual(response["overall_risk"], "High")
        self.assertIsInstance(response["assessment_id"], int)

    def test_valid_assessment_boundaries_are_accepted(self):
        patient_id = self._create_patient()
        assessment = AssessmentCreate(
            **self._assessment_payload(
                patient_id,
                age=120,
                glucose=1000,
                systolic_bp=300,
                diastolic_bp=200,
                bmi=150,
                height_cm=300,
                weight_kg=500,
            )
        )

        response = create_assessment(assessment, self.session, self.caregiver)

        self.assertIsInstance(response["assessment_id"], int)


if __name__ == "__main__":
    unittest.main()
