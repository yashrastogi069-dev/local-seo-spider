@echo off
setlocal

where python >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 is required. Install Python 3.12 and rerun this command.
  exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 is required. The current python command is not Python 3.12.
  exit /b 1
)

if not exist .venv (
  python -m venv .venv
  if errorlevel 1 exit /b 1
)

if not exist .env (
  copy /Y local-seo-spider.env.example .env >nul
  echo Created local .env from the checked-in configuration template.
)

.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -e ".[dev]"
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 exit /b 1

if not defined PORT set PORT=3000
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%
