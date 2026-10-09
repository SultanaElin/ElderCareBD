import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import image_storage
import models
from auth_test_support import create_verified_caregiver_session
from database import Base, get_db
from ocr_engine import (
    PrescriptionOcrEngine,
    PrescriptionOcrError,
    PrescriptionOcrResult,
    PrescriptionOcrTimeoutError,
    TesseractPrescriptionOcrEngine,
    get_prescription_ocr_engine,
)
from prescription_parser import PrescriptionMedicineParser
from routers import auth, medicines, patients, prescriptions
from test_core_workflow import _database_signatures
from test_prescription_foundation import RawRequestHarness


class FakeOcrEngine(PrescriptionOcrEngine):
    def __init__(self, text="", failure=None):
        self.text = text
        self.failure = failure
        self.calls = 0

    @property
    def name(self):
        return "fake-ocr"

    @property
    def languages(self):
        return ("eng",)

    def extract_text(self, _image_path):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return PrescriptionOcrResult(
            text=self.text,
            engine=self.name,
            languages=self.languages,
        )


class PrescriptionOcrRouteTest(unittest.TestCase):
    def setUp(self):
        self.database_signatures = _database_signatures()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="eldercare-task12b-test-"
        )
        self.original_private_directory = image_storage.PRIVATE_UPLOAD_DIR
        image_storage.PRIVATE_UPLOAD_DIR = (
            Path(self.temporary_directory.name) / "private_uploads"
        ).resolve()
        self.ocr_engine = FakeOcrEngine()

        app = FastAPI()
        app.include_router(auth.router)
        app.include_router(patients.router)
        app.include_router(prescriptions.router)
        app.include_router(medicines.router)

        def override_get_db():
            yield self.session

        def override_ocr_engine():
            return self.ocr_engine

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_prescription_ocr_engine] = override_ocr_engine
        self.client = RawRequestHarness(app)

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        image_storage.PRIVATE_UPLOAD_DIR = self.original_private_directory
        self.temporary_directory.cleanup()
        self.assertEqual(self.database_signatures, _database_signatures())

    def _register(self, label):
        return create_verified_caregiver_session(
            self.session,
            name=f"OCR Caregiver {label}",
            identity=f"task12b-{label}@example.invalid",
            password=f"secure-task12b-password-{label}",
        )

    def _patient(self, caregiver_id, token, label):
        status, body, _ = self.client.json(
            "POST",
            "/patients/",
            {
                "caregiver_id": caregiver_id,
                "name": f"OCR Patient {label}",
                "age": 72,
                "gender": "Other",
            },
            token,
        )
        self.assertEqual(status, 200)
        return body["patient_id"]

    @staticmethod
    def _image_bytes():
        from PIL import Image

        output = io.BytesIO()
        Image.new("RGB", (240, 160), "white").save(output, format="PNG")
        return output.getvalue()

    def _prescription(self, patient_id, token, with_image=True):
        status, body, _ = self.client.multipart(
            "POST",
            "/prescriptions/",
            {"patient_id": patient_id},
            token,
            self._image_bytes() if with_image else None,
            filename="synthetic-prescription.png",
            file_content_type="image/png",
        )
        self.assertEqual(status, 200)
        return body["prescription_id"]

    def test_extraction_requires_authentication_and_owned_image(self):
        caregiver_a, token_a = self._register("security-a")
        caregiver_b, token_b = self._register("security-b")
        patient_a = self._patient(caregiver_a, token_a, "security-a")
        image_prescription = self._prescription(patient_a, token_a)
        no_image_prescription = self._prescription(
            patient_a,
            token_a,
            with_image=False,
        )

        status, _, _ = self.client.json(
            "POST", f"/prescriptions/{image_prescription}/extract"
        )
        self.assertEqual(status, 401)
        status, _, _ = self.client.json(
            "POST",
            f"/prescriptions/{image_prescription}/extract",
            token=token_b,
        )
        self.assertEqual(status, 404)
        status, body, _ = self.client.json(
            "POST",
            f"/prescriptions/{no_image_prescription}/extract",
            token=token_a,
        )
        self.assertEqual(status, 409)
        self.assertEqual(
            body["detail"],
            "Prescription does not have a valid stored image.",
        )

        unsafe_prescription = self.session.get(
            models.Prescription,
            no_image_prescription,
        )
        unsafe_prescription.image_path = r"..\eldercare_bd.db"
        self.session.commit()
        status, body, _ = self.client.json(
            "POST",
            f"/prescriptions/{no_image_prescription}/extract",
            token=token_a,
        )
        self.assertEqual(status, 409)
        self.assertEqual(
            body["detail"],
            "Prescription does not have a valid stored image.",
        )
        self.assertEqual(self.ocr_engine.calls, 0)

    def test_success_stores_raw_text_but_not_candidate_medicines(self):
        caregiver_id, token = self._register("success")
        patient_id = self._patient(caregiver_id, token, "success")
        prescription_id = self._prescription(patient_id, token)
        self.ocr_engine.text = (
            "Paracetamol 500 mg\n"
            "1 tablet twice daily for 5 days after food\n"
            "Tab. Napa 500 mg\n"
            "1+1+1 \u00d7 3 days\n"
        )

        status, body, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/extract", token=token
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["ocr_status"], "ready")
        self.assertEqual(body["ocr_engine"], "fake-ocr")
        self.assertEqual(body["ocr_languages"], ["eng"])
        self.assertFalse(body["reused"])
        self.assertEqual(len(body["candidates"]), 2)
        self.assertEqual(body["candidates"][0]["name"], "Paracetamol")
        self.assertEqual(body["candidates"][0]["strength"], "500 mg")
        self.assertEqual(body["candidates"][0]["dosage"], "1 tablet")
        self.assertEqual(body["candidates"][0]["frequency"], "twice daily")
        self.assertEqual(body["candidates"][0]["duration"], "5 days")
        self.assertEqual(body["candidates"][0]["instructions"], "after food")
        self.assertEqual(body["candidates"][1]["frequency"], "1+1+1")
        self.assertEqual(self.session.query(models.Medicine).count(), 0)

        prescription = self.session.get(models.Prescription, prescription_id)
        self.session.refresh(prescription)
        self.assertEqual(prescription.ocr_text, self.ocr_engine.text)
        self.assertEqual(prescription.ocr_status, "ready")
        self.assertEqual(prescription.ocr_engine, "fake-ocr:eng")
        self.assertIsNone(prescription.ocr_error)

        status, detail, _ = self.client.json(
            "GET", f"/prescriptions/{prescription_id}", token=token
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["ocr_text"], self.ocr_engine.text)
        self.assertNotIn("image_path", detail)

    def test_ready_reextract_is_idempotent_and_never_creates_medicines(self):
        caregiver_id, token = self._register("repeat")
        patient_id = self._patient(caregiver_id, token, "repeat")
        prescription_id = self._prescription(patient_id, token)
        self.ocr_engine.text = "Cap. Omeprazole 20 mg\n1 capsule once daily"

        first_status, first, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/extract", token=token
        )
        second_status, second, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/extract", token=token
        )
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(first["ocr_text"], second["ocr_text"])
        self.assertEqual(first["candidates"], second["candidates"])
        self.assertEqual(self.ocr_engine.calls, 1)
        self.assertEqual(self.session.query(models.Medicine).count(), 0)

    def test_failure_and_timeout_set_failed_without_deleting_image(self):
        for label, failure, expected_warning in (
            (
                "failure",
                PrescriptionOcrError(),
                "OCR processing failed. You can enter medicines manually.",
            ),
            (
                "timeout",
                PrescriptionOcrTimeoutError(),
                "OCR processing timed out. You can enter medicines manually.",
            ),
        ):
            with self.subTest(label=label):
                caregiver_id, token = self._register(label)
                patient_id = self._patient(caregiver_id, token, label)
                prescription_id = self._prescription(patient_id, token)
                prescription = self.session.get(models.Prescription, prescription_id)
                image_path = image_storage.PRIVATE_UPLOAD_DIR / prescription.image_path
                self.assertTrue(image_path.is_file())
                self.ocr_engine = FakeOcrEngine(failure=failure)

                status, body, _ = self.client.json(
                    "POST", f"/prescriptions/{prescription_id}/extract", token=token
                )
                self.assertEqual(status, 200)
                self.assertEqual(body["ocr_status"], "failed")
                self.assertEqual(body["candidates"], [])
                self.assertIn(expected_warning, body["warnings"])
                self.assertNotIn(str(image_path), str(body))
                self.assertTrue(image_path.is_file())
                self.session.expire_all()
                prescription = self.session.get(models.Prescription, prescription_id)
                self.assertEqual(prescription.ocr_status, "failed")
                self.assertEqual(prescription.ocr_error, expected_warning)
                self.assertEqual(self.session.query(models.Medicine).count(), 0)

    def test_cross_owner_cannot_read_raw_ocr_text(self):
        caregiver_a, token_a = self._register("privacy-a")
        caregiver_b, token_b = self._register("privacy-b")
        patient_a = self._patient(caregiver_a, token_a, "privacy-a")
        prescription_id = self._prescription(patient_a, token_a)
        self.ocr_engine.text = "Synthetic Secret Medicine 10 mg"
        status, _, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/extract", token=token_a
        )
        self.assertEqual(status, 200)

        status, _, _ = self.client.json(
            "GET", f"/prescriptions/{prescription_id}", token=token_b
        )
        self.assertEqual(status, 404)
        status, prescriptions_body, _ = self.client.json(
            "GET", "/prescriptions/", token=token_b
        )
        self.assertEqual(status, 200)
        self.assertEqual(prescriptions_body, [])

    def test_processing_state_blocks_overlap_but_manual_confirmation_can_recover(self):
        caregiver_id, token = self._register("overlap")
        patient_id = self._patient(caregiver_id, token, "overlap")
        prescription_id = self._prescription(patient_id, token)
        prescription = self.session.get(models.Prescription, prescription_id)
        prescription.ocr_status = "processing"
        self.session.commit()

        status, body, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/extract", token=token
        )
        self.assertEqual(status, 409)
        self.assertEqual(
            body["detail"],
            "Prescription extraction is already in progress.",
        )
        status, body, _ = self.client.json(
            "POST",
            f"/prescriptions/{prescription_id}/confirm",
            {"medicines": [{"name": "Manual medicine"}]},
            token,
        )
        self.assertEqual(status, 200)
        self.assertFalse(body["already_confirmed"])
        self.assertEqual(self.session.query(models.Medicine).count(), 1)
        self.session.expire_all()
        prescription = self.session.get(models.Prescription, prescription_id)
        self.assertEqual(prescription.ocr_status, "confirmed")

        status, _, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/extract", token=token
        )
        self.assertEqual(status, 409)

    def test_reviewed_confirmation_after_extraction_remains_idempotent(self):
        caregiver_id, token = self._register("confirm")
        patient_id = self._patient(caregiver_id, token, "confirm")
        prescription_id = self._prescription(patient_id, token)
        self.ocr_engine.text = "Tab. Napa 500 mg\n1 tablet twice daily for 3 days"
        status, extracted, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/extract", token=token
        )
        self.assertEqual(status, 200)
        candidate = extracted["candidates"][0]
        payload = {
            "medicines": [
                {
                    key: candidate[key]
                    for key in (
                        "name",
                        "strength",
                        "dosage",
                        "frequency",
                        "duration",
                        "instructions",
                    )
                }
            ]
        }
        status, confirmed, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/confirm", payload, token
        )
        self.assertEqual(status, 200)
        self.assertFalse(confirmed["already_confirmed"])
        status, repeated, _ = self.client.json(
            "POST", f"/prescriptions/{prescription_id}/confirm", payload, token
        )
        self.assertEqual(status, 200)
        self.assertTrue(repeated["already_confirmed"])
        self.assertEqual(self.session.query(models.Medicine).count(), 1)
        prescription = self.session.get(models.Prescription, prescription_id)
        self.session.refresh(prescription)
        self.assertEqual(prescription.ocr_status, "confirmed")
        self.assertEqual(prescription.ocr_text, self.ocr_engine.text)


