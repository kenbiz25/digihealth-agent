@echo off
echo Starting Digital Health Africa AI Agent...
echo.

REM Check if .env exists
if not exist .env (
    echo ERROR: .env file not found!
    echo Copy .env.example to .env and fill in your API keys.
    pause
    exit /b 1
)

REM Install dependencies if needed
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet

echo.
echo Starting server at http://localhost:8000
echo Dashboard: http://localhost:8000
echo API Docs:  http://localhost:8000/docs
echo.
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
