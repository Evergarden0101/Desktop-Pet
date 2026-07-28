@echo off
REM =====================================================================
REM  Build DesktopPet.exe (and optionally the installer) on Windows.
REM
REM  Usage:
REM     build.bat            Build the standalone DesktopPet.exe
REM     build.bat installer  Also build the Setup installer (needs Inno Setup)
REM
REM  Requirements: Python 3.9+ on PATH. Everything else is installed here.
REM =====================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo [1/5] Creating virtual environment (.venv) ...
if not exist ".venv" (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error

echo.
echo [2/5] Installing dependencies ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || goto :error

echo.
echo [3/5] Generating application icon ...
python packaging\make_icon.py || goto :error

echo.
echo [4/5] Building executable with PyInstaller ...
pyinstaller --noconfirm --clean packaging\DesktopPet.spec || goto :error

echo.
echo   Done.  ->  dist\DesktopPet.exe
echo.

if /I "%1"=="installer" (
    echo [5/5] Building installer with Inno Setup ...
    where iscc >nul 2>nul
    if errorlevel 1 (
        echo   Inno Setup ^(iscc.exe^) not found on PATH.
        echo   Install it from https://jrsoftware.org/isdl.php and re-run:
        echo       build.bat installer
        goto :done
    )
    iscc packaging\installer.iss || goto :error
    echo   Done.  ->  dist\DesktopPet-Setup.exe
) else (
    echo [5/5] Skipping installer ^(run "build.bat installer" to build it^).
)

:done
echo.
echo Build finished successfully.
goto :eof

:error
echo.
echo *** BUILD FAILED (see the message above). ***
exit /b 1
