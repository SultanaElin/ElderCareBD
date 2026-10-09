import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tests.generate_ocr_fixtures import (
    DEFAULT_BENGALI_FONT,
    IMAGE_FILENAMES,
    PINNED_BENGALI_FONT_SHA256,
    PORTABLE_IMAGE_FILENAMES,
    generate_fixtures,
)


FIXTURE_DIRECTORY = Path(__file__).parent / "tests" / "fixtures" / "prescription_ocr"


class PrescriptionOcrFixtureTests(unittest.TestCase):
    def test_manifest_and_images_are_valid_and_deidentified(self):
        manifest = json.loads(
            (FIXTURE_DIRECTORY / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["schema_version"], 1)
        self.assertIn("synthetic", manifest["description"].lower())
        self.assertIn("de-identified", manifest["description"].lower())
        self.assertEqual(
            [entry["file"] for entry in manifest["fixtures"]],
            list(IMAGE_FILENAMES),
        )

        for entry in manifest["fixtures"]:
            image_path = FIXTURE_DIRECTORY / entry["file"]
            self.assertEqual(
                hashlib.sha256(image_path.read_bytes()).hexdigest(),
                entry["sha256"],
            )
            with Image.open(image_path) as image:
                image.verify()
            with Image.open(image_path) as image:
                image.load()
                self.assertEqual(list(image.size), entry["dimensions"])
                self.assertEqual(image.mode, entry["mode"])

            expected_text = "\n".join(entry["expected_text_lines"]).lower()
            self.assertNotIn("patient name", expected_text)
            self.assertNotIn("@", expected_text)
            self.assertNotRegex(expected_text, r"\b\d{10,}\b")

    def test_generation_is_byte_for_byte_reproducible(self):
        can_generate_bengali = (
            DEFAULT_BENGALI_FONT.is_file()
            and hashlib.sha256(DEFAULT_BENGALI_FONT.read_bytes()).hexdigest()
            == PINNED_BENGALI_FONT_SHA256
        )
        with tempfile.TemporaryDirectory(prefix="eldercare-ocr-test-") as temporary:
            generated_directory = Path(temporary)
            generate_fixtures(
                generated_directory,
                include_bengali=can_generate_bengali,
            )
            filenames = (
                (*IMAGE_FILENAMES, "manifest.json")
                if can_generate_bengali
                else PORTABLE_IMAGE_FILENAMES
            )
            for filename in filenames:
                self.assertEqual(
                    (FIXTURE_DIRECTORY / filename).read_bytes(),
                    (generated_directory / filename).read_bytes(),
                    filename,
                )


if __name__ == "__main__":
    unittest.main()
