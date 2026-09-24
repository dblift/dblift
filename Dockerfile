# Stage 1: build and install the package with every engine extra
FROM python:3.11-slim AS python-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY . /tmp/dblift-src
RUN cd /tmp/dblift-src && pip install --no-cache-dir --user ".[all]"

# Stage 2: runtime image
FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/dblift/dblift"
LABEL org.opencontainers.image.description="DBLift - Database Migration Tool"
LABEL org.opencontainers.image.licenses="Apache-2.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The wheel and its console script were installed into /root/.local in stage 1.
COPY --from=python-builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

RUN mkdir -p /workspace
WORKDIR /workspace

# Verify installation
RUN dblift --version

ENTRYPOINT ["/usr/bin/tini", "--", "dblift"]
CMD ["--help"]
