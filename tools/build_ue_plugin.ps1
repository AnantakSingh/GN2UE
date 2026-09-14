# Build the GNueImporter C++ modules (GNueParams + GNuePCG custom PCG node).
# The Unreal editor MUST be closed - Live Coding holds a mutex on the binaries.
#
#   powershell -ExecutionPolicy Bypass -File tools/build_ue_plugin.ps1 [-Engine <dir>] [-Project <dir>] [-DryRun]
#
# Engine and project default to tools/gnue_paths.py (GNUE_* env vars,
# gnue.config.json, or auto-discovery - see PORTABILITY.md). The UBT target is
# derived from the .uproject's name, never hardcoded, so a project that isn't
# called GNtoUE builds correctly. -DryRun prints what would be built and exits.
#
# GNuePCG is only declared in the .uplugin once its binary exists (a declared
# module with no binary stops the whole plugin loading), so this script declares
# it for the build itself via GNUE_DECLARE_PCG=1.
param(
    [string]$Engine = "",
    [string]$Project = "",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$paths = Join-Path $repo "tools\gnue_paths.py"

if (-not $Project) {
    $Project = (python $paths ue_project)
    if ($LASTEXITCODE -ne 0 -or -not $Project) { Write-Output "cannot resolve the UE project - see PORTABILITY.md"; exit 1 }
}
$uproject = Get-ChildItem -Path $Project -Filter *.uproject -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $uproject) { Write-Output "no .uproject found in $Project"; exit 1 }
$target = $uproject.BaseName + "Editor"

if (-not $Engine) {
    $env:GNUE_UE_PROJECT = $Project      # key engine discovery on THIS project's EngineAssociation
    $Engine = (python $paths engine_root)
    if ($LASTEXITCODE -ne 0 -or -not $Engine) { Write-Output "cannot resolve the engine - see PORTABILITY.md"; exit 1 }
}
$buildBat = Join-Path $Engine "Engine\Build\BatchFiles\Build.bat"
if (-not (Test-Path $buildBat)) { Write-Output "Build.bat not found under $Engine"; exit 1 }

if ($DryRun) {
    Write-Output "engine   = $Engine"
    Write-Output "project  = $Project"
    Write-Output "uproject = $($uproject.FullName)"
    Write-Output "target   = $target"
    Write-Output "DRY RUN - nothing built"
    exit 0
}

$editor = Get-Process UnrealEditor -ErrorAction SilentlyContinue
if ($editor) {
    Write-Output "BUILD BLOCKED: close the Unreal editor first (PID $($editor.Id))."
    exit 2
}

$env:GNUE_DECLARE_PCG = "1"
python "$repo\tools\sync_ue_plugin.py" $Project
if ($LASTEXITCODE -ne 0) { Write-Output "SYNC FAILED"; exit 1 }

& $buildBat $target Win64 Development `
    -Project="$($uproject.FullName)" -WaitMutex -FromMsBuild
$code = $LASTEXITCODE
$env:GNUE_DECLARE_PCG = $null

$dll = Join-Path $Project "Plugins\GNueImporter\Binaries\Win64\UnrealEditor-GNuePCG.dll"
if ($code -eq 0 -and (Test-Path $dll)) {
    Write-Output "BUILD OK: GNuePCG built - exact proximity scaling available."
} else {
    # leave the plugin loadable rather than half-declared
    python "$repo\tools\sync_ue_plugin.py" $Project | Out-Null
    Write-Output "BUILD FAILED (exit $code) - module left undeclared, plugin still loads."
}
exit $code
