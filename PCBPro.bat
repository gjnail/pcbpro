@echo off
rem PCBPro launcher for running from source on Windows: sets up a private Python environment on first run, then
rem opens the app. The Windows download (PCBPro.exe) needs none of this.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up PCBPro for the first time. This downloads close to 1 GB and takes a few minutes...
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
    if errorlevel 1 (
        echo Python 3.10 or newer is required: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installing the dependencies failed. See the messages above.
        pause
        exit /b 1
    )
)
start "" ".venv\Scripts\pythonw.exe" -m pcbpro %*
