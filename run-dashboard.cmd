@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Project virtual environment is missing. Create .venv and install requirements.txt first.
    exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py %*
exit /b %errorlevel%
