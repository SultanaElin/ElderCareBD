[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ApiBaseUrl
)

$ErrorActionPreference = 'Stop'
$normalizedUrl = $ApiBaseUrl.Trim().TrimEnd('/')

if ([string]::IsNullOrWhiteSpace($normalizedUrl)) {
    throw 'ApiBaseUrl must not be empty.'
}

$parsedUrl = $null
if (-not [Uri]::TryCreate($normalizedUrl, [UriKind]::Absolute, [ref] $parsedUrl)) {
    throw "ApiBaseUrl is malformed: $normalizedUrl"
}

if ($parsedUrl.Scheme -ne 'https') {
    throw 'ApiBaseUrl must use HTTPS for the public-tunnel demo.'
}

if (-not [string]::IsNullOrEmpty($parsedUrl.UserInfo)) {
    throw 'ApiBaseUrl must not contain embedded credentials.'
}

if (-not [string]::IsNullOrEmpty($parsedUrl.Query) -or
    -not [string]::IsNullOrEmpty($parsedUrl.Fragment)) {
    throw 'ApiBaseUrl must not contain a query string or fragment.'
}

$hostName = $parsedUrl.DnsSafeHost.ToLowerInvariant()
$isPrivateHost =
    $hostName -eq 'localhost' -or
    $hostName -eq '0.0.0.0' -or
    $hostName -eq '::1' -or
    $hostName -match '^127\.' -or
    $hostName -match '^10\.' -or
    $hostName -match '^192\.168\.' -or
    $hostName -match '^172\.(1[6-9]|2[0-9]|3[01])\.'

if ($isPrivateHost) {
    throw 'ApiBaseUrl must be a public HTTPS tunnel URL, not a localhost or private-LAN address.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$mobileAppPath = Join-Path $repositoryRoot 'mobile_app'
if (-not (Test-Path -LiteralPath (Join-Path $mobileAppPath 'pubspec.yaml'))) {
    throw "Flutter application was not found at $mobileAppPath."
}

$flutterCommand = Get-Command flutter -ErrorAction SilentlyContinue
$flutterExecutable = if ($null -ne $flutterCommand) {
    $flutterCommand.Source
}
else {
    $null
}

if ([string]::IsNullOrWhiteSpace($flutterExecutable)) {
    $flutterRoot = [Environment]::GetEnvironmentVariable('FLUTTER_ROOT')
    if (-not [string]::IsNullOrWhiteSpace($flutterRoot)) {
        $flutterBat = Join-Path $flutterRoot 'bin\flutter.bat'
        if (Test-Path -LiteralPath $flutterBat) {
            $flutterExecutable = $flutterBat
        }
    }
}

if ([string]::IsNullOrWhiteSpace($flutterExecutable)) {
    throw 'Flutter was not found in PATH. Add Flutter to PATH or set FLUTTER_ROOT, then try again.'
}

Write-Host "Building ElderCareBD debug APK with API base URL: $normalizedUrl" -ForegroundColor Cyan

Push-Location $mobileAppPath
try {
    & $flutterExecutable build apk --debug --no-pub `
        "--dart-define=ELDERCARE_API_BASE_URL=$normalizedUrl"

    if ($LASTEXITCODE -ne 0) {
        throw "Flutter APK build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$apkPath = Join-Path $mobileAppPath 'build\app\outputs\flutter-apk\app-debug.apk'
Write-Host ''
Write-Host 'APK build completed.' -ForegroundColor Green
Write-Host "APK: $apkPath"
