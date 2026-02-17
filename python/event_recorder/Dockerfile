# Event Recorder & WordPress Publisher
# Multi-platform Docker image for emon_Suite integration
# Supports: amd64, arm64, arm/v7

FROM --platform=$TARGETPLATFORM python:3.11-slim
ARG TARGETARCH
ARG BUILDPLATFORM

LABEL maintainer="Event Recorder"
LABEL description="Autonomous vehicle drive logging with data visualization and WordPress publishing"
LABEL version="0.1.0"

# Set working directory
WORKDIR /app

# Install system dependencies (minimal - no build tools needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY event_recorder/ ./event_recorder/

# Install Python dependencies
COPY event_recorder/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Create directories
RUN mkdir -p /data /config /data/plots /data/uploads

# Environment variables
ENV TZ=UTC
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Expose web interface port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/api/status', timeout=5)" || exit 1

# Entry point
CMD ["python", "-m", "event_recorder.main", \
     "--config", "/config/event_recorder_config.yml", \
     "--events-dir", "/config/events", \
     "--data-dir", "/data"]
