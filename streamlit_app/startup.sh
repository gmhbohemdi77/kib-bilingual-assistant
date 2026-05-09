#!/bin/bash
# Startup command for Azure Web App (Linux Python).
# Configure this in Portal → Web App → Configuration → General settings →
# "Startup Command":
#     bash startup.sh
#
# Azure mounts the deployed code at /home/site/wwwroot. Streamlit needs to
# bind to 0.0.0.0:8000 so the App Service front door can reach it.

cd /home/site/wwwroot
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app/app.py \
    --server.port 8000 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false
