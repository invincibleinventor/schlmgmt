@echo off
setlocal
cd /d "%~dp0\.."

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher was not found. Install Python 3.8.10 first.
  exit /b 1
)

if not exist ".venv-win\Scripts\python.exe" (
  py -3.8 -m venv .venv-win
  if errorlevel 1 exit /b 1
)

call ".venv-win\Scripts\activate.bat"
python -m pip install --upgrade "pip<24.1"
if errorlevel 1 exit /b 1
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

python -m PyInstaller --noconfirm --clean --windowed --name "TVS Activity Desk" --collect-all openpyxl app.py
if errorlevel 1 exit /b 1

set "INNO_COMPILER=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%INNO_COMPILER%" set "INNO_COMPILER=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%INNO_COMPILER%" (
  echo.
  echo Application build complete: dist\TVS Activity Desk
  echo Inno Setup 6 was not found, so the installer was not compiled.
  exit /b 0
)

"%INNO_COMPILER%" "windows\TVSActivityDesk.iss"
if errorlevel 1 exit /b 1

echo.
echo Installer complete: dist\installer\TVS-Activity-Desk-Setup.exe
endlocal