class PrescriptionMedicineParserTest(unittest.TestCase):
    def setUp(self):
        self.parser = PrescriptionMedicineParser()

    def test_clear_and_multiple_patterns_are_extracted_conservatively(self):
        candidates = self.parser.parse(
            "Paracetamol 500 mg\n"
            "1 tablet twice daily for 5 days after food\n"
            "Cap. Omeprazole 20 mg\n"
            "1+0+0 x 7 days"
        )
        self.assertEqual([item["name"] for item in candidates], ["Paracetamol", "Omeprazole"])
        self.assertEqual(candidates[0]["strength"], "500 mg")
        self.assertEqual(candidates[0]["dosage"], "1 tablet")
        self.assertEqual(candidates[0]["frequency"], "twice daily")
        self.assertEqual(candidates[0]["duration"], "5 days")
        self.assertEqual(candidates[1]["frequency"], "1+0+0")
        self.assertEqual(candidates[1]["duration"], "7 days")

    def test_uncertain_line_is_reviewable_without_fabricated_fields(self):
        candidates = self.parser.parse("Medi cine unclear")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_line"], "Medi cine unclear")
        self.assertEqual(candidates[0]["name"], "Medi cine unclear")
        self.assertEqual(candidates[0]["confidence"], "low")
        self.assertIsNone(candidates[0]["strength"])
        self.assertIsNone(candidates[0]["dosage"])
        self.assertIsNone(candidates[0]["frequency"])
        self.assertIsNone(candidates[0]["duration"])
        self.assertIsNone(candidates[0]["instructions"])
        self.assertIn("Medicine name is uncertain.", candidates[0]["warnings"])

    def test_numeric_frequency_with_multiplication_sign_is_supported(self):
        candidates = self.parser.parse(
            "Tab. Napa 500 mg\n1+1+1 \u00d7 3 days"
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["frequency"], "1+1+1")
        self.assertEqual(candidates[0]["duration"], "3 days")

    def test_one_line_medicine_and_directions_are_not_dropped(self):
        examples = (
            (
                "Tab. Napa 500 mg 1 tablet twice daily for 3 days",
                "Napa",
                "1 tablet",
                "twice daily",
                "3 days",
            ),
            (
                "Tab. Napa 500 mg 1+1+1 x 3 days",
                "Napa",
                None,
                "1+1+1",
                "3 days",
            ),
            (
                "Paracetamol 500 mg twice daily for 5 days",
                "Paracetamol",
                None,
                "twice daily",
                "5 days",
            ),
        )
        for source, name, dosage, frequency, duration in examples:
            with self.subTest(source=source):
                candidates = self.parser.parse(source)
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]["name"], name)
                self.assertEqual(candidates[0]["dosage"], dosage)
                self.assertEqual(candidates[0]["frequency"], frequency)
                self.assertEqual(candidates[0]["duration"], duration)
                self.assertEqual(candidates[0]["source_line"], source)

        self.assertEqual(
            self.parser.parse("Take 5 ml twice daily for 3 days"),
            [],
        )

    def test_liquid_concentration_is_distinct_from_dosage(self):
        candidates = self.parser.parse(
            "Syr. Amoxicillin 125 mg/5 ml 5 ml twice daily for 7 days"
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["name"], "Amoxicillin")
        self.assertEqual(candidates[0]["strength"], "125 mg/5 ml")
        self.assertEqual(candidates[0]["dosage"], "5 ml")
        self.assertEqual(candidates[0]["frequency"], "twice daily")
        self.assertEqual(candidates[0]["duration"], "7 days")

    def test_later_frequency_removes_an_earlier_missing_frequency_warning(self):
        candidates = self.parser.parse(
            "Tab. Napa 500 mg 1 tablet\nTwice daily for 3 days"
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["frequency"], "Twice daily")
        self.assertNotIn(
            "Frequency was not recognized.",
            candidates[0]["warnings"],
        )

    def test_empty_or_non_medicine_text_does_not_create_fake_candidate(self):
        self.assertEqual(self.parser.parse(""), [])
        self.assertEqual(
            self.parser.parse(
                "SYNTHETIC - NOT CLINICAL\n"
                "Prescription\nDate 23 August 2026\nTake after food"
            ),
            [],
        )


