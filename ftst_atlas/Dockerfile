FROM ghcr.io/home-assistant/base-python:3.13-alpine3.24
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.version="${BUILD_VERSION}" io.hass.type="app" io.hass.arch="${BUILD_ARCH}"
WORKDIR /app
RUN apk add --no-cache ffmpeg
RUN pip install --no-cache-dir pypdf==6.21.2 websocket-client==1.9.0
COPY ha_calendar.py calendar_appointments.py appointments.py frontdesk_live.py frontdesk.js frontdesk.css dialog.py voice.py workflows.py knowledge.py submissions.py submissions_server.py bookkeeping_reports.py bookkeeping_export.py bookkeeping.py bookkeeping_sync.py atlas_billomat_client.py app.py telegram_bridge.py mail_client.py online_client.py jobs.py index.html style.css app.js profile.json /app/
ENV PYTHONUNBUFFERED=1
CMD ["python3", "/app/app.py"]
