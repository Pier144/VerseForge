@echo off
title VerseForge
cd /d "%~dp0"
where python >nul 2>nul || (echo Python non trovato. Installa Python 3.11+ da python.org & pause & exit /b 1)
python -c "import fastapi, uvicorn, trimesh, zstandard, Crypto" 2>nul || (
  echo Installo le dipendenze...
  python -m pip install -r requirements.txt
)
python avvia.py %*
pause
