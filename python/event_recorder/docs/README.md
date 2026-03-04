# Event Recorder & WordPress Publisher

Autonomous service for automatic vessel track logging with data visualization and WordPress blog publishing.

## Overview

Monitors GPS position via MQTT, automatically detects vessel movement, records sensor data (battery, GPS, temperature, motor), generates comprehensive visualization plots, and publishes results to WordPress blog posts.

**Primary Use Case:** Autonomous vessel track documentation - no manual intervention required.

## Features

### 🚗 Automatic GPS-Based Triggers
- Detects vessel movement via GPS coordinate changes (Haversine distance calculation)
- Configurable start threshold (default: 20m movement for 10 seconds)
- Configurable stop threshold (default: stationary for 60 seconds)

### 📊 Multi-Topic MQTT Recording
- Wildcard subscription support (`gps/#`, `battery/#`, etc.)
- Message buffering with batch writes (5s or 1000 messages)
- SQLite persistence with WAL mode for crash resilience

### 🔌 Power Outage Recovery
- Detects interrupted recordings on startup
- Automatic resume or completion based on vessel state
- No data loss (at most 5 seconds of messages)

### 📈 Comprehensive Visualizations
- **Line plots**: Speed, power, voltage over time
- **Multi-line plots**: Battery bank comparisons
- **GPS route maps**: Interactive maps with start/end markers
- **Statistics tables**: Distance, speed, energy consumption

### 📝 WordPress Integration
- Application Password authentication (WordPress 5.6+)
- Automatic media upload (plots and images)
- Blog post creation with customizable templates
- Category management and featured images
- Retry logic with exponential backoff

### 🌐 Web UI
- Real-time status dashboard with 2-second polling
- View all recordings with filtering
- Manual recording start/stop
- Image upload functionality
- WordPress test and publish controls
- Purple gradient theme matching emon_settings_web

### ⚙️ Configuration-Trackn
- Time-based YAML configs (YYYYMMDD-HHMM.yml pattern)
- Environment variable substitution
- Per-event trigger and plot customization
- Multiple WordPress site support

## Architecture

```
event_recorder/
├── main.py                    # Service orchestrator
├── trigger_monitor.py         # GPS monitoring & movement detection
├── data_recorder.py           # MQTT buffering & SQLite persistence
├── data_processor.py          # Plot generation & statistics
├── wordpress_publisher.py     # WordPress REST API client
├── recovery_manager.py        # Power outage recovery
├── web_interface.py           # Flask REST API
├── config_manager.py          # Time-based YAML loading
├── models.py                  # SQLite schema (WAL mode)
└── web_ui/                    # Vanilla JavaScript SPA
    ├── index.html             # Main interface
    ├── app.js                 # Dashboard, recordings, manual control
    └── style.css              # Purple gradient theme
```

### Data Flow
```
GPS Topics (latitude/longitude)
    → trigger_monitor.py (detect movement/stopped)
        → [TRIGGER: Movement detected]
            → data_recorder.py (subscribe to battery/gps/temp topics)
                → Buffer to SQLite (flush every 5 seconds)
                    → [STOP: Vessel stopped 60+ seconds]
                        → data_processor.py (generate plots & stats)
                            → wordpress_publisher.py (create blog post)
                                → WordPress REST API
```

## Development Status

**Version:** 0.1.0

**Current Status:** ✅ Phases 1-4 Complete, Phase 5 (Deployment) In Progress

### Completed Phases

#### ✅ Phase 1: Core Recording Infrastructure
- [x] SQLite schema with WAL mode
- [x] Configuration management (time-based YAML)
- [x] MQTT data recorder with buffering
- [x] GPS trigger monitor (Haversine distance)
- [x] Power outage recovery
- [x] Integration testing

#### ✅ Phase 2: Data Processing & Plotting
- [x] Line plot generation (matplotlib)
- [x] Multi-line plots
- [x] GPS route maps (folium + matplotlib fallback)
- [x] Statistics calculation (distance, speed, energy)
- [x] Statistics table generation
- [x] Image storage in database

#### ✅ Phase 3: Web Interface
- [x] Flask REST API (15+ endpoints)
- [x] Vanilla JavaScript SPA
- [x] Real-time status polling (2-second interval)
- [x] Dashboard view
- [x] Recordings management
- [x] Manual control
- [x] Settings view
- [x] Purple gradient theme

#### ✅ Phase 4: WordPress Integration
- [x] Application Password authentication
- [x] Media upload to WordPress library
- [x] Blog post creation with embedded images
- [x] Error handling with retry logic
- [x] Category management
- [x] Template system
- [x] Web API endpoints

#### 🚧 Phase 5: Production Deployment (In Progress)
- [x] Dockerfile (multi-platform support)
- [x] docker-compose integration
- [x] Build scripts (Linux & Windows)
- [ ] Docker Hub deployment
- [ ] End-to-end testing
- [ ] Documentation finalization

