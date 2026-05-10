#!/bin/bash
# Startup command for the FastAPI app on Azure Web App (Linux Python).
# Configure in Portal → Web App → Configuration → General settings:
#     bash teams_api/startup.sh
cd /home/site/wwwroot
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn teams_api.main:app --host 0.0.0.0 --port 8000
