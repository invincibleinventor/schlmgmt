@echo off
setlocal EnableExtensions
title TVS Activity Desk - Windows 7-10 Release Builder
cd /d "%~dp0\.."

echo.
echo ============================================================
echo   TVS Activity Desk - Windows 7-10 installer builder
echo ============================================================
echo.

if defined TVS_PYTHON (
  set "PYTHON_EXE=%TVS_PYTHON%"
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python launcher was not found.
    echo Install 32-bit Python 3.8.10 and select "Install launcher".
    goto :failed
  )
  for /f "delims=" %%P in ('py -3.8-32 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE goto :wrongpython
"%PYTHON_EXE%" -c "import sys,struct; assert sys.version_info[:2] == (3,8) and struct.calcsize('P') == 4" >nul 2>nul
if errorlevel 1 goto :wrongpython

if not exist ".venv-win32\Scripts\python.exe" (
  echo Creating the isolated build environment...
  "%PYTHON_EXE%" -m venv .venv-win32
  if errorlevel 1 goto :failed
)

call ".venv-win32\Scripts\activate.bat"
python -c "import sys,struct; assert sys.version_info[:2] == (3,8) and struct.calcsize('P') == 4"
if errorlevel 1 (
  echo ERROR: The existing .venv-win32 environment has the wrong Python.
  echo Delete only .venv-win32 and run this builder again.
  goto :failed
)

echo Installing pinned build dependencies...
python -m pip install --upgrade "pip<24.1"
if errorlevel 1 goto :failed
python -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo Running automated tests...
python -m unittest discover -q
if errorlevel 1 goto :failed

echo Creating application icon...
powershell -NoProfile -ExecutionPolicy Bypass -File "windows\make_icon.ps1" -OutputPath "%CD%\build\assets\tvs.ico"
if errorlevel 1 goto :failed

echo Building the self-contained application...
python -m PyInstaller --noconfirm --clean --windowed --noupx ^
  --name "TVS Activity Desk" ^
  --icon "build\assets\tvs.ico" ^
  --version-file "windows\version_info.txt" ^
  --collect-all openpyxl ^
  app.py
if errorlevel 1 goto :failed

if not exist "dist\TVS Activity Desk\TVS Activity Desk.exe" (
  echo ERROR: Packaged application was not created.
  goto :failed
)

echo Checking the packaged database and encryption runtime...
start "" /wait "dist\TVS Activity Desk\TVS Activity Desk.exe" --package-check
if errorlevel 1 (
  echo ERROR: The packaged application self-check failed.
  goto :failed
)

set "INNO_COMPILER=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%INNO_COMPILER%" set "INNO_COMPILER=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%INNO_COMPILER%" set "INNO_COMPILER=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not exist "%INNO_COMPILER%" set "INNO_COMPILER=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not exist "%INNO_COMPILER%" (
  echo ERROR: Inno Setup 6 was not found.
  echo Install Inno Setup 6, then run this builder again.
  goto :failed
)

echo Compiling the teacher-friendly installer...
"%INNO_COMPILER%" "windows\TVSActivityDesk.iss"
if errorlevel 1 goto :failed

set "INSTALLER=dist\installer\TVS-Activity-Desk-Setup.exe"
if not exist "%INSTALLER%" goto :failed
certutil -hashfile "%INSTALLER%" SHA256 > "%INSTALLER%.sha256.txt"

echo.
echo ============================================================
echo   SUCCESS
echo   Give teachers this one file only:
echo   %INSTALLER%
echo ============================================================
echo.
if defined CI goto :success
explorer /select,"%CD%\%INSTALLER%"
pause
:success
endlocal
exit /b 0

:wrongpython
echo ERROR: 32-bit Python 3.8.10 is required for the universal
echo Windows 7-10 package. It was not found by the Python launcher.
goto :failed

:failed
echo.
echo BUILD FAILED. Read the message above. No incomplete installer
echo should be distributed.
echo.
if defined CI goto :failedexit
pause
:failedexit
endlocal
exit /b 1
