@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%.venv\Scripts\python.exe" (
  "%ROOT%.venv\Scripts\python.exe" "%ROOT%tools\backup_data.py" %*
) else (
  py -3 "%ROOT%tools\backup_data.py" %*
)
endlocal
