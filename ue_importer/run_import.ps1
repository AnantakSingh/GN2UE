# Headless GN->UE import: builds the PCG graph from a .gnue.json descriptor
# without opening the editor UI (and without any MCP server).
#
#   powershell -File run_import.ps1 [-Descriptor <path>] [-Project <path>] [-Engine <path>]
#
# Success is judged by the script's "GNUE IMPORT RESULT" line, not the raw exit
# code: unrelated plugins (e.g. the MCP toolset failing to bind port 8000 when
# the interactive editor is open) log errors that force the commandlet exit
# code to 1 even when the import succeeded.

param(
    [string]$Descriptor = (Join-Path $PSScriptRoot "..\export\spinetree.gnue.json"),
    [string]$Project = "",   # path to the .uproject; default from tools/gnue_paths.py
    [string]$Engine = "",    # engine root;            default from tools/gnue_paths.py
    [switch]$DryRun          # print the resolved paths and exit
)

# Defaults come from the resolver (GNUE_* env vars, gnue.config.json, or
# auto-discovery - see PORTABILITY.md). Explicit parameters always win.
$paths = Join-Path (Split-Path -Parent $PSScriptRoot) "tools\gnue_paths.py"
if (-not $Project) {
    $Project = (python $paths uproject)
    if ($LASTEXITCODE -ne 0 -or -not $Project) { Write-Error "cannot resolve the UE project - see PORTABILITY.md"; exit 1 }
}
if (-not $Engine) {
    $env:GNUE_UE_PROJECT = Split-Path -Parent $Project   # key engine discovery on this project
    $Engine = (python $paths engine_root)
    if ($LASTEXITCODE -ne 0 -or -not $Engine) { Write-Error "cannot resolve the engine - see PORTABILITY.md"; exit 1 }
}

$cmd = Join-Path $Engine "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
if ($DryRun) {
    Write-Output "engine     = $Engine"
    Write-Output "uproject   = $Project"
    Write-Output "cmd        = $cmd"
    Write-Output "descriptor = $Descriptor"
    Write-Output "DRY RUN - nothing imported"
    exit 0
}
if (-not (Test-Path $cmd)) { Write-Error "UnrealEditor-Cmd not found: $cmd"; exit 1 }
if (-not (Test-Path $Descriptor)) { Write-Error "Descriptor not found: $Descriptor"; exit 1 }

$script = Join-Path $PSScriptRoot "import_gnue.py"
$logFile = Join-Path $PSScriptRoot "last_run.log"
$env:GNUE_DESCRIPTOR = (Resolve-Path $Descriptor).Path

& $cmd "$Project" -run=pythonscript -script="$script" `
    -stdout -FullStdOutLogOutput -unattended -nosplash -nosound -NoLiveCoding *> $logFile

$result = Select-String -Path $logFile -Pattern "GNUE IMPORT RESULT: (\w+)" |
    Select-Object -Last 1
if ($null -eq $result) {
    Write-Error "Import script did not report a result - see $logFile"
    exit 1
}
$verdict = $result.Matches[0].Groups[1].Value
Select-String -Path $logFile -Pattern "GNUE" | ForEach-Object {
    Write-Output ($_.Line -replace ".*(GNUE)", '$1')
}
if ($verdict -eq "FAIL") { exit 1 }
exit 0
