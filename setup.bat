@echo off
REM One-time setup: build a local venv and install numpy + OpenImageIO.
setlocal
cd /d "%~dp0"

echo Creating virtual environment...
python -m venv .venv || goto :fail

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet || goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet || goto :fail

where ffmpeg >nul 2>&1 || echo WARNING: ffmpeg is not on PATH. Install it with: winget install Gyan.FFmpeg
where exiftool >nul 2>&1 || echo NOTE: exiftool is not on PATH. Canon Log auto-detection will be skipped.

echo.
echo Setup complete. Launch the tool with run.bat
pause
exit /b 0

:fail
echo.
echo Setup FAILED. Check that Python 3.10+ is installed and on PATH.
pause
exit /b 1
