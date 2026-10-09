# Task 16 acceptance checklist

Status values are `PASS`, `FAIL`, or `PENDING DEVICE`. Automated results do not substitute for the mandatory physical Android run.

| Flow | Precondition | Steps | Expected result | Status |
|---|---|---|---|---|
| Register caregiver | Backend running; unused email/phone; delivery configured | Open Register, choose channel, enter identity/password, submit | Pending account is created and OTP screen opens without an auth token | PENDING DEVICE |
| Verify OTP | Valid pending challenge and delivered code | Enter six digits and select Verify Code | Account is verified; pending context is cleared; login is shown | PENDING DEVICE |
| Login | Verified caregiver | Enter identity/password and submit | Bearer session is saved and caregiver dashboard opens | PENDING DEVICE |
| Add patient | Authenticated caregiver | Open Patients, enter required profile fields, save | Patient is created under current caregiver and selected | PENDING DEVICE |
| Select patient | Caregiver has at least two owned patients | Select another patient on dashboard | Selected-patient summary and subsequent flows use that patient | PENDING DEVICE |
| DiaBD screening | Selected patient; supported gender; random-session mmol/L measurement | Complete vitals, confirm random glucose context, submit | DiaBD v3 result identifies model/version, score, threshold/classification, and disclaimer | PENDING DEVICE |
| Heart screening | Selected patient; supported clinical sex/chest-pain category; confirmed resting systolic BP | Complete required inputs and submit | Heart v2 result is clearly separated from the heuristic | PENDING DEVICE |
| Missing-input fallback | Omit or do not confirm a required model input | Submit general assessment | Assessment saves; unavailable model uses labelled heuristic demo fallback | PENDING DEVICE |
| Assessment history | At least one saved assessment | Open History > Assessments | Saved vitals, symptoms, model/fallback provenance, and timestamp render without overflow | PENDING DEVICE |
| Weekly Heart v2 record | At least one saved Heart v2 result | Open History > Assessments | Latest rolling seven-day saved-score summary renders and clearly states that it is not an acute heart-attack forecast | PENDING DEVICE |
| Take prescription photo | Camera-capable phone and permission available | Open Prescription, select Take photo, grant permission, capture | Image preview is shown and can be removed before upload | PENDING DEVICE |
| Select gallery image | Phone contains a test prescription image | Select Choose from gallery and choose image | Selected image preview and filename appear | PENDING DEVICE |
| OCR extraction | Uploaded prescription image; OCR configured | Select Extract Medicines | Progress is shown; raw OCR/candidates or a friendly manual fallback appears | PENDING DEVICE |
| Edit medicine | OCR candidate or manual entry exists | Edit fields; add/remove an item | Review list reflects edits; nothing is persisted automatically | PENDING DEVICE |
| Confirm prescription | Verified authenticated caregiver; reviewed candidate list | Select Confirm Reviewed Medicines | Prescription and reviewed medicines persist once | PENDING DEVICE |
| Prescription history | Confirmed prescription exists | Open History > Prescriptions | Prescription, protected image state, OCR status, and confirmed medicines are grouped | PENDING DEVICE |
| Logout/relaunch | Logged-in caregiver | Log out, close app, relaunch | Protected dashboard is not silently exposed; normal login/resume rules apply | PENDING DEVICE |
| Back/keyboard/layout | Any form screen | Navigate back; focus last fields; enlarge Android font | Back behavior is predictable; keyboard does not hide critical action; no overflow/exception | PENDING DEVICE |
| Feet/inches height | Assessment form | Enter whole feet and inches plus weight | BMI is calculated; the saved/API height remains centimetres and no unit is silently reinterpreted | PENDING DEVICE |
| Decimal glucose | Assessment form | Enter a value such as `6.1` or `7.00` | UI accepts mmol/L, saved general record remains compatible with the existing integer mg/dL API, and history displays mmol/L | PENDING DEVICE |
| ElderCare launcher icon | Android launcher | Install the current APK and inspect normal/round launcher presentation | Sea-green elder silhouette, protective heart/hand, and medical accent replace the Flutter template icon without mask cropping | PASS |

## Automated evidence completed

- Assessment narrow-phone and 180% text-scale widget checks: PASS (9 focused tests, including model flows).
- OTP registration/login/restart/error widget checks: PASS (10 focused tests).
- Shared role-selection, registration, and OTP viewport checks: PASS (3 focused tests at 320 x 780 and 180% text scale).
- Flutter analyzer: PASS (0 errors, 0 warnings, 0 informational lints).
- Full Flutter suite: PASS (169 tests passed, 0 failed).
- Full backend suite: PASS (126 tests passed, 0 failed).
- Full ML suite: PASS (75 tests passed, 0 failed).
- Flutter Web release build: PASS; the 900 x 700 tablet and 1440 x 1000 desktop layouts received a static visual review.
- Android debug APK (pre-latest UI update): PASS; built with LAN API configuration, installed on a Xiaomi 24117RN76G running Android 15, and launched successfully.
- Physical Android workflow (pre-latest UI update): PARTIAL; registration, captured development OTP verification, login, patient creation/selection, assessment keyboard/layout, BMI, and Heart v2 input controls were exercised. Assessment submission, histories, camera/gallery/OCR, logout/relaunch, and enlarged-font validation remain pending.
- Fresh post-update debug APK: BUILD/INSTALL PASS on 2026-10-06 with `--dart-define=ELDERCARE_API_BASE_URL=http://192.168.0.100:8000`. The icon/UI build (`63AE33D6238D27B370088943A4649B3166F662345064D8ACFCEFDCF1FE85BF4F`) was installed after two initial phone-side rejections; launcher, startup, login, dashboard cleanup, LAN access, camera permission, and camera launch passed. The latest helper-text rebuild (SHA-256 `CC6921DE35D13B9F469666221E9AE22268544833A186D71B057DA762BD1C13EB`) was subsequently installed successfully; its remaining end-to-end rows are still pending and are not counted as passed.
- Release APK build: PASS on 2026-10-06 (56,041,884 bytes; SHA-256 `FBF1A7B507671F0036376C6DA1FB98409B756D807F9A8381C58EBD1E27EDD682`). It currently uses the Android debug signing configuration, so this is not a production-signed release artifact.
- Feet/inches, decimal mmol/L glucose, weekly Heart v2 history, and global Bangla fallback still require completion of their physical-device rows. Dashboard cleanup and the ElderCare launcher icon have been physically observed on the installed Android build.
