@echo off
rem ============================================================
rem  Arion Studio — Windows auto-installer / launcher
rem  Creates the venv, installs dependencies (with a regional
rem  PyPI mirror fallback) and runs the app.
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

rem --- 1) find the Python launcher ----------------------------------------
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py"
if not defined PYCMD where python >nul 2>nul && set "PYCMD=python"

if not defined PYCMD (
    echo Installing Python 3.12 via winget...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo.
        echo   Python was not installed automatically.
        echo   Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^) and re-run run.bat
        pause
        exit /b 1
    )
    rem after winget, PATH needs a fresh console in some cases
    where py >nul 2>nul && set "PYCMD=py"
    if not defined PYCMD where python >nul 2>nul && set "PYCMD=python"
    if not defined PYCMD (
        echo   Python installed but PATH not refreshed yet.
        echo   Please close this window and run run.bat again.
        pause
        exit /b 1
    )
)

rem --- 2) ffmpeg check (non-fatal warning) ---------------------------------
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo.
    echo   ^[!] ffmpeg not found on PATH. The app can start but audio/video
    echo       jobs will fail. Install it with:
    echo           winget install Gyan.FFmpeg
    echo.
)

rem --- 3) venv --------------------------------------------------------------
rem A half-created venv (no python.exe) would break every later step, so
rem rebuild it instead of failing with a confusing error.
if exist venv if not exist "venv\Scripts\python.exe" (
    echo   Existing venv is incomplete - rebuilding it...
    rmdir /s /q venv
)
if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYCMD% -m venv venv
    if errorlevel 1 (
        echo   venv creation failed.
        pause
        exit /b 1
    )
)

set "VPY=venv\Scripts\python.exe"

"%VPY%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo   Bootstrapping pip in the virtual environment...
    "%VPY%" -m ensurepip --upgrade
)

rem --- 4) dependencies ------------------------------------------------------
rem The marker alone is not trusted: a requirements change or a half-finished
rem install must not be mistaken for a working environment.
if exist "venv\.deps_ok" (
    "%VPY%" -c "import customtkinter, dotenv, requests, yt_dlp" >nul 2>nul
    if not errorlevel 1 goto deps_done
    echo   Existing packages are incomplete - reinstalling dependencies...
)

rem pip writes to %LOCALAPPDATA%\pip\Cache and to %TEMP%. When either is locked
rem (antivirus, OneDrive-redirected AppData, a stale cache, a restricted
rem profile) pip can block forever without printing anything - the "Installing
rem python dependencies..." hang. Keep every temp file inside the app folder
rem and disable the HTTP cache.
if not exist ".tmp" mkdir ".tmp"
set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"
set "TMPDIR=%~dp0.tmp"
set "PIP_NO_CACHE_DIR=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_NO_INPUT=1"
set "PIP_DEFAULT_TIMEOUT=20"

echo Installing python dependencies...
echo   About 5 MB to download; on a slow connection this can take a few minutes.
echo.
"%VPY%" -m pip install --no-cache-dir --disable-pip-version-check --no-input --prefer-binary --timeout 20 --retries 2 -r requirements.txt
if not errorlevel 1 goto deps_verify

echo.
echo   Primary PyPI failed or was too slow - trying the runflare mirror...
"%VPY%" -m pip install --no-cache-dir --disable-pip-version-check --no-input --prefer-binary --timeout 20 --retries 2 -i https://mirror-pypi.runflare.com/simple -r requirements.txt
if errorlevel 1 (
    echo.
    echo   Dependency install failed. Check your internet connection, then retry:
    echo       venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
    echo   If that hangs too, add:  --timeout 20 --retries 2
    pause
    exit /b 1
)

:deps_verify
"%VPY%" -c "import customtkinter, dotenv, requests, yt_dlp" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Dependencies were installed but cannot be imported.
    echo   Please report this with the output above.
    pause
    exit /b 1
)
echo done > "venv\.deps_ok"

:deps_done
rem --- 5) run ---------------------------------------------------------------
if defined ARION_NO_LAUNCH (
    echo Dependencies are ready. ARION_NO_LAUNCH is set, so the app is not started.
    exit /b 0
)
echo Starting Arion Studio...
"%VPY%" main.py