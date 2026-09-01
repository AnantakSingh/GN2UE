# Build the GNueImporter C++ modules (GNueParams + GNuePCG custom PCG node).
# The Unreal editor MUST be closed - Live Coding holds a mutex on the binaries.
#
#   powershell -ExecutionPolicy Bypass -File tools/build_ue_plugin.ps1
#
# GNuePCG is only declared in the .uplugin once its binary exists (a declared
# module with no binary stops the whole plugin loading), so this script declares
# it for the build itself via GNUE_DECLARE_PCG=1.
$ErrorActionPreference = "Stop"
$engine = "C:\Program Files\Epic Games\UE_5.8"
$project = "C:\Users\User\Documents\Unreal Projects\GNtoUE"
$repo = Split-Path -Parent $PSScriptRoot

$editor = Get-Process UnrealEditor -ErrorAction SilentlyContinue
if ($editor) {
    Write-Output "BUILD BLOCKED: close the Unreal editor first (PID $($editor.Id))."
    exit 2
}

$env:GNUE_DECLARE_PCG = "1"
python "$repo\tools\sync_ue_plugin.py" $project
if ($LASTEXITCODE -ne 0) { Write-Output "SYNC FAILED"; exit 1 }

& "$engine\Engine\Build\BatchFiles\Build.bat" GNtoUEEditor Win64 Development `
    -Project="$project\GNtoUE.uproject" -WaitMutex -FromMsBuild
$code = $LASTEXITCODE
$env:GNUE_DECLARE_PCG = $null

$dll = "$project\Plugins\GNueImporter\Binaries\Win64\UnrealEditor-GNuePCG.dll"
if ($code -eq 0 -and (Test-Path $dll)) {
    Write-Output "BUILD OK: GNuePCG built - exact proximity scaling available."
} else {
    # leave the plugin loadable rather than half-declared
    python "$repo\tools\sync_ue_plugin.py" $project | Out-Null
    Write-Output "BUILD FAILED (exit $code) - module left undeclared, plugin still loads."
}
exit $code
