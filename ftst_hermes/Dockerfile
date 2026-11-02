FROM nousresearch/hermes-agent:v0.22.6-amd64
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.version="${BUILD_VERSION}" io.hass.type="app" io.hass.arch="${BUILD_ARCH}"
USER root
WORKDIR /opt/ftst
COPY server.py atlas_tasks_mcp.py index.html client.js screen.css ./
RUN /opt/hermes/.venv/bin/python -c "from mcp.server.fastmcp import FastMCP"
ENTRYPOINT ["/opt/hermes/.venv/bin/python", "/opt/ftst/server.py"]
CMD []
