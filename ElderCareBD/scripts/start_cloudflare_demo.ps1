[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$backendUrl = 'http://127.0.0.1:8000'

$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($null -eq $cloudflared) {
    Write-Error @'
cloudflared was not found in PATH.
Install it once with:
  winget install --id Cloudflare.cloudflared
Then open a new PowerShell window and run this script again.
'@
}

try {
    $response = Invoke-WebRequest `
        -Uri "$backendUrl/" `
        -UseBasicParsing `
        -TimeoutSec 5

    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
        throw "Backend returned HTTP $($response.StatusCode)."
    }
}
catch {
    Write-Error @"
The ElderCareBD backend did not respond at $backendUrl.

Start it in another PowerShell window first:
  cd backend
  .\venv\Scripts\python.exe .\run_local_demo.py --capture-otp --host 127.0.0.1 --port 8000

Details: $($_.Exception.Message)
"@
}

Write-Host ''
Write-Host 'Local backend check passed.' -ForegroundColor Green
Write-Host 'Starting a Cloudflare Quick Tunnel...' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Copy the generated https://*.trycloudflare.com URL shown below.' -ForegroundColor Yellow
Write-Host 'Keep this PowerShell window, cloudflared, and the backend running.' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Then build the APK from the repository root with:' -ForegroundColor Cyan
Write-Host '  .\scripts\build_demo_apk.ps1 -ApiBaseUrl "https://YOUR-TUNNEL.trycloudflare.com"'
Write-Host ''

& $cloudflared.Source tunnel --url $backendUrl
if ($LASTEXITCODE -ne 0) {
    throw "cloudflared exited with code $LASTEXITCODE."
}
