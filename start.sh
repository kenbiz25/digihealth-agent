#!/usr/bin/env bash
set -e

echo "Starting Digital Health Africa AI Agent..."

if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in API keys."
    exit 1
fi

if [ ! -d venv ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install -r requirements.txt -q

echo ""
echo "Dashboard: http://localhost:8000"
echo "API Docs:  http://localhost:8000/docs"
echo ""
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
