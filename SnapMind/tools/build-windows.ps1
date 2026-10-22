$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw 'Build requires Windows x64.' }
py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required on the build machine.' }
$Python = Join-Path $PWD '.venv\Scripts\python.exe'
& $Python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$env:QT_QPA_PLATFORM = 'offscreen'
& $Python -m pytest -q --junitxml=docs/test-results-windows.xml
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; packaging stopped.' }
Remove-Item Env:QT_QPA_PLATFORM
& $Python -m tools.build --target windows
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
$SmokeData = Join-Path ([System.IO.Path]::GetTempPath()) ('SnapMind-package-smoke-' + [guid]::NewGuid().ToString())
$env:QT_QPA_PLATFORM = 'offscreen'
function Invoke-SnapMindCheck([string[]]$CheckArguments) {
    $SnapMindProcess = Start-Process -FilePath '.\dist\SnapMind\SnapMind.exe' -ArgumentList $CheckArguments -PassThru
    if (-not $SnapMindProcess.WaitForExit(60000)) {
        $SnapMindProcess.Kill()
        throw 'Packaged executable timed out after 60 seconds.'
    }
    if ($SnapMindProcess.ExitCode -ne 0) { throw 'Packaged executable check failed.' }
}
try {
    Invoke-SnapMindCheck -CheckArguments @('--smoke', '--data-dir', ('"' + $SmokeData + '"'))
    $Fixture = Join-Path $PWD 'tests\fixtures\technical-text.png'
    Invoke-SnapMindCheck -CheckArguments @('--verify-ocr', ('"' + $Fixture + '"'), '--data-dir', ('"' + $SmokeData + '"'))
    & $Python -m tools.check_ocr_database (Join-Path $SmokeData 'data\app.db')
    if ($LASTEXITCODE -ne 0) { throw 'Packaged EXE did not persist expected OCR output.' }
} finally {
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    if (Test-Path $SmokeData) { Remove-Item -Recurse -Force $SmokeData }
}
Write-Host 'Portable package: dist\SnapMind-0.1.0-Windows-x64.zip'
Write-Host 'Native hotkeys, multi-monitor DPI and tray behavior still require interactive Windows acceptance.'
