# Event Recorder - Test Environment

Self-contained test environment with MQTT broker, WordPress, and event_recorder service.

## Quick Start

### 1. Build the Docker Image (if not pulled from Docker Hub)

```bash
# From the event_recorder directory
cd ..
./build.sh local
```

Or pull from Docker Hub:
```bash
docker pull sfewings32/emon_event_recorder:latest
```

### 2. Configure Environment

Edit `.env` file:
```bash
cd test_event_recorder
nano .env
```

The `.env` file is pre-configured with default values. You can use defaults or customize:
- MySQL credentials (already set with defaults)
- WordPress credentials (will be configured after first setup)
- Timezone (default: Australia/Perth)

### 3. Start Services

```bash
docker-compose up -d
```

This starts:
- **mysql** - MySQL database for WordPress
- **wordpress** - WordPress CMS - Port 8080
- **mosquitto** - MQTT broker - Port 1883
- **event_recorder** - Event recorder service - Port 5001

### 4. Setup WordPress (First Time Only)

1. **Access WordPress setup:**
   ```
   http://localhost:8080
   ```

2. **Complete 5-minute installation:**
   - Site Title: "Event Recorder Test"
   - Username: `admin` (or your choice)
   - Password: Choose a strong password
   - Email: Your email address
   - Click "Install WordPress"

3. **Generate Application Password:**
   - Log into WordPress admin: http://localhost:8080/wp-admin
   - Go to: Users → Profile
   - Scroll to "Application Passwords"
   - Application Name: "Event Recorder"
   - Click "Add New Application Password"
   - **Copy the password** (format: `xxxx xxxx xxxx xxxx xxxx xxxx`)

4. **Update .env file:**
   ```bash
   nano .env
   ```
   Update:
   ```env
   WP_USERNAME=admin  # Or your chosen username
   WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx  # Paste your password
   ```

5. **Restart event_recorder:**
   ```bash
   docker-compose restart event_recorder
   ```

### 5. Verify Setup

Check logs:
```bash
docker-compose logs -f
```

Check service health:
```bash
docker-compose ps
```

Access services:
- **Event Recorder Web UI**: http://localhost:5001
- **WordPress Admin**: http://localhost:8080/wp-admin
- **WordPress Site**: http://localhost:8080

Test WordPress connection from Event Recorder:
```bash
curl http://localhost:5001/api/wordpress/test
```

### 6. Test MQTT Publishing

Publish test GPS data:
```bash
# Install mosquitto-clients if needed
# sudo apt-get install mosquitto-clients

# Publish GPS coordinates (simulate vehicle movement)
mosquitto_pub -h localhost -t "gps/latitude/0" -m "-31.9505"
mosquitto_pub -h localhost -t "gps/longitude/0" -m "115.8605"

# Simulate movement (change coordinates)
mosquitto_pub -h localhost -t "gps/latitude/0" -m "-31.9510"
mosquitto_pub -h localhost -t "gps/longitude/0" -m "115.8610"

# Publish battery data
mosquitto_pub -h localhost -t "battery/voltage/0/0" -m "12.5"
mosquitto_pub -h localhost -t "battery/power/0/0" -m "250"
```

### 7. View Recordings

Check the web UI at http://localhost:5001 to see:
- Active recordings
- Recording history
- Generated plots
- WordPress publishing status

### 8. Test WordPress Publishing

1. Create a recording (via GPS movement simulation)
2. Wait for recording to complete
3. Open Event Recorder UI: http://localhost:5001
4. Select the recording
5. Click "Publish to WordPress"
6. Verify post created at: http://localhost:8080

### 9. Stop Services

```bash
docker-compose down
```

Keep data:
```bash
docker-compose down  # Volumes persist
```

Remove all data:
```bash
docker-compose down -v  # Removes volumes too
```

## Directory Structure

```
test_event_recorder/
├── docker-compose.yml          # Service definitions (4 services)
├── .env                        # Environment variables
├── config/                     # Event recorder configuration
│   ├── event_recorder_config.yml
│   └── events/
│       └── 20260212-1000.yml
├── data/                       # Recorded data & plots
│   ├── recordings.db
│   ├── plots/
│   └── uploads/
├── mosquitto-config/           # MQTT broker config
│   └── mosquitto.conf
└── README.md                   # This file

Docker Volumes (managed by Docker):
├── mysql-data                  # WordPress database
├── wordpress-data              # WordPress files
├── mosquitto-data              # MQTT persistence
└── mosquitto-logs              # MQTT logs
```

