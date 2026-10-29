# Builds dist\installer\3DScanPostProcessor_Setup.exe
#   1. PyInstaller -> dist\3DScanPostProcessor\ (GUI + CLI exe)
#   2. optional code signing of the exes (set $env:SIGN_CERT_THUMBPRINT)
#   3. Inno Setup -> installer exe (signed too when a certificate is given)
# Usage:  powershell -ExecutionPolicy Bypass -File build_installer.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

& .venv\Scripts\pyinstaller.exe 3d_scan_post_processor.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$thumb = $env:SIGN_CERT_THUMBPRINT
function Sign($files) {
    if (-not $thumb) { return }
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
        Sort-Object FullName -Descending | Select-Object -First 1
    & $signtool.FullName sign /sha1 $thumb /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $files
    if ($LASTEXITCODE -ne 0) { throw "signing failed" }
}
Sign @("dist\3DScanPostProcessor\3DScanPostProcessor.exe", "dist\3DScanPostProcessor\3DScanPostProcessorCLI.exe")

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
& $iscc installer\3DScanPostProcessor.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Sign (Get-ChildItem dist\installer\*.exe | ForEach-Object FullName)
Get-ChildItem dist\installer\*.exe | Select-Object Name, @{n="MB"; e={[math]::Round($_.Length / 1MB)}}
