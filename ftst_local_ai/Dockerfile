# Official Ollama 0.34.1, linux/amd64 digest verified 2026-09-16.
FROM ollama/ollama:0.34.1@sha256:8eb6c4d16138c8320f2598f03e01b3549f6ed2e41fe6ac16329a5a921b314914
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.version="${BUILD_VERSION}" io.hass.type="app" io.hass.arch="${BUILD_ARCH}"
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY service.py /opt/ftst/service.py
ENV OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_MODELS=/data/models \
    OLLAMA_NO_CLOUD=1 \
    OLLAMA_NOHISTORY=1 \
    OLLAMA_DEBUG=0 \
    OLLAMA_DEBUG_LOG_REQUESTS=0 \
    OLLAMA_NUM_PARALLEL=1 \
    OLLAMA_MAX_LOADED_MODELS=1 \
    OLLAMA_MAX_QUEUE=1 \
    OLLAMA_CONTEXT_LENGTH=4096 \
    OLLAMA_KEEP_ALIVE=60s \
    OLLAMA_LOAD_TIMEOUT=120s \
    OLLAMA_VULKAN=0
ENTRYPOINT ["python3", "-u", "/opt/ftst/service.py"]
CMD []
