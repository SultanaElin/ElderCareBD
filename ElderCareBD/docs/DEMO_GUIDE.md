# ElderCare BD 10-minute demo guide

## Before the audience arrives

1. Put the Android phone and laptop on the same trusted Wi-Fi network.
2. Find the laptop LAN IPv4 address without writing it into source control.
3. Start FastAPI on `0.0.0.0:8000` with the authoritative database and configured OTP/OCR environment.
4. Build/install the debug APK:
   `flutter build apk --debug --dart-define=ELDERCARE_API_BASE_URL=http://<DEMO_LAPTOP_IP>:8000`
5. Confirm Windows firewall permits the trusted-network connection and open the app once.
6. Prepare an unused demo caregiver identity, an OTP delivery/capture plan, one synthetic patient, and a non-private prescription image.

## Suggested flow

1. **Introduction (45 seconds):** Explain caregiver ownership, non-diagnostic screening, and caregiver-reviewed OCR.
2. **Registration/OTP/login (75 seconds):** Register, show the masked destination/countdown, verify, then complete normal password login.
3. **Dashboard (45 seconds):** Point out selected patient, quick actions, alerts, history, and language toggle.
4. **Patient (45 seconds):** Add/select a synthetic patient; show ownership-scoped data.
5. **Assessment (2 minutes):** Enter height in feet/inches (the app converts and stores centimetres), enter the other basic measurements, explain random-session glucose in mmol/L, select supported Heart v2 categories, confirm measurement contexts, and submit.
6. **Result (60 seconds):** Distinguish DiaBD v3, Heart v2, and the general heuristic fallback. Explain score/threshold without calling it clinical certainty.
7. **Prescription image (45 seconds):** Capture or select an image and show preview/remove behavior.
8. **OCR review (75 seconds):** Extract, optionally reveal raw text, edit candidates, add/remove a medicine, then explicitly confirm.
9. **History (45 seconds):** Show the rolling seven-day saved Heart v2 score summary, its non-heart-attack disclaimer, and the assessment and prescription/medicine tabs.
10. **Engineering summary (45 seconds):** Mention FastAPI ownership controls, artifact hash/contract checks, private images, migrations, and automated tests.

## Validated Android demo environment

- Flutter SDK: `E:\flutter_user_sdk_3.44.6\flutter`
- Physical phone: Xiaomi 24117RN76G (`tanzanite`), Android 15 / API 35, ADB serial `xckr79ovzt69tkhu`
- Tested laptop LAN address: `192.168.0.100`; discover the active address again for each demo and substitute it below instead of committing it to source.
- For a local OTP demo, start the backend from `backend` with `.\venv\Scripts\python.exe run_local_demo.py --capture-otp --host 0.0.0.0 --port 8000`. After phone registration, type `otp` only in that trusted laptop console. Production continues to use the standard uvicorn command with configured SMTP.
- Build the demo APK from `mobile_app` with `E:\flutter_user_sdk_3.44.6\flutter\bin\flutter.bat build apk --debug --no-pub --dart-define=ELDERCARE_API_BASE_URL=http://<DEMO_LAPTOP_IP>:8000`.
- Install with `C:\Users\LENOVO\AppData\Local\Android\Sdk\platform-tools\adb.exe install -r build\app\outputs\flutter-apk\app-debug.apk` and confirm that `adb devices -l` reports the intended phone as `device`.
- The validated debug build uses the compile-time `ELDERCARE_API_BASE_URL`; no laptop-specific address is stored in source. If Wi-Fi/LAN access fails, confirm both devices are on the same trusted network, verify `http://<DEMO_LAPTOP_IP>:8000/docs` from the phone, and allow port 8000 only on the trusted/private firewall profile.
- A release APK can be produced, but the current Android release block uses the debug signing configuration. Treat it as a demo artifact, not a production-signed release.

## Safe fallback plans

- **OCR fails:** Show the friendly failure state, then enter a medicine manually. This is supported behavior, not a bypass.
- **Backend disconnects:** Explain the visible retry state, reconnect to the trusted LAN, and retry. Keep a web/static walkthrough only as secondary evidence.
- **SMTP/SMS unavailable:** Use `run_local_demo.py --capture-otp`, then type `otp` at its terminal prompt after registration. The code remains process-local and is never exposed by an API; never use this launcher in production or show the terminal during screen sharing.
- **Model unavailable/missing input:** Save the assessment with the clearly labelled heuristic demo fallback and explain why the ML call was skipped.
- **Camera issue:** Use gallery selection with the prepared non-private image.
