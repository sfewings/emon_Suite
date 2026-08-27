# Event Recorder & WordPress Publisher
# Multi-platform Docker image for emon_Suite integration
# Supports: amd64, arm64, arm/v7

FROM --platform=$TARGETPLATFORM python:3.11-slim
ARG TARGETARCH
ARG BUILDPLATFORM

LABEL maintainer="Event Recorder"
LABEL description="Autonomous vessel track logging with data visualization and WordPress publishing"
LABEL version="0.1.0"

# Set working directory
WORKDIR /app

# No system dependencies.
#
# chromium + chromium-driver used to be installed here to screenshot the folium
# map into a PNG. Route maps are now drawn by matplotlib over the offline chart
# from enchantee_racing, which is the map the boat can actually use with no
# internet, so nothing screenshots a browser any more. folium still writes the
# interactive OpenStreetMap view for the WordPress post, and generating that
# needs no browser. That takes several hundred megabytes off the image.

# Create directories
RUN mkdir -p /data /config /data/plots /data/uploads

# Install Python dependencies.
# Copy requirements.txt on its own, before the application code, so that editing
# source does not invalidate this layer. Copying the whole package first meant
# every source change re-ran the full pip install, which is slow on a Pi.
COPY event_recorder/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code last: it changes most often, so everything above it
# stays cached.
COPY event_recorder/ ./event_recorder/

# Environment variables
ENV TZ=UTC
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Expose web interface port
EXPOSE 5000

# Health check - uses stdlib urllib to avoid importing the full requests package
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=5)" || exit 1

# Entry point
CMD ["python", "-m", "event_recorder.main", \
     "--config", "/config/event_recorder_config.yml", \
     "--events-dir", "/config/events", \
     "--data-dir", "/data"]
