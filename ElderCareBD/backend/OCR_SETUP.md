# Prescription OCR runtime setup

ElderCareBD describes this feature as **OCR-assisted prescription digitization
with caregiver verification**. OCR output and parser candidates are never
authoritative medicines until the caregiver reviews and confirms them.

## Audited development environment

Audit date: 2026-08-23 on the current Windows development machine.

- Python: 3.13.6.
- Backend Pillow: 12.3.0.
- No machine-global `tesseract.exe` was found on the process/user/machine
  `PATH`, in standard Windows installation directories, or in uninstall
  registry entries.
- A task-scoped runtime was subsequently staged outside the repository at
  `%TEMP%\ElderCareBD-Task12B\Tesseract-OCR\tesseract.exe`. It is Tesseract
  5.5.3.20260724 with Leptonica 1.87.0. Because it is temporary and not on
  `PATH`, `ELDERCARE_TESSERACT_CMD` must point to it explicitly for this audit.
- Its verified languages are `eng`, `ben`, and `osd`.
- Installer-supplied `eng.traineddata`: 4,113,088 bytes; SHA-256
  `7D4322BD2A7749724879683FC3912CB542F19906C83BCC1A52132556427170B2`.
- Official `tessdata_fast` `ben.traineddata`: 855,841 bytes; SHA-256
  `31163084C279AAEBD376216F0C3D5C17AD4B5FEE8DB49DAE79C20000B5DE5964`.
- The backend environment has no `pytesseract` package. None is needed: the
  backend adapter uses Python's standard subprocess API directly.

The application still handles a missing or later-removed runtime as OCR
unavailable, preserves the uploaded image, and allows manual medicine entry.
The temporary runtime is validation evidence, not a production installation.

## Install Tesseract on Windows

The Tesseract project's downloads documentation historically said that current
Windows installers were third-party, but that page lags the current 5.5.3
release assets. This task used the following Windows installer hosted directly
under the official `tesseract-ocr/tesseract` GitHub release:

- https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe
- size: 26,573,224 bytes
- SHA-256: `BEE9E3434BD94FD65387D9BE28CD467A41F61B1275383B55B0F59A1331270AE4`

The hash was also checked against the current Scoop manifest. A controlled
deployment may instead build/install the official project using a documented
package tool such as vcpkg. The project documentation remains useful but should
be reconciled with the selected release rather than treated as a current binary
inventory:

- https://tesseract-ocr.github.io/tessdoc/Downloads.html
- https://tesseract-ocr.github.io/tessdoc/Compiling.html

Record the exact Tesseract version, installer/source, architecture, and SHA-256
checksum in deployment records. Do not download executables or language data at
request time.

English uses `eng.traineddata`. Bengali uses `ben.traineddata`; both are
available from the official language-data repository:

- https://github.com/tesseract-ocr/tessdata
- https://github.com/tesseract-ocr/tessdata_fast
- https://github.com/tesseract-ocr/tessdoc/blob/main/Data-Files.md

Pin language data to a reviewed repository commit and record its checksum.
Bengali installation makes Bengali character recognition available, but does
not make the conservative medicine parser Bengali-aware or reliable on
handwriting.

## Configure ElderCareBD

The backend does not silently require a particular global install directory.
Configure an explicit executable path for stable Windows development and
deployment:

```powershell
$env:ELDERCARE_TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
$env:ELDERCARE_TESSERACT_LANGUAGES = 'eng'
$env:ELDERCARE_TESSERACT_TIMEOUT_SECONDS = '20'
$env:ELDERCARE_OCR_MAX_CONCURRENCY = '2'
```

For this task-scoped validation session specifically:

```powershell
$env:ELDERCARE_TESSERACT_CMD = `
  "$env:TEMP\ElderCareBD-Task12B\Tesseract-OCR\tesseract.exe"
```

For evaluated bilingual OCR, install both reviewed trained-data files and set:

```powershell
$env:ELDERCARE_TESSERACT_LANGUAGES = 'eng+ben'
```

If trained data is stored outside the installation's default `tessdata`
directory, configure `TESSDATA_PREFIX` according to the Tesseract installation
documentation. Keep this operational configuration outside source control.

Runtime bounds are defensive and cannot be disabled through environment values:

- timeout is clamped to 1-120 seconds (default 20);
- concurrency is clamped to 1-4 processes (default 2);
- OCR stdout is capped at 200,000 characters.

The concurrency semaphore is process-local. A deployment with multiple Uvicorn
workers can therefore run `workers × ELDERCARE_OCR_MAX_CONCURRENCY` Tesseract
processes; size worker counts and host-level resource controls accordingly.

An extraction request that reaches `processing` prevents a second extraction.
If its worker is forcibly terminated, the caregiver can still use the manual
review flow and atomically confirm medicines; confirmation wins through the
database claim and a stale OCR worker cannot overwrite `confirmed`. Automatic
re-extraction of an abandoned `processing` claim would require a future leased
job timestamp/reset mechanism.

The adapter passes a fixed argument list with `shell=False`, supplies no stdin,
spools stdout to an automatically cleaned temporary file before a bounded UTF-8
read, suppresses Windows console creation, and discards rather than returning or
logging Tesseract stderr. FastAPI routes must pass only an ownership-checked
image path resolved by the private image-storage layer.

## Verify the runtime without touching a database

From `backend/` in PowerShell:

```powershell
& $env:ELDERCARE_TESSERACT_CMD --version
& $env:ELDERCARE_TESSERACT_CMD --list-langs
& $env:ELDERCARE_TESSERACT_CMD `
  'tests\fixtures\prescription_ocr\clear_english.png' `
  stdout -l eng --psm 6
```

`--list-langs` must contain `eng` before English is enabled and `ben` before
`eng+ben` is configured. Treat a missing requested model as a deployment error,
not as successful support.

## Synthetic benchmark fixtures

The repository fixtures are generated, de-identified, and explicitly nonclinical:

- `clear_english.png`
- `noisy_low_resolution.png`
- `multiple_medicines.png`
- `near_empty.png`
- `bengali_printed.png`

The Bengali fixture uses the audited Windows `Nirmala.ttc` font (SHA-256
`AD02CDFC06E144AC45F318E8E5A64CBE04C7479D4BEB91D25F5A319A466B1767`).
Byte-for-byte regeneration of that optional fixture requires the same font;
portable English/empty fixtures remain reproducible without it.

Regenerate or verify them from `backend/`:

```powershell
venv\Scripts\python.exe tests\generate_ocr_fixtures.py
venv\Scripts\python.exe tests\generate_ocr_fixtures.py --check
venv\Scripts\python.exe -m unittest test_ocr_fixtures.py -v
```

The fixtures benchmark only a few synthetic printed English cases and one
Bengali case. They are not evidence of general prescription accuracy, clinical
correctness, handwriting support, or Bengali parser support.

## Audited synthetic benchmark result

Using the staged 5.5.3 runtime through `TesseractPrescriptionOcrEngine` with
`--psm 6`:

- clear English text was recognized exactly;
- the deterministic noisy/low-resolution English text was recognized exactly;
- all expected multiple-medicine text was recognized, with whitespace removed
  around `X`;
- the near-empty image returned an empty string and no invented text;
- the Bengali model returned reviewable Bengali text but made spelling and
  dosage-line errors on the synthetic Bengali fixture.

This small fixture run proves local invocation and failure-safe integration,
not general OCR accuracy. Bengali output must remain caregiver-reviewable, and
the current parser is intentionally English-focused.
