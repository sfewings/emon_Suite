# Testing Guide - Event Recorder

## Quick Start Testing

### Prerequisites

1. **Python 3.11+** installed
2. **MQTT Broker** (Mosquitto) running
3. **Dependencies** installed

### Setup

```bash
# Navigate to event_recorder directory
cd c:/Users/StephenFewings/OneTrack\ -\ terra15\ technologies/Documents/Home/emon/emon_Suite/python/event_recorder

# Install dependencies
pip install -r requirements.txt

# Start MQTT broker (if using Docker)
docker run -d -p 1883:1883 eclipse-mosquitto:latest

# Or if you have the full emon_Suite docker-compose:
cd ../../provisioning/shannstainable
docker-compose up -d mosquitto
```

### Run Full Integration Test (Phases 1-2)

This test simulates a complete track cycle:

- GPS position changes (start/stop detection)
- Battery data recording
- Automatic plot generation
- Statistics calculation

```bash
python test_full_cycle.py
```

**Expected output:**

```
==============================================================
FULL INTEGRATION TEST: Phases 1-2
==============================================================

STEP 1: Initialize Database
✓ Database initialized

STEP 2: Initialize Components
✓ Components initialized

STEP 3: Connect to MQTT Broker
✓ All MQTT connections established

STEP 4: Setup GPS Trigger Monitor
✓ Trigger monitor configured

STEP 5: Simulate Track Cycle
Publishing GPS waypoints, speed, and battery data...

Phase 1: Stationary at start
Phase 2: Starting to move (trigger START)
🟢 START TRIGGER FIRED!
Created recording 1: Test Track - 2026-02-12 ...
Phase 3: Stopped at destination (trigger STOP)
🔴 STOP TRIGGER FIRED!

STEP 6: Verify Recording
✓ Recording verified
  Messages: 50+
  Topics: gps/latitude/0, gps/longitude/0, gps/speed/0, battery/power/0/0, battery/voltage/0/0

STEP 7: Process Recording (Generate Plots)
✓ Processing complete
  Plots generated: 5
    - Speed Over Time
    - Battery Power
    - Battery Voltage
    - Track Route
    - Statistics Summary

STEP 8: Verify Outputs
✓ Plots verified

==============================================================
INTEGRATION TEST: PASSED ✅
==============================================================
```

### View Test Results

After successful test:

```bash
# View database
sqlite3 test_recordings.db "SELECT * FROM recordings;"

# View generated plots
start test_plots/1/speed_over_time.png
start test_plots/1/battery_power.png
start test_plots/1/track_route.png
start test_plots/1/statistics_summary.png
```

---

## Manual Component Testing

### Test Database (models.py)

```bash
python -m event_recorder.models --init-db test.db --stats
```

### Test GPS Trigger Monitor

Terminal 1 - Start monitor:

```bash
python -m event_recorder.trigger_monitor --broker localhost
```

Terminal 2 - Publish GPS data:

```bash
# Stationary
mosquitto_pub -h localhost -t "gps/latitude/0" -m "-31.9505"
mosquitto_pub -h localhost -t "gps/longitude/0" -m "115.8605"

# Move 50 meters
mosquitto_pub -h localhost -t "gps/latitude/0" -m "-31.9510"
mosquitto_pub -h localhost -t "gps/longitude/0" -m "115.8610"

# Should see START trigger after 10 seconds

# Stop (same position for 60 seconds)
# Should see STOP trigger
```

### Test Data Recorder

Terminal 1 - Start recorder:

```bash
python -m event_recorder.data_recorder \
    --broker localhost \
    --db test.db \
    --topics "gps/#" "battery/#" \
    --duration 30
```

Terminal 2 - Publish test data:

```bash
# Publish messages for 30 seconds
mosquitto_pub -h localhost -t "gps/speed/0" -m "25.5"
mosquitto_pub -h localhost -t "battery/power/0/0" -m "-1500"
```

### Test Data Processor

```bash
# First, create a recording with data
python test_full_cycle.py

# Then process a specific recording
python -m event_recorder.data_processor \
    --db test_recordings.db \
    --recording-id 1 \
    --plots-dir test_plots
```

---

## Troubleshooting

### MQTT Connection Failed

```
Error: Failed to connect to MQTT: [Errno 111] Connection refused
```

**Solution:** Start Mosquitto broker

```bash
docker run -d -p 1883:1883 eclipse-mosquitto:latest
```

### Module Not Found

```
ModuleNotFoundError: No module named 'paho'
```

**Solution:** Install dependencies

```bash
pip install -r requirements.txt
```

### No GPS Data

```
Warning: No data found for topic gps/latitude/0
```

**Solution:** Check that GPS data is being published:

```bash
mosquitto_sub -h localhost -t "gps/#" -v
```

### Folium/Selenium Not Found

```
Warning: folium or selenium not installed, skipping route map
```

**Solution:** This is OK - test will use matplotlib fallback for route maps. To use folium:

```bash
pip install folium selenium
# Also need ChromeDriver: https://chromedriver.chromium.org/
```

---

## Test Coverage

