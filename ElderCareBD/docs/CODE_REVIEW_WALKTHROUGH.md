# Code review walkthrough

| Area | Responsibility | Key files | Rationale |
|---|---|---|---|
| Flutter entry/theme | Starts the app, restores language, applies shared accessible Material theme | `mobile_app/lib/main.dart`, `mobile_app/lib/app.dart` | One root controls typography, palette, touch targets, inputs, cards, and localization delegates. |
| Navigation/screens | Caregiver workflow, selected patient, assessment, result, prescription, and history | `mobile_app/lib/screens/` | Screen-level state remains explicit and easy to demonstrate; shared widgets remove visual duplication. |
| Flutter API/session | Typed HTTP contracts, friendly transport errors, bearer session and selected-patient persistence | `mobile_app/lib/services/api_service.dart`, `session_service.dart` | Keeps networking/auth state out of presentation widgets and testable through injected clients/storage. |
| FastAPI entry/routers | Route registration and bounded domain endpoints | `backend/main.py`, `backend/routers/` | Routers separate authentication, patients, assessments, predictions, prescriptions, and medicines. |
| Authentication/security | Password hashing, bearer validation, ownership dependencies, OTP hashing/rate/attempt/expiry rules | `backend/security.py`, `identity.py`, `otp_verification.py`, `otp_delivery.py`, `routers/auth.py` | Server-side controls remain authoritative; the Flutter client is never trusted for ownership. |
| Database models | Durable caregiver/patient/assessment/prescription/medicine and migration state | `backend/models.py`, `database.py` | SQLAlchemy relationships and explicit migrations preserve historical compatibility. |
| ML inference | Loads approved artifacts, verifies hashes/contracts, validates inputs, returns model provenance | `backend/ml_model_service.py`, `prediction_schemas.py`, `routers/predictions.py` | Models stay server-side and fail closed to the labelled application fallback. |
| OCR | Private image storage, bounded Tesseract execution, conservative parsing | `backend/image_storage.py`, `ocr_engine.py`, `prescription_parser.py` | OCR is assistive; uncertain output remains editable and unconfirmed. |
| Prescription confirmation | Creates upload record, extracts candidates, requires explicit authenticated confirmation | `backend/routers/prescriptions.py`, `prescription_integrity.py` | Separates machine suggestion from caregiver-approved persisted medicine data. |
| Migrations | Idempotent schema upgrades and audit markers | `backend/migrate_*.py`, `backend/*_migration.py` | Production data is upgraded deliberately without destructive implicit schema creation. |
| Tests | Contract, security, migration, ML, OCR, widget, accessibility, and workflow regression | `backend/test_*.py`, `ml_training/tests/`, `mobile_app/test/` | Layered tests catch schema/API drift and visible Flutter failures. |

