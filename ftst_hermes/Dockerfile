FROM nousresearch/hermes-agent:v0.22.6@sha256:d27689bc6e8581ec884a7227c9101fdaebf6c853cff8859020dac14f21452b4d
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.version="${BUILD_VERSION}" io.hass.type="app" io.hass.arch="${BUILD_ARCH}"
USER root
WORKDIR /opt/ftst
COPY server.py atlas_tasks_mcp.py index.html client.js screen.css ./
RUN /opt/hermes/.venv/bin/python -c "from mcp.server.mcpserver import MCPServer"
ENTRYPOINT ["/opt/hermes/.venv/bin/python", "/opt/ftst/server.py"]
CMD []