### Phase 1: Core Recording Infrastructure ✅

- [X] Database initialization
- [X] SQLite WAL mode
- [X] Configuration loading
- [X] MQTT connection
- [X] GPS position tracking
- [X] Movement detection (Haversine)
- [X] Start trigger (movement > 20m for 10s)
- [X] Stop trigger (stationary > 60s)
- [X] Data buffering
- [X] Batch writes to database

### Phase 2: Data Processing & Plotting ✅

- [X] Line plot generation
- [X] Multi-line plot generation
- [X] GPS route map (matplotlib fallback)
- [X] Statistics calculation (distance, speed, energy)
- [X] Statistics table generation
- [X] Image storage in database

### Phase 3: Web Interface ✅

- [X] Flask REST API
- [X] JavaScript frontend
- [X] Real-time status polling
- [X] Dashboard view
- [X] Recordings management
- [X] Manual control
- [X] Settings view

### Phase 4: WordPress Integration ✅

- [X] REST API authentication (Application Passwords)
- [X] Image upload to media library
- [X] Post creation with embedded images
- [X] Error handling and retry logic
- [X] Category management
- [X] Draft/publish status control

### Phase 5: Production Deployment 📋

- [ ] Docker build
- [ ] docker-compose integration
- [ ] End-to-end deployment test

---

## Phase 3: Web Interface Testing

### Start Web Server

```bash
# From python directory
cd c:/Users/StephenFewings/OneTrack\ -\ terra15\ technologies/Documents/Home/emon/emon_Suite/python

# Set PYTHONPATH and start server
set PYTHONPATH=.
python -m event_recorder.web_interface --db event_recorder/test_recordings.db --port 5001 --debug
```

**Expected output:**

```
2026-02-12 20:53:15 - event_recorder.models - INFO - Using existing database
2026-02-12 20:53:15 - __main__ - INFO - ============================================================
2026-02-12 20:53:15 - __main__ - INFO - Event Recorder Web Interface
2026-02-12 20:53:15 - __main__ - INFO - ============================================================
2026-02-12 20:53:15 - __main__ - INFO - Server: http://0.0.0.0:5001
2026-02-12 20:53:15 - __main__ - INFO - Open your browser and navigate to http://localhost:5001
```

### Test API Endpoints

```bash
# Status endpoint
curl http://localhost:5001/api/status

# List all recordings
curl http://localhost:5001/api/recordings

# Get specific recording
curl http://localhost:5001/api/recordings/1

# Start manual recording
curl -X POST http://localhost:5001/api/recordings \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Recording","description":"Manual test","topics":["gps/#","battery/#"]}'

# Stop recording
curl -X POST http://localhost:5001/api/recordings/1/stop
```

### Test Web UI

1. **Open Browser**: Navigate to http://localhost:5001
2. **Check Dashboard View**:

   - Purple gradient header with "Event Recorder & WordPress Publisher"
   - Status indicator (green dot = online)
   - Sidebar stats showing Total Recordings, Total Messages, DB Size
   - Active Recordings section (should show active recordings)
   - Service Status section (MQTT, Buffer Size, etc.)
   - Recent Recordings list
3. **Test Recordings View**:

   - Click "Recordings" in sidebar
   - Should display recordings in grid/list format
   - Filter by status (All, Active, Stopped, Processing, Published, Failed)
   - Click on a recording to view details in modal
   - Modal shows: Name, Status, Timestamps, Message Count, Images
4. **Test Manual Control**:

   - Click "Manual Control" in sidebar
   - Fill out "Start New Recording" form:
     - Recording Name: "My Test Track"
     - Description: "Testing manual recording"
     - Topics: "gps/#\nbattery/#"
   - Click "Start Recording"
   - Should see toast notification
   - Check Dashboard - recording should appear in Active Recordings
5. **Test Settings View**:

   - Click "Settings" in sidebar
   - Should show version info and configuration details
6. **Test Real-time Polling**:

   - Open browser DevTools (F12) → Network tab
   - Should see `/api/status` requests every 2 seconds
   - Status dot should pulse and show "Online"

### Verify Phase 3 Features

✓ **Flask REST API**:

- All endpoints responding with JSON
- Status, Recordings, Manual control endpoints working

✓ **JavaScript SPA**:

- View switching (Dashboard, Recordings, Manual, Settings)
- Status polling every 2 seconds
- Modal dialogs for recording details
- Toast notifications for actions

✓ **Purple Gradient Theme**:

- Header gradient: #667eea → #764ba2
- Consistent styling across views
- Responsive design

✓ **Real-time Updates**:

- Status indicator updates automatically
- Sidebar stats refresh
- Active recordings update

---

## Phase 4: WordPress Integration Testing

### Prerequisites

1. **WordPress Site** (5.6+) with HTTPS enabled
2. **WordPress Account** with Administrator or Editor role
3. **Application Password** generated (see setup below)

### Setup WordPress Application Password

