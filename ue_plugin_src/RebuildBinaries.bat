@echo off
setlocal EnableDelayedExpansion
rem ============================================================
rem  GNue Importer - rebuild the plugin's C++ binaries for YOUR
rem  engine build. Run this if the editor says:
rem    "Plugin 'GNueImporter' failed to load because module
rem     'GNueParams'/'GNuePCG' could not be loaded"
rem  or "modules ... built with a different engine version".
rem  Requires: Visual Studio 2022 with the "Game development
rem  with C++" workload installed.
rem ============================================================

set ENGINE=
for /f "tokens=2,*" %%a in ('reg query "HKLM\SOFTWARE\EpicGames\Unreal Engine\5.8" /v InstalledDirectory 2^>nul ^| find "InstalledDirectory"') do set ENGINE=%%b
if "%ENGINE%"=="" if exist "C:\Program Files\Epic Games\UE_5.8" set ENGINE=C:\Program Files\Epic Games\UE_5.8
if "%ENGINE%"=="" (
    echo Could not find Unreal Engine 5.8. Edit this file and set ENGINE= to your engine folder.
    pause
    exit /b 1
)
echo Engine: %ENGINE%
echo Plugin: %~dp0GNueImporter.uplugin

set OUT=%TEMP%\GNueRebuild
if exist "%OUT%" rmdir /s /q "%OUT%"

call "%ENGINE%\Engine\Build\BatchFiles\RunUAT.bat" BuildPlugin -Plugin="%~dp0GNueImporter.uplugin" -Package="%OUT%" -TargetPlatforms=Win64 -Rocket
if errorlevel 1 (
    echo.
    echo BUILD FAILED. Most common cause: Visual Studio 2022 with the
    echo "Game development with C++" workload is not installed.
    pause
    exit /b 1
)

echo Copying fresh binaries into the plugin...
xcopy /e /y /i "%OUT%\Binaries" "%~dp0Binaries" >nul
echo.
echo Done. Start the editor again - the plugin will now load.
pause
