@echo off
rem Rebuilds dist\VerseForge\VerseForge.exe and the installer dist\VerseForge-<version>-Setup.exe
title Build VerseForge
cd /d "%~dp0"
python -m pip show pyinstaller >nul 2>nul || python -m pip install pyinstaller
python -m PyInstaller VerseForge.spec --noconfirm --workpath build --distpath dist || (echo PyInstaller build failed & pause & exit /b 1)
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ISCC%" (
  "%ISCC%" /Q installer\VerseForge.iss && echo Installer created in dist\
) else (
  echo Inno Setup not found: only dist\VerseForge\VerseForge.exe was created
)
pause