## Quick Start

### Option 1: Docker Deployment (Recommended)

#### Prerequisites
- Docker & docker-compose
- MQTT broker (Mosquitto)
- WordPress site (5.6+) with HTTPS (optional, for Phase 4)

#### Installation

```bash
# 1. Pull Docker image
docker pull sfewings32/emon_event_recorder:latest

# 2. Create configuration directory
mkdir -p /share/event_recorder/config/events
mkdir -p /share/event_recorder/data

# 3. Copy example configurations
cp config_examples/event_recorder_config.yml /share/event_recorder/config/
cp config_examples/events/20260212-1000.yml /share/event_recorder/config/events/

# 4. Configure environment variables
cat > .env << EOF
WP_SITE_URL=https://yourblog.com
WP_USERNAME=admin
WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
TIMEZONE=Australia/Perth
EOF

# 5. Add to docker-compose.yml (see docker-compose.example.yml)

# 6. Start service
docker-compose up -d event_recorder
```

#### Verify Deployment

```bash
# Check logs
docker logs -f event_recorder

# Test web interface
curl http://localhost:5001/api/status

# Open browser
open http://localhost:5001
```

### Option 2: Development Setup

#### Prerequisites
- Python 3.11+
- MQTT broker (Mosquitto)
- GPS data publishing to MQTT

#### Installation

```bash
# 1. Navigate to event_recorder directory
cd python/event_recorder

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run integration test
python test_full_cycle.py

# 4. Start web interface
cd ..
set PYTHONPATH=.
python -m event_recorder.web_interface --db event_recorder/test_recordings.db --port 5001

# 5. Open browser
open http://localhost:5001
```

## Configuration

### Main Service Config: `/config/event_recorder_config.yml`

```yaml
service:
  mqtt_broker: "mqtt"
  mqtt_port: 1883
  database_path: "/data/recordings.db"
  timezone: "Australia/Perth"

recording:
  buffer_flush_interval: 5
  max_buffer_size: 1000
  min_recording_duration: 30

wordpress:
  default_site:
    site_url: "${WP_SITE_URL}"
    username: "${WP_USERNAME}"
    app_password: "${WP_APP_PASSWORD}"
    category: "Track Logs"
    publish_status: "draft"
```

### Event Config: `/config/events/YYYYMMDD-HHMM.yml`

```yaml
events:
  track_recording:
    enabled: true

    # Monitor GPS topics
    monitor_topics:
      - "gps/latitude/0"
      - "gps/longitude/0"

    # Start: Vessel moving
    start_condition:
      type: "gps_movement"
      distance_threshold: 20      # meters
      duration: 10                # seconds

    # Stop: Vessel stopped
    stop_condition:
      type: "gps_stopped"
      distance_threshold: 5       # meters
      duration: 60                # seconds

    # Topics to record
    record_topics:
      - "gps/#"
      - "battery/#"
      - "temperature/bms/+"

    # Plot generation
    plots:
      - type: "line"
        title: "Speed Over Time"
        topics: ["gps/speed/0"]
      - type: "map"
        title: "Track Route"
        topics: ["gps/latitude/0", "gps/longitude/0"]
```

See `config_examples/` for complete examples.

## WordPress Setup

### Generate Application Password

1. Log into WordPress Admin → Users → Profile
2. Scroll to "Application Passwords"
3. Enter name: "Event Recorder"
4. Click "Add New Application Password"
5. Copy password (format: `xxxx xxxx xxxx xxxx xxxx xxxx`)

### Configure Environment

```bash
# Add to .env file
WP_SITE_URL=https://yourblog.com
WP_USERNAME=admin
WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
```

### Test Connection

```bash
# Via web API
curl http://localhost:5001/api/wordpress/test

# Via CLI
python -m event_recorder.wordpress_publisher \
  --site-url "https://yourblog.com" \
  --username "admin" \
  --password "xxxx xxxx xxxx xxxx xxxx xxxx"
```

See `wordpress_config.example.yml` for detailed setup instructions.

## Testing

### Integration Test (Phases 1-2)
```bash
python test_full_cycle.py
```

Simulates complete track cycle: GPS movement → data recording → processing → plot generation

### Web Interface Test (Phase 3)
```bash
# Start server
python -m event_recorder.web_interface --db test_recordings.db --port 5001

# Open http://localhost:5001
# Test dashboard, recordings, manual control
```

### WordPress Mock Test (Phase 4)
```bash
python test_wordpress_mock.py
```

Tests WordPress integration without real WordPress site (mocked HTTP requests)

### WordPress Live Test (Phase 4)
```bash
# Configure .env first
python test_wordpress.py
```

Tests real WordPress connection, image upload, post creation

See [TESTING.md](TESTING.md) for comprehensive testing guide.

