@echo off
rem Launch the metacheck app.
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  where python3 >nul 2>nul
  if %ERRORLEVEL%==0 (set "BASEPY=python3") else (set "BASEPY=python")
  %BASEPY% -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo Starting metacheck app at http://127.0.0.1:8000
"%PY%" -m uvicorn app:app --host 127.0.0.1 --port 8000
