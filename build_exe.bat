@echo off
rem Ricostruisce dist\VerseForge\VerseForge.exe e l'installer dist\VerseForge-<versione>-Setup.exe
title Build VerseForge
cd /d "%~dp0"
python -m pip show pyinstaller >nul 2>nul || python -m pip install pyinstaller
python -m PyInstaller VerseForge.spec --noconfirm --workpath build --distpath dist || (echo Build PyInstaller fallita & pause & exit /b 1)
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ISCC%" (
  "%ISCC%" /Q installer\VerseForge.iss && echo Installer creato in dist\
) else (
  echo Inno Setup non trovato: creato solo dist\VerseForge\VerseForge.exe
)
pause