## Configuration Files

### event_recorder_config.yml
Main service configuration:
- MQTT broker settings
- Database paths
- Plot settings
- WordPress credentials

### events/YYYYMMDD-HHMM.yml
Time-based event trigger configurations:
- GPS monitoring topics
- Start/stop conditions
- Recording topics
- Plot definitions

## Troubleshooting

### MQTT Connection Failed
```bash
# Check mosquitto is running
docker logs test_mqtt

# Test MQTT connection
mosquitto_sub -h localhost -t "#" -v
```

### Event Recorder Not Starting
```bash
# Check logs
docker logs test_event_recorder

# Check config files
cat config/event_recorder_config.yml
```

### No Recordings Created
- Verify GPS data is being published
- Check GPS threshold settings in event config
- View logs: `docker logs -f test_event_recorder`

### WordPress Not Accessible
```bash
# Check WordPress is running
docker logs test_wordpress

# Check MySQL is running
docker logs test_mysql

# Verify containers are up
docker-compose ps
```

### WordPress Publishing Failed
```bash
# Test WordPress connection
curl http://localhost:5001/api/wordpress/test

# Check event_recorder can reach WordPress
docker exec test_event_recorder ping -c 3 wordpress

# Verify WordPress credentials in .env
cat .env | grep WP_
```

Common issues:
- **Application Password not set**: Generate in WordPress admin
- **Wrong WP_SITE_URL**: Should be `http://wordpress` (container name)
- **WordPress not ready**: Wait 30 seconds after `docker-compose up`
- **Need to restart**: Run `docker-compose restart event_recorder` after updating .env

### WordPress Database Issues
If WordPress won't install:
```bash
# Stop and remove all containers
docker-compose down -v

# Start fresh
docker-compose up -d

# Wait for MySQL to initialize (30 seconds)
sleep 30

# Access WordPress setup
open http://localhost:8080
```

## Testing Phases

### Phase 1-2: Core Recording & Plotting
1. Start services
2. Publish GPS movement data
3. Verify recording created
4. Check plots generated in `data/plots/`

### Phase 3: Web Interface
1. Open http://localhost:5001
2. Test dashboard view
3. Test manual recording start/stop
4. Upload test images

### Phase 4: WordPress Publishing
1. Complete WordPress setup (see step 4 above)
2. Generate Application Password in WordPress admin
3. Update `.env` with WP_APP_PASSWORD
4. Restart event_recorder: `docker-compose restart event_recorder`
5. Test connection: http://localhost:5001/api/wordpress/test
6. Create a test recording (publish GPS data)
7. Open Event Recorder UI: http://localhost:5001
8. Click "Publish to WordPress" on a completed recording
9. Verify post at: http://localhost:8080
10. Check post includes plots and statistics

## Development Testing

### Test with Local Code Changes

Build and test with local changes:
```bash
# From event_recorder directory
docker-compose -f test_event_recorder/docker-compose.yml build event_recorder
docker-compose -f test_event_recorder/docker-compose.yml up -d
```

### View Live Logs
```bash
docker-compose logs -f event_recorder
```

### Interactive Shell
```bash
docker exec -it test_event_recorder bash
```

## Notes

### Security
- MQTT uses `allow_anonymous true` - **NOT for production!**
- WordPress and MySQL use default passwords - **Change for production!**
- This is a TEST environment - use strong passwords in production

### Data Persistence
- Data persists in Docker volumes between restarts
- Recordings: `data/` directory
- WordPress content: `wordpress-data` volume
- MySQL database: `mysql-data` volume

### Networking
- All services communicate via Docker network (no external access needed)
- Services reach each other by container name (e.g., `wordpress`, `mysql`, `mosquitto`)
- `WP_SITE_URL=http://wordpress` uses internal Docker network
- External access via ports: 8080 (WordPress), 5001 (Event Recorder), 1883 (MQTT)

### Ports
- 5001: Event Recorder Web UI
- 8080: WordPress (not 80 to avoid conflicts)
- 1883: MQTT broker
- MySQL 3306 is internal only (not exposed)
