@echo off
rem Washing-text web workbench launcher (keep ASCII only)
cd /d "%~dp0"
if not exist logs mkdir logs

rem avoid a second instance fighting for port 8777
netstat -ano | findstr ":8777" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [%date% %time%] port 8777 already in use, skip start >> logs\web.log
  exit /b 0
)

echo [%date% %time%] starting web workbench >> logs\web.log
.venv\Scripts\python.exe web\app.py >> logs\web.log 2>&1
echo [%date% %time%] web workbench exited with code %errorlevel% >> logs\web.log
