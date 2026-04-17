@echo off
setlocal EnableDelayedExpansion

REM meeting-hive CLI wrapper (Windows — cmd / PowerShell via PATHEXT).
REM Activates the package's venv and invokes it. Sources secrets.env so
REM API keys show up as environment variables for the Python process.

REM Resolve repo directory from this script's location.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO=%%~fI"

set "VENV=%REPO%\.venv"

REM Config dir: XDG_CONFIG_HOME wins, else %APPDATA%\meeting-hive.
if defined XDG_CONFIG_HOME (
    set "CONFIG_DIR=%XDG_CONFIG_HOME%\meeting-hive"
) else (
    set "CONFIG_DIR=%APPDATA%\meeting-hive"
)
set "SECRETS=%CONFIG_DIR%\secrets.env"

REM Load secrets (KEY=value lines; skip comments and blanks).
if exist "%SECRETS%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%SECRETS%") do (
        if not "%%A"=="" set "%%A=%%B"
    )
)

REM Bootstrap venv on first run.
if not exist "%VENV%\Scripts\python.exe" (
    echo [meeting-hive] bootstrapping venv at %VENV% 1>&2
    where python >nul 2>&1
    if errorlevel 1 (
        echo [meeting-hive] ERROR: Python not found on PATH. Install Python 3.11+ from https://www.python.org/downloads/windows/ 1>&2
        exit /b 1
    )
    python -m venv "%VENV%" || (
        echo [meeting-hive] ERROR: failed to create venv 1>&2
        exit /b 1
    )
    "%VENV%\Scripts\pip.exe" install --quiet --upgrade pip
    "%VENV%\Scripts\pip.exe" install --quiet -e "%REPO%"
)

"%VENV%\Scripts\python.exe" -m meeting_hive %*
exit /b %ERRORLEVEL%
