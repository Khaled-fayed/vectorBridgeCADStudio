$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($null -eq $compiler) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            $compiler = Get-Item -LiteralPath $candidate
            break
        }
    }
}

if ($null -eq $compiler) {
    throw 'Inno Setup 6 is required. Install JRSoftware.InnoSetup, then rerun this script.'
}
$compilerPath = $compiler.Source
if ([string]::IsNullOrWhiteSpace($compilerPath)) {
    $compilerPath = $compiler.FullName
}

$executable = Join-Path $root 'dist\VectorBridgeCADStudio.exe'
$icon = Join-Path $root 'assets\vectorBridge_icon.ico'
$script = Join-Path $root 'installer.iss'
foreach ($requiredFile in @($executable, $icon, $script)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required installer input is missing: $requiredFile"
    }
}

Push-Location $root
try {
    & $compilerPath $script
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compiler failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$setup = Join-Path $root 'dist\VectorBridgeCADStudio-Setup.exe'
if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) {
    throw "Installer output was not created: $setup"
}
Get-Item -LiteralPath $setup | Select-Object FullName, Length
