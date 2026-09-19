FROM python:3.12-slim-bookworm

ARG BUILD_VERSION=0.3.0
ARG BUILD_ARCH=amd64
LABEL io.hass.name="FTST STRATO Mail" \
      io.hass.description="Read-only STRATO mail assistant with OAuth MCP" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY app/requirements.lock /app/requirements.lock
RUN python -m pip install --no-cache-dir -r /app/requirements.lock
COPY app/ /app/
RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation /app
COPY run.sh /run.sh
RUN chmod 0555 /run.sh

EXPOSE 8098
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8098/healthz', timeout=3).read()"
CMD ["/run.sh"]
