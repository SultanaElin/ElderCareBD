"""Generate the deterministic, synthetic prescription OCR benchmark images.

The fixtures contain no names, identifiers, or real prescription data. Portable
fixtures use Pillow's bundled font; the optional Bengali fixture records and
requires the exact audited system-font hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "prescription_ocr"
DEFAULT_BENGALI_FONT = Path(
    os.getenv(
        "ELDERCARE_OCR_BENGALI_FIXTURE_FONT",
        r"C:\Windows\Fonts\Nirmala.ttc",
    )
)
PINNED_BENGALI_FONT_SHA256 = (
    "ad02cdfc06e144ac45f318e8e5a64cbe04c7479d4beb91d25f5a319a466b1767"
)
PORTABLE_IMAGE_FILENAMES = (
    "clear_english.png",
    "noisy_low_resolution.png",
    "multiple_medicines.png",
    "near_empty.png",
)
IMAGE_FILENAMES = (
    *PORTABLE_IMAGE_FILENAMES,
    "bengali_printed.png",
)


def _font(size: int):
    # Pillow ships this font, avoiding dependence on private/system font files.
    return ImageFont.load_default(size=size)


def _draw_lines(
    image: Image.Image,
    lines: tuple[str, ...],
    *,
    origin: tuple[int, int],
    font_size: int,
    line_gap: int,
):
    draw = ImageDraw.Draw(image)
    font = _font(font_size)
    x, y = origin
    for line in lines:
        draw.text((x, y), line, fill=(20, 32, 30), font=font)
        y += font_size + line_gap


def _clear_english():
    lines = (
        "PRESCRIPTION - SYNTHETIC ONLY",
        "PARACETAMOL 500 MG",
        "1 TABLET TWICE DAILY FOR 5 DAYS",
    )
    image = Image.new("RGB", (1200, 520), (250, 249, 242))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 1169, 489), outline=(45, 115, 98), width=4)
    _draw_lines(image, lines, origin=(85, 85), font_size=42, line_gap=38)
    return image, lines


def _multiple_medicines():
    lines = (
        "PRESCRIPTION - SYNTHETIC ONLY",
        "TAB NAPA 500 MG",
        "1+1+1 X 3 DAYS",
        "CAP AMOXICILLIN 250 MG",
        "1 CAPSULE THREE TIMES DAILY FOR 7 DAYS",
    )
    image = Image.new("RGB", (1400, 760), (250, 249, 242))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 1369, 729), outline=(45, 115, 98), width=4)
    _draw_lines(image, lines, origin=(80, 75), font_size=40, line_gap=35)
    return image, lines


def _noisy_low_resolution():
    lines = (
        "PRESCRIPTION - SYNTHETIC ONLY",
        "TAB CETIRIZINE 10 MG",
        "1 TABLET ONCE DAILY FOR 3 DAYS",
    )
    image = Image.new("RGB", (520, 300), (238, 237, 230))
    _draw_lines(image, lines, origin=(20, 45), font_size=18, line_gap=25)

    # Fixed-seed linear congruential noise is stable and needs no random module.
    draw = ImageDraw.Draw(image)
    state = 0x0ECBD12B
    for _ in range(950):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        x = state % image.width
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        y = state % image.height
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        shade = 155 + (state % 80)
        draw.point((x, y), fill=(shade, shade, shade))
    draw.line((0, 254, 519, 248), fill=(185, 185, 180), width=2)
    return image, lines


def _near_empty():
    image = Image.new("RGB", (640, 400), (250, 249, 242))
    draw = ImageDraw.Draw(image)
    draw.line((75, 92, 125, 90), fill=(238, 237, 232), width=2)
    draw.line((500, 310, 555, 313), fill=(239, 238, 233), width=2)
    draw.point((320, 205), fill=(235, 234, 229))
    return image, ()


def _bengali_printed(font_path: Path):
    font_hash = hashlib.sha256(font_path.read_bytes()).hexdigest()
    if font_hash != PINNED_BENGALI_FONT_SHA256:
        raise RuntimeError(
            "Bengali fixture generation requires the audited Nirmala font "
            f"with SHA-256 {PINNED_BENGALI_FONT_SHA256}."
        )
    lines = (
        "সিনথেটিক - চিকিৎসার জন্য নয়",
        "ট্যাব নাপা ৫০০ মি.গ্রা.",
        "১+১+১ × ৩ দিন",
    )
    image = Image.new("RGB", (1200, 570), (250, 249, 242))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 1169, 539), outline=(45, 115, 98), width=4)
    font = ImageFont.truetype(str(font_path), size=44, index=0)
    y = 85
    for line in lines:
        draw.text((75, y), line, fill=(20, 32, 30), font=font)
        y += 125
    return image, lines


def _sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_fixtures(
    output_directory: Path = FIXTURE_DIRECTORY,
    *,
    include_bengali: bool = True,
    bengali_font: Path = DEFAULT_BENGALI_FONT,
):
    output_directory.mkdir(parents=True, exist_ok=True)
    definitions = (
        (
            "clear_english.png",
            "clear English printed prescription",
            _clear_english,
            "Medicine name, strength, dosage, frequency, and duration are visible.",
        ),
        (
            "noisy_low_resolution.png",
            "noisy low-resolution printed prescription",
            _noisy_low_resolution,
            "OCR may be imperfect; uncertain text must remain reviewable.",
        ),
        (
            "multiple_medicines.png",
            "multiple printed medicines",
            _multiple_medicines,
            "Two medicine candidates should remain separate.",
        ),
        (
            "near_empty.png",
            "near-empty image",
            _near_empty,
            "No medicine candidate should be fabricated.",
        ),
    )

    if include_bengali:
        if not bengali_font.is_file():
            raise RuntimeError(
                "Bengali fixture font not found. Set "
                "ELDERCARE_OCR_BENGALI_FIXTURE_FONT to the audited font path."
            )
        definitions += (
            (
                "bengali_printed.png",
                "Bengali printed prescription",
                lambda: _bengali_printed(bengali_font),
                (
                    "Bengali OCR may expose raw text for review; the current "
                    "medicine parser remains English-focused."
                ),
            ),
        )

    entries = []
    for filename, category, factory, expectation in definitions:
        image, expected_lines = factory()
        image_path = output_directory / filename
        image.save(image_path, format="PNG", compress_level=9, optimize=False)
        entries.append(
            entry := {
                "file": filename,
                "category": category,
                "dimensions": list(image.size),
                "mode": image.mode,
                "expected_text_lines": list(expected_lines),
                "expectation": expectation,
                "sha256": _sha256(image_path),
            }
        )
        if filename == "bengali_printed.png":
            entry["font"] = {
                "file": bengali_font.name,
                "sha256": PINNED_BENGALI_FONT_SHA256,
            }

    manifest = {
        "schema_version": 1,
        "description": (
            "Deterministic, de-identified synthetic images for OCR-assisted "
            "prescription digitization tests. Not clinical data."
        ),
        "generator": "tests/generate_ocr_fixtures.py",
        "fixtures": entries,
    }
    manifest_path = output_directory / "manifest.json"
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=True) + "\n"
    with manifest_path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(manifest_text)
    return manifest


def check_fixtures(fixture_directory: Path = FIXTURE_DIRECTORY):
    manifest_path = fixture_directory / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("OCR fixture manifest is missing.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    corrupt_files = [
        entry["file"]
        for entry in manifest.get("fixtures", [])
        if not (fixture_directory / entry["file"]).is_file()
        or _sha256(fixture_directory / entry["file"]) != entry["sha256"]
    ]
    if corrupt_files:
        raise SystemExit(
            "OCR fixture hashes do not match the manifest: "
            + ", ".join(corrupt_files)
        )

    can_generate_bengali = (
        DEFAULT_BENGALI_FONT.is_file()
        and _sha256(DEFAULT_BENGALI_FONT) == PINNED_BENGALI_FONT_SHA256
    )
    with tempfile.TemporaryDirectory(prefix="eldercare-ocr-fixtures-") as temporary:
        generated_directory = Path(temporary)
        generate_fixtures(
            generated_directory,
            include_bengali=can_generate_bengali,
        )
        expected_files = (
            (*IMAGE_FILENAMES, "manifest.json")
            if can_generate_bengali
            else PORTABLE_IMAGE_FILENAMES
        )
        differences = [
            filename
            for filename in expected_files
            if not (fixture_directory / filename).is_file()
            or (fixture_directory / filename).read_bytes()
            != (generated_directory / filename).read_bytes()
        ]
    if differences:
        raise SystemExit(
            "OCR fixtures are missing or stale: " + ", ".join(differences)
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=FIXTURE_DIRECTORY,
        help="Directory for generated PNG files and manifest.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed fixtures match a fresh deterministic generation.",
    )
    arguments = parser.parse_args()
    if arguments.check:
        check_fixtures(arguments.output_dir)
    else:
        generate_fixtures(arguments.output_dir)


if __name__ == "__main__":
    main()