## API Reference

### REST API Endpoints

#### Status
```
GET /api/status
```
Returns service status, active recordings, database stats

#### Recordings
```
GET    /api/recordings                 # List all
GET    /api/recordings/<id>            # Get details
POST   /api/recordings                 # Start manual recording
PUT    /api/recordings/<id>            # Update name/description
DELETE /api/recordings/<id>            # Delete
POST   /api/recordings/<id>/stop       # Stop recording
POST   /api/recordings/<id>/publish    # Publish to WordPress
```

#### Images
```
POST   /api/recordings/<id>/images     # Upload image
DELETE /api/images/<id>                # Delete image
```

#### WordPress
```
GET    /api/wordpress/test             # Test connection
```

## Project Structure

```
event_recorder/
├── README.md                          # This file
├── TESTING.md                         # Testing guide
├── requirements.txt                   # Python dependencies
├── Dockerfile                         # Multi-platform Docker image
├── docker-compose.example.yml         # Docker compose example
├── build.sh                           # Linux/Mac build script
├── build.cmd                          # Windows build script
├── .dockerignore                      # Docker build exclusions
├── .env.example                       # Environment variable template
│
├── config_examples/                   # Example configurations
│   ├── event_recorder_config.yml     # Main service config
│   ├── events/
│   │   └── 20260212-1000.yml         # Event trigger config
│   └── wordpress_config.example.yml   # WordPress setup guide
│
├── event_recorder/                    # Python package
│   ├── __init__.py
│   ├── main.py                        # Service entry point
│   ├── models.py                      # SQLite schema
│   ├── config_manager.py              # Configuration loading
│   ├── trigger_monitor.py             # GPS monitoring
│   ├── data_recorder.py               # MQTT recording
│   ├── data_processor.py              # Plot generation
│   ├── wordpress_publisher.py         # WordPress client
│   ├── recovery_manager.py            # Power outage recovery
│   ├── web_interface.py               # Flask REST API
│   └── web_ui/                        # Web interface
│       ├── index.html
│       ├── app.js
│       └── style.css
│
├── docs/                              # Documentation
│   └── EVENT_RECORDER_REQUIREMENTS.md # Living requirements
│
└── tests/                             # Test scripts
    ├── test_full_cycle.py             # Integration test (Phases 1-2)
    ├── test_wordpress_mock.py         # WordPress mock test
    └── test_wordpress.py              # WordPress live test
```

## Building Docker Image

### Local Build (Single Platform)

```bash
# Linux/Mac
./build.sh local

# Windows
build.cmd local
```

### Multi-Platform Build & Push

```bash
# Requires Docker Buildx and Linux/WSL2
./build.sh push
```

Builds for: `linux/amd64`, `linux/arm64`, `linux/arm/v7`

### Test Build

```bash
./build.sh test
```

Builds and runs test container with example config.

## Troubleshooting

### MQTT Connection Failed
```
Error: Failed to connect to MQTT broker
```
**Solution:** Check MQTT broker is running and accessible
```bash
docker ps | grep mosquitto
mosquitto_sub -h localhost -t "#" -v
```

### GPS Data Not Detected
```
Warning: No GPS data received
```
**Solution:** Verify GPS data is publishing
```bash
mosquitto_sub -h localhost -t "gps/#" -v
```

### WordPress Authentication Failed
```
Error: Authentication failed - check credentials
```
**Solution:**
- Verify WordPress URL (https://)
- Check username spelling (case-sensitive)
- Regenerate application password
- Ensure WordPress 5.6+ with HTTPS

### Database Locked
```
Error: database is locked
```
**Solution:** SQLite WAL mode should prevent this. If it occurs:
```bash
# Check for multiple instances
docker ps | grep event_recorder
# Stop extra instances
docker stop event_recorder
```

See [TESTING.md](TESTING.md) for more troubleshooting tips.

## Documentation

- **Testing Guide**: [TESTING.md](TESTING.md)
- **Requirements**: [docs/EVENT_RECORDER_REQUIREMENTS.md](../../docs/EVENT_RECORDER_REQUIREMENTS.md)
- **Implementation Plan**: `~/.claude/plans/rosy-plotting-lovelace.md`
- **WordPress Setup**: [config_examples/wordpress_config.example.yml](config_examples/wordpress_config.example.yml)

## Contributing

This is part of the emon_Suite project. Follow existing patterns:
- Time-based YAML configurations
- Vanilla JavaScript (no frameworks)
- Flask REST APIs
- SQLite for persistence
- Docker deployment
- Multi-platform support

## License

Part of emon_Suite project.

## Author

Stephen Fewings / terra15 technologies

## Acknowledgments

- Built with Claude Code (Anthropic)
- Integration with emon_Suite ecosystem
- WordPress REST API
- OpenStreetMap for route mapping
