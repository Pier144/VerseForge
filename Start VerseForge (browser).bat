@echo off
title VerseForge
cd /d "%~dp0"
where python >nul 2>nul || (echo Python not found. Install Python 3.11+ from python.org & pause & exit /b 1)
python -c "import fastapi, uvicorn, trimesh, zstandard, Crypto" 2>nul || (
  echo Installing dependencies...
  python -m pip install -r requirements.txt
)
python start.py %*
pause
