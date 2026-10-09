# Public repository readiness audit

## Result

The source tree is **not ready to publish as-is** because it currently contains authoritative/local SQLite databases, database backups, private prescription images, legacy uploads, virtual environments, generated Flutter content, logs, and `android/local.properties`. No files were deleted during this audit.

The root `.gitignore` now excludes those categories for future Git tracking. Ignore rules do not remove files already tracked in an existing repository; inspect the index/history before publishing.

## Files/directories that must not be committed

- `backend/eldercare_bd.db`, `backend/eldercare_bd_2.db`, any `*.db-*` sidecars
- `backend/backups/`
- `backend/private_uploads/` and `backend/uploads/`
- `.env` and environment-specific variants
- Android signing keys, `key.properties`, and `mobile_app/android/local.properties`
- `.venv/`, `backend/venv/`, `ml_training/venv/`
- Flutter `build/`, `.dart_tool/`, `ephemeral/`, and log files
- any real patient export, prescription image, OTP capture, SMTP credential, API key, or bearer token

## Credential findings

- Backend settings are environment-driven for database, OTP HMAC, SMTP, private upload location, and Tesseract.
- Test-only secret strings and test passwords are present in tests; they are fixtures, but should remain clearly non-production.
- `.env.example` contains placeholders only.
- No machine-specific demo IP was added to source. Flutter obtains the backend URL through `--dart-define=ELDERCARE_API_BASE_URL=...`.

## Required pre-publication procedure

1. Initialize/use the intended repository root and review `git status` plus `git ls-files`.
2. Remove private/generated files from the Git index without deleting working data.
3. Scan the full commit history with a secret scanner; rotate any credential ever committed.
4. Inspect every database/upload manually for patient or prescription data.
5. Confirm approved ML datasets/artifacts have appropriate licenses and redistribution rights.
6. Replace the Android example application ID and configure a private release signing process before distribution.
7. Re-run tests and build from a clean clone using only documented prerequisites.

## Remaining release issue

The Android release build currently uses the debug signing configuration. That is acceptable only for local demonstration and must not be treated as a production signing setup.

