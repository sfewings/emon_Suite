# Docker Deployment Guide for emon_settings_web

## Overview

This Dockerfile creates a production-ready containerized version of the emon_settings_web application using Gunicorn as the web server (not Flask development server).

## Building the Docker Image

### Standard Build

```bash
cd emon_Suite
docker build -f -t emon-settings-web:latest -f python/emon_settings_web/Dockerfile python
```

### With Platform Specification (for cross-platform compatibility)

```bash
cd emon_Suite
docker build -t emon-settings-web:latest -f python/emon_settings_web/Dockerfile python
```

## Running the Container

### Basic Usage (with local config directory)

```bash
docker run -d \
  --name emon-settings \
  -v /path/to/your/emon/config:/config \
  -e EMON_CONFIG=/config \
  -e TZ=UTC \
  -p 5000:5000 \
  emon-settings-web:latest
```

### Example: Using Australia/Perth timezone

```bash
docker run -d \
  --name emon-settings \
  -v /home/user/emon_config:/config \
  -e TZ=Australia/Perth \
  -p 5000:5000 \
  emon-settings-web:latest
```

### Example: Custom port mapping (external port 8080)

```bash
docker run -d \
  --name emon-settings \
  -v /home/user/emon_config:/config \
  -p 8080:5000 \
  emon-settings-web:latest
```

## Environment Variables

### EMON_CONFIG (Required)

- **Default:** `/config`
- **Purpose:** Path where YAML settings files are stored
- **Example:** `-e EMON_CONFIG=/config`

### TZ (Optional)

- **Default:** `UTC`
- **Purpose:** Timezone for log timestamps and time-based settings selection
- **Example:** `-e TZ=Australia/Perth`
- **Supported values:** Any valid IANA timezone (Australia/Sydney, America/New_York, Europe/London, etc.)

## Health Check

The container includes a built-in health check that verifies the API is responding:

```bash
docker ps  # Will show "healthy" or "unhealthy" status
```

## Docker Compose Example

Create a `docker-compose.yml` in your emon suite directory:

```yaml
version: '3.8'

services:
  emon-settings-web:
    build:
      context: ./python/emon_settings_web
      dockerfile: Dockerfile
    container_name: emon-settings
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - /home/user/emon_config:/config
    environment:
      EMON_CONFIG: /config
      TZ: Australia/Perth
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:5000/api/settings/current')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 5s
```

Then run:

```bash
docker-compose up -d
docker-compose logs -f emon-settings-web
```

## Docker Configuration Details

### Base Image

- **Image:** `python:3.11-slim`
- **Size:** ~150MB (slim variant is lightweight)
- **Architecture Support:** linux/amd64, linux/arm64, linux/arm/v7 (via `--platform` flag)

### Web Server

- **Server:** Gunicorn (production-ready WSGI HTTP server)
- **Workers:** 4 processes (configured for typical workloads)
- **Timeout:** 30 seconds per request
- **Logging:** All access and error logs to stdout (visible via `docker logs`)

### Port

- **Internal:** 5000 (Gunicorn binding)
- **External:** Configurable (default: 5000)
- **Protocol:** HTTP

### Volume Mounts

- **Container Path:** `/config`
- **Purpose:** Store YAML settings files persistently
- **Must be writable:** For creating new settings files via web UI

## Accessing the Web Interface

After starting the container, access the web application:

- **Local machine:** http://localhost:5000
- **Remote machine:** http://`<hostname-or-ip>`:5000

## Viewing Logs

```bash
# Real-time logs
docker logs -f emon-settings

# Last 50 lines
docker logs --tail 50 emon-settings

# With timestamps
docker logs -f --timestamps emon-settings
```

## Stopping and Cleaning Up

```bash
# Stop the container
docker stop emon-settings

# Remove the container
docker rm emon-settings

# Remove the image
docker rmi emon-settings-web:latest
```

## Networking

### Localhost only (development)

```bash
docker run -d \
  --name emon-settings \
  -v /path/to/config:/config \
  -p 127.0.0.1:5000:5000 \
  emon-settings-web:latest
```

### Internet-facing (production)

```bash
docker run -d \
  --name emon-settings \
  -v /path/to/config:/config \
  -p 5000:5000 \
  --restart unless-stopped \
  emon-settings-web:latest
```

**Security Note:** For internet-facing deployment, consider:

- Using a reverse proxy (Nginx, Traefik)
- Implementing authentication/authorization
- Using HTTPS with SSL certificates
- Restricting access with firewall rules

## Advanced Configuration

### Custom Gunicorn Settings

Modify the CMD in Dockerfile to adjust:

- `--workers`: Number of processes (4 is default, scale based on CPU cores)
- `--timeout`: Request timeout in seconds (30 is default)
- `--max-requests`: Restart workers after N requests (prevents memory leaks)

Example for high-traffic:

```
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "8", "--max-requests", "1000", "emon_settings_web:app"]
```

### Resource Limits

```bash
docker run -d \
  --memory=512m \
  --cpus=1.0 \
  --name emon-settings \
  -v /path/to/config:/config \
  -p 5000:5000 \
  emon-settings-web:latest
```

## Troubleshooting

### Port already in use

```bash
# Find what's using port 5000
lsof -i :5000
# Use different port
docker run -p 8080:5000 emon-settings-web:latest
```

### Config directory permission denied

```bash
# Ensure directory is readable by Docker
chmod 755 /path/to/config
# Check ownership
ls -la /path/to/config
```

### Container exits immediately

```bash
# Check logs
docker logs emon-settings
# Check Docker output
docker run -it emon-settings-web:latest
```

### Health check failing

```bash
# Check if API is responding
curl http://localhost:5000/api/settings/current
# View detailed error logs
docker logs --since 5m -f emon-settings
```

## Performance Tuning

### CPU-bound optimization

```bash
--workers = (2 × CPU cores) + 1
```

### Memory optimization

```bash
# Use memory limit
--memory=256m
# Add swap space
--memory-swap=512m
```

### I/O optimization

For high file access:

- Use SSD for `/config` volume
- Consider persistent named volume instead of bind mount
- Enable Docker's caching during build

## Version Information

- **Python:** 3.11
- **Flask:** 2.3.3
- **PyYAML:** 6.0
- **Gunicorn:** 21.2.0

## Support and Debugging

For detailed logs on startup:

```bash
docker run -it \
  -v /path/to/config:/config \
  emon-settings-web:latest \
  /bin/bash
```

Then manually run:

```bash
python -m gunicorn --bind 0.0.0.0:5000 emon_settings_web:app
```
