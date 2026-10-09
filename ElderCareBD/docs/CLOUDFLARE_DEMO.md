# Cloudflare Quick Tunnel Demo

This workflow exposes the laptop-hosted ElderCareBD development backend through a temporary public HTTPS URL. It is intended only for development and demonstrations with synthetic data.

## 1. Install cloudflared once

Open PowerShell and run:

```powershell
winget install --id Cloudflare.cloudflared
```

Open a new PowerShell window after installation and confirm that `cloudflared --version` works. A Cloudflare account or domain is not required for a Quick Tunnel.

If `winget` is unavailable and the portable executable is installed under the
current user's local programs directory, add it to each new PowerShell session
before running the tunnel helper:

```powershell
$cfDir = Join-Path $env:LOCALAPPDATA 'Programs\cloudflared'
$env:Path = "$cfDir;$env:Path"
cloudflared --version
```

## 2. Start the local backend

From the repository root:

```powershell
cd backend
.\venv\Scripts\python.exe .\run_local_demo.py --capture-otp --host 127.0.0.1 --port 8000
```

Binding to `127.0.0.1` keeps the development backend accessible only from the laptop and the local tunnel connector.

Keep this PowerShell window running. Development OTP values remain available only through the local capture-provider console; they are not returned by an HTTP API.

## 3. Verify the backend locally

Open the following URL on the laptop:

```text
http://127.0.0.1:8000/docs
```

## 4. Start the Quick Tunnel

From the repository root, run the helper:

```powershell
.\scripts\start_cloudflare_demo.ps1
```

The equivalent direct command is:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Keep this PowerShell window running. Copy the generated URL resembling:

```text
https://random-name.trycloudflare.com
```

Open that HTTPS URL in a browser before building the APK and confirm that the backend responds.

## 5. Build the demo APK

From the repository root, substitute the URL printed by `cloudflared`:

```powershell
.\scripts\build_demo_apk.ps1 -ApiBaseUrl "https://random-name.trycloudflare.com"
```

The helper requires a public HTTPS URL, removes a trailing slash, rejects localhost and private-LAN addresses, and builds with:

```text
--dart-define=ELDERCARE_API_BASE_URL=https://random-name.trycloudflare.com
```

The generated APK is located at:

```text
mobile_app\build\app\outputs\flutter-apk\app-debug.apk
```

Transfer and install this APK on the Redmi phone. Do not commit the generated APK.

## 6. Physical Android acceptance

Use only synthetic/de-identified demonstration data.

- [ ] Local backend is running on `127.0.0.1:8000`.
- [ ] `cloudflared` is running and displays the public HTTPS URL.
- [ ] The public URL opens in the phone browser.
- [ ] The APK can register or log in and the request reaches the backend.
- [ ] OTP verification works using the local capture-provider console.
- [ ] The app reaches the backend while the phone uses Wi-Fi.
- [ ] After switching the phone to mobile data, the app still reaches the backend.
- [ ] At least one authenticated API action succeeds after the network switch.
- [ ] No real patient health information is used.

## 7. Restart runbook

Use two PowerShell windows: one for the backend and one for `cloudflared`.

### Restart only the backend

If the Quick Tunnel window is still running, its public URL has not changed and
the installed APK does not need to be rebuilt.

1. In the backend console, enter `quit` to stop it cleanly. `Ctrl+C` can be used
   if the console is not accepting commands.
2. In the same or a new PowerShell window, run:

```powershell
Set-Location -LiteralPath 'E:\Project Software Engineer\8th Semester\SPL-3\ElderCareBD\backend'

$env:ELDERCARE_ENVIRONMENT = 'development'
$env:ELDERCARE_OTP_DELIVERY_MODE = 'capture'

.\venv\Scripts\python.exe .\run_local_demo.py --capture-otp --host 127.0.0.1 --port 8000
```

3. Keep the backend window open and verify from another PowerShell window:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/ -UseBasicParsing
```

The expected status is HTTP `200`. Outstanding local-demo OTPs are invalidated
when the backend restarts because the process-local secret and capture state are
new. Request/resend a new OTP and enter `otp` in the backend console when needed.

### Restart the laptop or both backend and tunnel

A Quick Tunnel normally receives a different URL after `cloudflared` restarts.
The APK must be rebuilt and reinstalled when that happens.

1. Start and verify the backend using the commands above.
2. Open a second PowerShell window and run:

```powershell
$cfDir = Join-Path $env:LOCALAPPDATA 'Programs\cloudflared'
$env:Path = "$cfDir;$env:Path"

Set-Location -LiteralPath 'E:\Project Software Engineer\8th Semester\SPL-3\ElderCareBD'
.\scripts\start_cloudflare_demo.ps1
```

3. Keep the tunnel window open. Copy the newly generated URL:

```text
https://NEW-RANDOM-NAME.trycloudflare.com
```

4. Open the new URL in a browser and confirm the backend responds.
5. In a third PowerShell window, build the APK with the new URL:

```powershell
Set-Location -LiteralPath 'E:\Project Software Engineer\8th Semester\SPL-3\ElderCareBD'
$env:FLUTTER_ROOT = 'E:\flutter_user_sdk_3.44.6\flutter'

.\scripts\build_demo_apk.ps1 -ApiBaseUrl 'https://NEW-RANDOM-NAME.trycloudflare.com'
```

6. With USB debugging enabled, reinstall the APK:

```powershell
$adb = 'C:\Users\LENOVO\AppData\Local\Android\Sdk\platform-tools\adb.exe'
$apk = '.\mobile_app\build\app\outputs\flutter-apk\app-debug.apk'

& $adb devices
& $adb install -r $apk
```

7. Keep both backend and tunnel windows open while using the app. Verify the
   public URL and one authenticated action before the demonstration.

### Quick troubleshooting

- `Unable to connect to the remote server`: start the backend first and verify
  `http://127.0.0.1:8000/`.
- `cloudflared was not found in PATH`: add the portable installation directory
  to `$env:Path` using the command above.
- `502 Bad Gateway` from the tunnel: the tunnel is running but the local backend
  is stopped or is not bound to `127.0.0.1:8000`.
- App timeout after restarting `cloudflared`: the tunnel URL changed; rebuild and
  reinstall the APK with the new URL.

## Limitations and security

- Quick Tunnel is for development and demonstrations only. It is not the final production deployment architecture.
- The random URL usually changes whenever `cloudflared` restarts.
- When the URL changes, an APK built with the previous URL must be rebuilt.
- The laptop must remain powered on and awake.
- The backend process and `cloudflared` must remain running.
- Laptop sleep or loss of internet connectivity interrupts the demo.
- The phone requires internet connectivity to reach Cloudflare.
- Anyone who learns the temporary URL can reach the public API surface, so existing authentication must remain enabled.
- Never expose OTP capture values, OTP/HMAC secrets, SMTP credentials, database files, prescription image directories, or environment secrets.
- Do not add debug filesystem or OTP-disclosure endpoints.
- Use synthetic/de-identified patient data only.
