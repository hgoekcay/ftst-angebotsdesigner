#!/usr/bin/with-contenv bashio
set -e
export BILLOMAT_ID="$(bashio::config 'billomat_id')"
export BILLOMAT_API_KEY="$(bashio::config 'billomat_api_key')"
export FLASK_SECRET="$(bashio::config 'flask_secret')"
export PORT="8099"
export FTST_DATA_DIR="/data/ftst_angebotsdesigner"
if [ -z "${FLASK_SECRET}" ]; then export FLASK_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"; fi
bashio::log.info "Starting FTST AngebotsDesigner on port 8099"
exec python3 /app/app.py
