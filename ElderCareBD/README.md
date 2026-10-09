# ElderCare BD

ElderCare BD is a caregiver-focused health-screening and prescription digitization prototype. It combines a Flutter mobile/web client, a FastAPI service, SQLite persistence, authenticated caregiver ownership, OTP verification, research/demo disease-risk models, and caregiver-reviewed OCR.

The application is decision support for a student research/demo setting. It is not a diagnostic device and does not replace professional medical advice.

## Current features

- caregiver registration, email/SMS OTP verification, password login, and bearer sessions
- caregiver-owned patient creation and selection
- general heuristic assessment with optional disease-specific screening
- DiaBD v3 diabetes status screening and Heart v2 reduced screening
- assessment and prescription history
- prescription camera/gallery input, OCR-assisted candidate extraction, editing, and explicit caregiver confirmation
- medicine stock/restock tracking
- English/Bangla key-label support, accessible controls, and responsive phone/web layouts

Kidney prediction is not deployed. OCR suggestions are never auto-confirmed.

## Architecture

- `mobile_app/`: Flutter client and widget/contract tests
- `backend/`: FastAPI routers, SQLAlchemy models, security, OTP, ML inference, OCR, migrations, and tests
- `ml_training/`: reproducible model training/evaluation code, immutable source data, artifacts, reports, and tests
- `docs/`: Task 16 acceptance, demo, review, manual, and repository-readiness notes

The Flutter service layer calls authenticated FastAPI routes. FastAPI enforces caregiver ownership before database, image, prediction, or prescription operations. Model artifacts are loaded server-side with contract and hash checks.

## Prerequisites

- Python matching the project virtual environment and packages in `backend/requirements.txt`
- Flutter 3.44.x / Dart 3.12.x or a compatible stable version
- Android SDK for APK/device testing
- Tesseract OCR for live extraction; see `backend/OCR_SETUP.md`

## Backend setup

Configure environment variables from `.env.example`. Development OTP capture is allowed only with an explicit non-production environment; production must use a real delivery provider and a strong OTP HMAC secret.

```powershell
cd backend
python -m pip install -r requirements.txt
$env:ELDERCARE_ENVIRONMENT = 'development'
$env:ELDERCARE_OTP_DELIVERY_MODE = 'capture'
$env:ELDERCARE_OTP_HMAC_SECRET = '<at-least-32-random-characters>'
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Use the migration commands documented in `backend/DEPLOYMENT.md`; do not replace an existing authoritative database.

## Flutter run and build

Web or desktop development:

```powershell
cd mobile_app
flutter pub get
flutter run -d chrome --dart-define=ELDERCARE_API_BASE_URL=http://127.0.0.1:8000
```

Physical Android demo on the same trusted Wi-Fi/LAN as the backend laptop:

```powershell
cd mobile_app
flutter build apk --debug --dart-define=ELDERCARE_API_BASE_URL=http://<DEMO_LAPTOP_IP>:8000
```

Do not commit the laptop IP. Debug Android permits cleartext LAN traffic for this local workflow; release builds should use an HTTPS backend.

Web release build:

```powershell
flutter build web --release --dart-define=ELDERCARE_API_BASE_URL=https://<DEPLOYED_API_HOST>
```

## Tests

```powershell
cd ml_training
python -m unittest discover -s tests -v

cd ..\backend
python -m pytest -q

cd ..\mobile_app
dart format --output=none --set-exit-if-changed lib test
flutter analyze --no-pub
flutter test --no-pub
```

## Security and privacy

Passwords are hashed, sessions use bearer authentication, OTP challenges are hashed and rate/attempt limited, and caregiver ownership is enforced server-side. Prescription images are private resources. Never commit `.env` files, databases, backups, uploads, prescription images, signing keys, or `android/local.properties`; see `docs/PUBLIC_REPOSITORY_READINESS.md`.

## Limitations

- disease models have internal research/demo validation only and do not express clinical certainty
- kidney prediction is not deployed
- OCR quality depends on image quality, language packs, and Tesseract availability
- live email/SMS requires deployment credentials
- camera behavior differs by browser; gallery upload is the dependable web demonstration path
- a physical Android device and reachable LAN backend are required for final on-device acceptance

