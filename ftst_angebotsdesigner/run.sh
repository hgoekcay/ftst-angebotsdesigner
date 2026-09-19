#!/usr/bin/with-contenv bashio
set -e
export STRATO_AUTO_IMPORT="$(bashio::config 'strato_auto_import')"
export STRATO_AUTO_AI="$(bashio::config 'strato_auto_ai')"
export STRATO_POLL_SECONDS="$(bashio::config 'strato_poll_seconds')"
export STRATO_PROVIDER="$(bashio::config 'strato_provider')"
export STRATO_BRIDGE_TOKEN="$(bashio::config 'strato_bridge_token')"
export STRATO_IMAP_ENABLED="$(bashio::config 'strato_imap_enabled')"
export STRATO_IMAP_PASSWORD="$(bashio::config 'strato_imap_password')"
export AI_PROVIDER="$(bashio::config 'ai_provider')"
export BILLOMAT_ID="$(bashio::config 'billomat_id')"
export BILLOMAT_API_KEY="$(bashio::config 'billomat_api_key')"
export FLASK_SECRET="$(bashio::config 'flask_secret')"
export PORT="8099"
export FTST_REQUIRE_INGRESS="1"
export FTST_DATA_DIR="/data/ftst_angebotsdesigner"
export OPENAI_API_KEY="$(bashio::config 'openai_api_key')"
export OPENAI_MODEL="$(bashio::config 'openai_model')"
export OPENAI_TRANSCRIBE_MODEL="$(bashio::config 'openai_transcribe_model')"
if [ -z "${FLASK_SECRET}" ]; then export FLASK_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"; fi
bashio::log.info "Starting FTST AngebotsDesigner on port 8099"
exec python3 /app/app.py
