@echo off
rem Quick launcher for Arion Studio (Windows)
cd /d "%~dp0"
if not exist venv (
  echo Creating virtual environment...
  python -m venv venv || py -m venv venv
)
call venv\Scripts\activate.bat
pip show customtkinter >nul 2>&1 || pip install -r requirements.txt
python main.py
