# ElderCare BD user manual source

## Installation and connection

Install the approved APK on an Android phone. For a local demonstration, connect the phone and backend laptop to the same trusted Wi-Fi network. The APK must have been built with `ELDERCARE_API_BASE_URL` pointing to the laptop's LAN address. Do not use `localhost` or `127.0.0.1` for a physical phone.

## Caregiver registration and OTP

1. Select **Caregiver / Family Member**, then **Register**.
2. Enter the caregiver name, choose email or SMS, enter the destination and a password, then submit once.
3. On the verification screen, check the masked destination and enter the six-digit code.
4. Use **Resend OTP** only when enabled. A replacement code invalidates the previous challenge.
5. After successful verification, return to caregiver login and use the registered identity/password.

Wrong, expired, or exhausted codes display a safe explanation. Do not share an OTP.

## Patient management

Open **Patients**, enter the required profile information, select only known medical-background items, and save. The newly saved patient becomes selected. The dashboard patient list can switch among patients owned by the logged-in caregiver. Long names wrap rather than changing identity.

## Health assessment

1. Confirm the selected patient.
2. Enter blood pressure, glucose, height, and weight with the displayed units.
3. The app calculates BMI; it does not ask the caregiver to interpret it clinically.
4. For DiaBD v3, use only a random-session glucose value in mmol/L and confirm that measurement context. Known diabetes makes this screening not applicable.
5. For Heart v2, select the supported clinical-sex and plain-language chest-pain metadata only when known, and confirm that systolic BP is a resting measurement.
6. Select observed symptoms, add optional notes, review, and submit.

Missing or unconfirmed model inputs do not block the general assessment. The result distinguishes research/demo ML output from the heuristic demonstration fallback. Scores are not clinical certainty.

## Prescription image and medicine review

1. Open **Prescription** and choose **Take photo** or **Choose from gallery**.
2. Review the preview; remove/replace it before upload if needed.
3. Save/upload the prescription, then request OCR extraction.
4. Review raw OCR text when useful. Edit every proposed medicine and add/remove entries as required.
5. Select **Confirm Reviewed Medicines** only after checking the list. OCR never auto-confirms.

If OCR is unavailable or cannot read the image, enter medicines manually. Only a verified, authenticated caregiver can persist confirmation.

## History and medicine tracker

**History** contains assessment, prescription, and medicine tabs for the selected patient. Pull-to-refresh or use the labelled refresh action when available. The medicine tracker estimates restock dates from saved quantity and daily dose; it is a planning aid.

## Language and accessibility

Use the English/Bangla action on authentication screens to switch key labels. The preference is retained. The interface supports larger system text, screen-reader semantics on important progress/actions, 48-pixel targets, and phone/web responsive widths.

## Logout and relaunch

Use the dashboard logout action. Relaunching must not expose protected data after logout. An unfinished valid OTP challenge may resume at verification; malformed or expired pending state returns to normal entry.

## Common errors

- **Could not connect to server:** Confirm backend, LAN, firewall, and APK base URL.
- **Verification code expired:** Request a new code and use only the latest one.
- **Please check required fields:** Correct highlighted values/units, then retry once.
- **Screening model unavailable:** The general assessment can still be saved with labelled fallback.
- **OCR could not read the image:** Retake in good light or enter medicines manually.
- **No data:** Add/select a patient or create the relevant assessment/prescription first.

ElderCare BD provides preliminary research/demo screening support only. Seek a qualified clinician for diagnosis or treatment decisions.

