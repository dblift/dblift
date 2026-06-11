# Stage 1: Build Python dependencies
FROM python:3.11-slim AS python-builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt /tmp/
COPY . /tmp/dblift-src
RUN pip install --no-cache-dir --user -r /tmp/requirements.txt && \
    cd /tmp/dblift-src && pip install --no-cache-dir --user ".[all]"

# Stage 2: Final runtime image
FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/dblift/dblift"
LABEL org.opencontainers.image.description="DBLift - Database Migration Tool"
LABEL org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DBLIFT_HOME=/opt/dblift \
    PATH="/opt/dblift:${PATH}"

# Copy Python packages from builder
COPY --from=python-builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Create application directory
WORKDIR /opt/dblift

# Copy application files
COPY . .

# Add to PYTHONPATH
ENV PYTHONPATH=/opt/dblift

# Create CLI entry point
RUN chmod +x /opt/dblift/dblift && \
    ln -s /opt/dblift/dblift /usr/local/bin/dblift

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace

# Verify installation
RUN python -m cli.main --version

ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "cli.main"]
CMD ["--help"]