```bash
# 1. Log into WordPress Admin Dashboard
# 2. Go to: Users → Profile
# 3. Scroll to "Application Passwords" section
# 4. Enter name: "Event Recorder"
# 5. Click "Add New Application Password"
# 6. Copy the password: "xxxx xxxx xxxx xxxx xxxx xxxx"

# 7. Create .env file (from example)
cd c:/Users/StephenFewings/OneTrack\ -\ terra15\ technologies/Documents/Home/emon/emon_Suite/python/event_recorder
cp .env.example .env

# 8. Edit .env and add your credentials:
# WP_SITE_URL=https://yourblog.com
# WP_USERNAME=admin
# WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
```

**Important Notes:**

- Keep spaces in application password
- WordPress 5.6+ required for Application Passwords
- HTTPS required (or add `define('WP_ENVIRONMENT_TYPE', 'local');` to wp-config.php)
- User needs `upload_files` and `publish_posts` capabilities

### Test WordPress Connection

```bash
# Install Phase 4 dependencies
pip install requests python-dateutil

# Method 1: Via CLI
cd c:/Users/StephenFewings/OneTrack\ -\ terra15\ technologies/Documents/Home/emon/emon_Suite/python
set PYTHONPATH=.
python -m event_recorder.wordpress_publisher \
  --site-url "https://yourblog.com" \
  --username "admin" \
  --password "xxxx xxxx xxxx xxxx xxxx xxxx"

# Expected output:
# ✓ Connected as YourName (['administrator', 'editor'])
```

```bash
# Method 2: Via Web API
# (with web server running on port 5001)
curl http://localhost:5001/api/wordpress/test

# Expected JSON:
# {"success": true, "message": "Connected as YourName (['administrator'])"}
```

### Test Publishing via Web API

```bash
# Publish an existing recording to WordPress

# 1. Start web server with WordPress configured
cd c:/Users/StephenFewings/OneTrack\ -\ terra15\ technologies/Documents/Home/emon/emon_Suite/python
set PYTHONPATH=.

# Load environment variables and start (assuming you have .env configured)
python -m event_recorder.web_interface \
  --db event_recorder/test_recordings.db \
  --port 5001

# 2. In another terminal, publish recording
curl -X POST http://localhost:5001/api/recordings/1/publish \
  -H "Content-Type: application/json" \
  -d "{\"category\": \"Track Logs\", \"auto_publish\": false}"

# Expected response:
# {
#   "success": true,
#   "post": {
#     "id": 123,
#     "title": "Test Track - 2026-02-12 17:44:33",
#     "link": "https://yourblog.com/?p=123",
#     "status": "draft",
#     "date": "2026-02-12T20:00:00"
#   }
# }
```

### Verify WordPress Post

1. **Check WordPress Admin:**

   - Go to: Posts → All Posts
   - Should see new post in drafts: "Test Track - 2026-02-12 ..."
   - Status: Draft
2. **Check Post Content:**

   - Click on the draft post
   - Should see:
     - Track summary text
     - Embedded images (speed, battery, route map, statistics)
     - Featured image set (first plot)
     - Category: "Track Logs"
3. **Check Media Library:**

   - Go to: Media → Library
   - Should see uploaded images (4 plots from test recording)
   - Each image should have caption

### Troubleshooting

**Error: "Authentication failed"**

```bash
# Verify credentials are set
echo $WP_SITE_URL
echo $WP_USERNAME
echo $WP_APP_PASSWORD

# Test with curl
curl -u "$WP_USERNAME:$WP_APP_PASSWORD" \
  https://yourblog.com/wp-json/wp/v2/users/me
```

**Error: "Connection failed"**

```bash
# Test site accessibility
curl -I https://yourblog.com/wp-json/

# Should return: HTTP/1.1 200 OK
```

**Error: "User does not have permission"**

- Check user role (Administrator or Editor required)
- Verify `upload_files` and `publish_posts` capabilities

**Error: "Application Passwords not available"**

- Update WordPress to 5.6+
- Enable HTTPS or set `WP_ENVIRONMENT_TYPE` in wp-config.php
- Check if disabled by security plugin

### Verify Phase 4 Features

✓ **WordPress Authentication**:

- Application password authentication working
- Connection test returns user info

✓ **Media Upload**:

- Images uploaded to WordPress media library
- Captions set correctly
- MIME types detected properly

✓ **Post Creation**:

- Posts created with title, content, status
- Categories created/assigned automatically
- Featured image set (first image)
- Excerpt generated

✓ **Error Handling**:

- Retry logic with exponential backoff
- Failed recordings marked with error message
- Database updated with WordPress URL

✓ **Configuration**:

- Environment variable substitution
- Multiple site support (optional)
- Custom templates per event

---

## Next Steps

After successful Phase 1-4 testing:

1. **Proceed to Phase 5:** Production Deployment
   - Multi-platform Docker build
   - docker-compose integration
   - End-to-end deployment testing
   - Documentation finalization

---

## Continuous Testing

Run integration test before each phase to ensure no regressions:

```bash
# Quick smoke test (30 seconds)
python test_full_cycle.py

# With coverage (requires pytest-cov)
pytest tests/ --cov=event_recorder --cov-report=html
```
