FROM ghcr.io/home-assistant/base-python:3.13-alpine3.24
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.version="${BUILD_VERSION}" io.hass.type="app" io.hass.arch="${BUILD_ARCH}"
WORKDIR /app
COPY app.py telegram_bridge.py mail_client.py online_client.py jobs.py index.html style.css app.js profile.json /app/
ENV PYTHONUNBUFFERED=1
CMD ["python3", "/app/app.py"]
