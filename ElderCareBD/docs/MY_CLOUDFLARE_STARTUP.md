# আমার ElderCareBD চালুর নিয়ম

এই file শুধু আমার নিজের local demo চালানোর জন্য। প্রতিবার laptop restart হলে নিচের ধাপগুলো অনুসরণ করব।

## Terminal 1 — Backend চালু করব

একটি নতুন PowerShell খুলে:

```powershell
Set-Location -LiteralPath 'E:\Project Software Engineer\8th Semester\SPL-3\ElderCareBD\backend'

$env:ELDERCARE_ENVIRONMENT = 'development'
$env:ELDERCARE_OTP_DELIVERY_MODE = 'capture'

.\venv\Scripts\python.exe .\run_local_demo.py --capture-otp --host 127.0.0.1 --port 8000
```

এটি দেখালে backend ঠিক আছে:

```text
Uvicorn running on http://127.0.0.1:8000
eldercare-demo>
```

এই terminal বন্ধ করব না। OTP দরকার হলে এই terminal-এ লিখব:

```text
otp
```

## Terminal 2 — Cloudflare Tunnel চালু করব

আরেকটি নতুন PowerShell খুলে:

```powershell
$cfDir = Join-Path $env:LOCALAPPDATA 'Programs\cloudflared'
$env:Path = "$cfDir;$env:Path"

Set-Location -LiteralPath 'E:\Project Software Engineer\8th Semester\SPL-3\ElderCareBD'

.\scripts\start_cloudflare_demo.ps1
```

Output থেকে এই ধরনের নতুন URL copy করব:

```text
https://NEW-RANDOM-NAME.trycloudflare.com
```

এই terminal-ও বন্ধ করব না।

## Terminal 3 — নতুন URL দিয়ে APK বানাব

Tunnel restart হলে URL বদলে যায়। তখন নতুন URL বসিয়ে APK আবার বানাব:

```powershell
Set-Location -LiteralPath 'E:\Project Software Engineer\8th Semester\SPL-3\ElderCareBD'

$env:FLUTTER_ROOT = 'E:\flutter_user_sdk_3.44.6\flutter'

.\scripts\build_demo_apk.ps1 -ApiBaseUrl 'https://NEW-RANDOM-NAME.trycloudflare.com'
```

APK থাকবে:

```text
mobile_app\build\app\outputs\flutter-apk\app-debug.apk
```

## USB দিয়ে Redmi-তে install করব

```powershell
$adb = 'C:\Users\LENOVO\AppData\Local\Android\Sdk\platform-tools\adb.exe'
$apk = '.\mobile_app\build\app\outputs\flutter-apk\app-debug.apk'

& $adb devices
& $adb install -r $apk
```

শেষে `Success` দেখালে install হয়েছে।

## খুব গুরুত্বপূর্ণ

- শুধু backend restart করলে, Tunnel terminal চালু থাকলে APK আবার build করতে হবে না।
- Cloudflare Tunnel restart হলে নতুন URL আসবে; তখন APK আবার build ও install করতে হবে।
- App ব্যবহারের সময় Backend এবং Tunnel—দুই terminal-ই চালু রাখতে হবে।
- Laptop sleep করলে app কাজ নাও করতে পারে।
- Registration-এর পর OTP নিতে Backend terminal-এ `otp` লিখব।
- শুধুমাত্র synthetic/demo patient data ব্যবহার করব।

## সমস্যা হলে

Backend পরীক্ষা:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/ -UseBasicParsing
```

`StatusCode: 200` পাওয়া উচিত।

- `Unable to connect`: Backend চালু নেই।
- `502 Bad Gateway`: Tunnel চলছে, কিন্তু Backend বন্ধ।
- App timeout: Tunnel URL বদলেছে; নতুন URL দিয়ে APK rebuild করতে হবে।
- `cloudflared not found`: Terminal 2-এর `$cfDir` ও `$env:Path` commands আবার চালাতে হবে।

## বন্ধ করার নিয়ম

- Backend terminal-এ `quit` লিখব।
- Tunnel terminal-এ `Ctrl+C` চাপব।
