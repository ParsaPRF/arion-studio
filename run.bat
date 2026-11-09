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

rem --- 3) venv + dependencies ------------------------------------------------
if not exist venv (
    echo Creating virtual environment...
    %PYCMD% -m venv venv || (echo   venv creation failed & pause & exit /b 1)
)

call venv\Scripts\activate.bat

if exist venv\.deps_ok goto deps_done

echo Installing python dependencies...
pip install --disable-pip-version-check -r requirements.txt
if not errorlevel 1 goto deps_mark

echo   Primary PyPI unreachable - trying the runflare mirror...
pip install --disable-pip-version-check -i https://mirror-pypi.runflare.com/simple -r requirements.txt
if errorlevel 1 (
    echo   Dependency install failed. Check your internet connection.
    pause
    exit /b 1
)

:deps_mark
echo done > venv\.deps_ok

:deps_done
rem --- 4) run ---------------------------------------------------------------
python main.py
