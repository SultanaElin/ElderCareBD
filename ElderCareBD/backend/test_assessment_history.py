import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from routers.assessments import (
    _serialize_utc_timestamp,
    get_patient_assessments,
)


class AssessmentHistoryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.caregiver = models.Caregiver(
            name="History Caregiver",
            phone_or_email="history@example.invalid",
            password="test-password",
        )
        self.session.add(self.caregiver)
        self.session.flush()
        self.session.add(
            models.Patient(
                id=42,
                caregiver_id=self.caregiver.id,
                name="History Patient",
                age=72,
                gender="Other",
            )
        )
        self.session.commit()

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _assessment(self, assessment_id, patient_id, created_at):
        return models.Assessment(
            id=assessment_id,
            patient_id=patient_id,
            age=72,
            glucose=130,
            systolic_bp=125,
            diastolic_bp=80,
            bmi=24.5,
            chest_pain=False,
            dizziness=False,
            shortness_of_breath=False,
            excessive_thirst=False,
            fatigue=False,
            blurred_vision=False,
            diabetes_risk="Low",
            heart_risk="Low",
            overall_risk="Low",
            recommendation="Continue regular monitoring.",
            created_at=created_at,
        )

    def test_patient_history_is_ordered_by_timestamp_newest_first(self):
        older = self._assessment(
            assessment_id=200,
            patient_id=42,
            created_at=datetime(2026, 8, 17, 10, 0),
        )
        newer = self._assessment(
            assessment_id=100,
            patient_id=42,
            created_at=datetime(2026, 8, 17, 11, 0),
        )
        self.session.add_all([older, newer])
        self.session.commit()

        response = get_patient_assessments(
            42,
            self.session,
            self.caregiver,
        )

        self.assertEqual([item["id"] for item in response], [100, 200])
        self.assertEqual(
            [item["created_at"] for item in response],
            ["2026-08-17T11:00:00Z", "2026-08-17T10:00:00Z"],
        )
        self.assertIsNone(response[0]["diabetes_prediction_source"])
        self.assertIsNone(response[0]["heart_prediction_source"])
        self.assertIsNone(response[0]["diabetes_model_score"])
        self.assertIsNone(response[0]["heart_model_score"])

    def test_naive_historical_timestamp_is_serialized_as_utc(self):
        timestamp = datetime(2026, 8, 17, 17, 13, 43, 478309)

        self.assertEqual(
            _serialize_utc_timestamp(timestamp),
            "2026-08-17T17:13:43.478309Z",
        )

    def test_aware_timestamp_is_converted_to_utc_before_serialization(self):
        dhaka_timestamp = datetime(
            2026,
            8,
            17,
            23,
            13,
            43,
            478309,
            tzinfo=timezone(timedelta(hours=6)),
        )

        self.assertEqual(
            _serialize_utc_timestamp(dhaka_timestamp),
            "2026-08-17T17:13:43.478309Z",
        )


if __name__ == "__main__":
    unittest.main()