class TesseractPrescriptionOcrEngineTest(unittest.TestCase):
    def test_adapter_uses_bounded_shell_free_argument_list(self):
        ocr_engine = TesseractPrescriptionOcrEngine(
            executable=r"C:\Program Files\Tesseract OCR\tesseract.exe",
            languages="eng+ben",
            timeout_seconds=7,
            max_concurrency=1,
        )
        def complete_successfully(**options):
            options["stdout"].write(b"Synthetic OCR text\n")
            return subprocess.CompletedProcess(
                args=options["args"],
                returncode=0,
            )

        with patch(
            "ocr_engine.subprocess.run",
            side_effect=complete_successfully,
        ) as run:
            result = ocr_engine.extract_text(Path(r"C:\private\safe image.png"))

        self.assertEqual(result.text, "Synthetic OCR text\n")
        self.assertEqual(result.languages, ("eng", "ben"))
        options = run.call_args.kwargs
        self.assertFalse(options["shell"])
        self.assertEqual(options["stderr"], subprocess.DEVNULL)
        self.assertNotIn("capture_output", options)
        self.assertEqual(options["timeout"], 7)
        self.assertIsInstance(options["args"], list)
        self.assertEqual(options["args"][1], r"C:\private\safe image.png")
        self.assertEqual(options["args"][4], "eng+ben")

    def test_adapter_maps_timeout_without_exposing_command_details(self):
        ocr_engine = TesseractPrescriptionOcrEngine(
            executable="tesseract-test",
            timeout_seconds=1,
        )
        with patch(
            "ocr_engine.subprocess.run",
            side_effect=subprocess.TimeoutExpired("sensitive-command", 1),
        ):
            with self.assertRaises(PrescriptionOcrTimeoutError) as context:
                ocr_engine.extract_text(Path("safe.png"))
        self.assertNotIn("sensitive-command", str(context.exception))


if __name__ == "__main__":
    unittest.main()
