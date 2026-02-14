FROM --platform=$TARGETPLATFORM python:3.11-slim
ARG TARGETARCH

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

    # Install Python dependencies
RUN pip install --no-cache-dir \
    Flask \
    PyYAML \
    gunicorn

    # Copy the shared emon library (parent directory)
COPY pyEmon/ /app/pyEmon/

# Copy Python application files (paths relative to `python` build context)
COPY emon_settings_web/emon_settings_web.py ./
COPY emon_settings_web/start_settings_manager.py ./
COPY emon_settings_web/web_static/ ./web_static/
COPY emon_settings_web/web_templates/ ./web_templates/


# Create config directory for mounted volumes
RUN mkdir -p /config

# Set environment variables
ENV TZ=UTC
ENV FLASK_APP=emon_settings_web.py

# Expose port for web server
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/api/settings/current')" || exit 1

# Run the settings manager with Gunicorn in production mode
CMD ["python", "start_settings_manager.py", "--settings-path", "/config", "--port", "5000", "--use-gunicorn"]
