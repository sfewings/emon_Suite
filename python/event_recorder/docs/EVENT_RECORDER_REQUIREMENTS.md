# Event Recorder & WordPress Publisher - Living Requirements

**Version:** 0.1.0
**Last Updated:** 2026-02-12
**Owner:** Stephen Fewings
**Status:** In Development - Phase 1

---

## Overview

The Event Recorder is an autonomous service that monitors GPS position via MQTT, automatically records vehicle drive sessions (battery, GPS, temperature, motor data), generates comprehensive plots and statistics, and publishes results to WordPress blog posts. This enables automatic documentation of vehicle performance without manual data collection.

**Primary Use Case:** Vehicle drive logging
**Integration:** Standalone containerized service following emon_Suite patterns

---

## Requirements Status

### Phase 1: Core Recording Infrastructure ✅🚧

- [ ] **FR-1:** GPS position monitoring
- [ ] **FR-2:** MQTT data recording with buffering
- [ ] **FR-3:** SQLite data persistence
- [ ] **TR-1:** Power outage recovery
- [ ] **TR-2:** Configuration management

### Phase 2: Data Processing 📋

- [ ] **FR-4:** Time-series line plots (matplotlib)
- [ ] **FR-5:** Multi-metric comparison plots
- [ ] **FR-6:** GPS route map visualization (folium)
- [ ] **FR-7:** Statistics calculation and summary table
- [ ] **TR-3:** Plot generation pipeline

### Phase 3: Web Interface 📋

- [ ] **FR-8:** Flask REST API endpoints
- [ ] **FR-9:** Dashboard with real-time status
- [ ] **FR-10:** Recordings history view
- [ ] **FR-11:** Configuration editor
- [ ] **FR-12:** Manual recording control
- [ ] **FR-13:** Image upload functionality

### Phase 4: WordPress Integration 📋

- [ ] **FR-14:** WordPress REST API authentication (app passwords)
- [ ] **FR-15:** Media upload to WordPress
- [ ] **FR-16:** Blog post creation with embedded images
- [ ] **FR-17:** Automatic publishing after recording
- [ ] **TR-4:** Error handling and retry logic

### Phase 5: Production Deployment 📋

- [ ] **TR-5:** Multi-platform Docker image
- [ ] **TR-6:** docker-compose.yml integration
- [ ] **TR-7:** Health checks
- [ ] **TR-8:** End-to-end testing
- [ ] **DOC-1:** Deployment documentation
- [ ] **DOC-2:** Configuration examples

---

## Functional Requirements

### FR-1: GPS Position Monitoring

**Priority:** Must Have
**Status:** 📋 Pending (Phase 1)
**Description:** Monitor GPS latitude and longitude topics to detect vehicle movement

**Acceptance Criteria:**

- [ ] Subscribe to `gps/latitude/0` and `gps/longitude/0` MQTT topics
- [ ] Calculate distance between successive GPS readings using Haversine formula
- [ ] Track position changes with configurable polling interval
- [ ] Handle missing or malformed GPS messages gracefully

**Technical Details:**

- Use direct paho-mqtt client (not emon_mqtt.py)
- Haversine formula for distance: handles Earth's curvature
- Store last known position in memory for comparison

---

### FR-2: MQTT Data Recording

**Priority:** Must Have
**Status:** 📋 Pending (Phase 1)
**Description:** Record MQTT messages from multiple topics during active recording sessions

**Acceptance Criteria:**

- [ ] Subscribe to wildcard topics (e.g., `battery/#`, `gps/#`)
- [ ] Buffer messages in memory (batch size: 1000 or 5-second flush)
- [ ] Store raw MQTT payloads (topic + payload + timestamp)
- [ ] Handle high-frequency messages (100+ msg/sec)
- [ ] Support dynamic topic subscription based on configuration

**Technical Details:**

- Message buffer class with auto-flush
- Batch writes to SQLite for performance
- Maximum buffer size limit to prevent memory overflow

---

### FR-3: SQLite Data Persistence

**Priority:** Must Have
**Status:** 📋 Pending (Phase 1)
**Description:** Store recording metadata and MQTT messages in SQLite database

**Acceptance Criteria:**

- [ ] Create database schema with 4 tables (recordings, recording_data, recording_images, configurations)
- [ ] Enable WAL (Write-Ahead Logging) mode for crash resilience
- [ ] Create indexes on recording_id and timestamp for query performance
- [ ] Support concurrent reads during active recording
- [ ] Database file location: `/data/recordings.db`

**Schema:**

```sql
-- recordings: Session metadata
CREATE TABLE recordings (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT CHECK(status IN ('active', 'stopped', 'processing', 'published', 'failed')),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    trigger_type TEXT,
    wordpress_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- recording_data: MQTT messages
CREATE TABLE recording_data (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    topic TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (recording_id) REFERENCES recordings(id)
);
CREATE INDEX idx_recording_data_recording_id ON recording_data(recording_id);
CREATE INDEX idx_recording_data_timestamp ON recording_data(timestamp);

-- recording_images: Generated plots and uploads
CREATE TABLE recording_images (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    image_type TEXT CHECK(image_type IN ('plot', 'user_upload')),
    caption TEXT,
    FOREIGN KEY (recording_id) REFERENCES recordings(id)
);

-- configurations: Event trigger definitions
CREATE TABLE configurations (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    monitor_topics TEXT NOT NULL,
    start_condition TEXT NOT NULL,
    stop_condition TEXT NOT NULL,
    record_topics TEXT NOT NULL,
    plot_config TEXT,
    enabled BOOLEAN DEFAULT 1
);
```

---

### FR-4: Time-Series Line Plots

**Priority:** Must Have
**Status:** 📋 Pending (Phase 2)
**Description:** Generate line plots showing single metrics over time (e.g., speed, voltage)

**Acceptance Criteria:**

- [ ] Use matplotlib for plot generation
- [ ] Plot dimensions: 12" x 6" at 150 DPI
- [ ] Include title, axis labels, grid
- [ ] Format x-axis as time (HH:MM:SS)
- [ ] Save as PNG to `/data/plots/{recording_id}/`
- [ ] Use color scheme: #667eea (purple) for consistency

**Example Topics:**

- `gps/speed/0` → "Speed Over Time"
- `battery/voltage/0/0` → "Battery Voltage"
- `temperature/bms/0` → "BMS Temperature"

---

### FR-5: Multi-Metric Comparison Plots

**Priority:** Must Have
**Status:** 📋 Pending (Phase 2)
**Description:** Generate plots with multiple metrics on same axes for comparison

**Acceptance Criteria:**

- [ ] Support multiple topics per plot
- [ ] Include legend with labeled lines
- [ ] Use distinct colors for each metric
- [ ] Handle different scales (optional: dual y-axes)

**Example:**

- Compare battery banks: `battery/power/0/0` vs `battery/power/0/1`

---

### FR-6: GPS Route Map

**Priority:** Must Have
**Status:** 📋 Pending (Phase 2)
**Description:** Generate map visualization showing GPS route with start/end markers

**Acceptance Criteria:**

- [ ] Use folium library for map generation
- [ ] Plot route as polyline on OpenStreetMap tiles
- [ ] Add start marker (green) and end marker (red)
- [ ] Export map as PNG (requires selenium/headless browser)
- [ ] Auto-zoom to fit route bounds

**Technical Challenge:**

- folium generates interactive HTML maps
- Need headless browser (selenium + geckodriver/chromedriver) to capture PNG
- Alternative: Use matplotlib basemap (simpler but lower quality)

---

### FR-7: Statistics Summary

**Priority:** Must Have
**Status:** 📋 Pending (Phase 2)
**Description:** Calculate statistics and generate summary table as image

**Acceptance Criteria:**

- [ ] Calculate for each configured metric: min, max, mean, median
- [ ] GPS-derived: total distance (Haversine), duration
- [ ] Energy: total Wh from power * time integration
- [ ] Generate table as matplotlib figure
- [ ] Format values with appropriate units and precision

**Statistics:**

- Speed: max, average
- Distance: total km (from GPS coordinates)
- Power: min, max, average, total energy (Wh)
- Duration: total time (HH:MM:SS format)

---

### FR-8 to FR-17: [Detailed requirements for Phases 3-4]

*(To be expanded as implementation progresses)*

---

## Technical Requirements

### TR-1: Power Outage Recovery

**Priority:** Must Have
**Status:** 📋 Pending (Phase 1)
**Description:** Detect and recover from service interruptions (power loss, container restart)

**Acceptance Criteria:**

- [ ] On startup, query `SELECT * FROM recordings WHERE status='active'`
- [ ] For each interrupted recording:
  - [ ] Check current GPS position to determine if still moving
  - [ ] Resume recording if vehicle moving
  - [ ] Move to 'processing' state if vehicle stopped
- [ ] Process any recordings stuck in 'stopped' or 'processing' states
- [ ] Maximum data loss: 5 seconds (buffer flush interval)

**Recovery Logic:**

```python
def recover_interrupted_recordings():
    active_recordings = db.query("SELECT * FROM recordings WHERE status='active'")
    for recording in active_recordings:
        current_gps = get_current_gps_position()
        if is_moving(current_gps):
            resume_recording(recording)
        else:
            move_to_processing(recording)
```

---

### TR-2: Configuration Management

**Priority:** Must Have
**Status:** 📋 Pending (Phase 1)
**Description:** Load and manage YAML configuration files with time-based selection

**Acceptance Criteria:**

- [ ] Load main config: `/config/event_recorder_config.yml`
- [ ] Load event configs from: `/config/events/*.yml`
- [ ] Support time-based config selection (YYYYMMDD-HHMM.yml pattern)
- [ ] Fallback to default config if no dated file matches
- [ ] Validate YAML syntax on load
- [ ] Support environment variable substitution (${VAR_NAME})

**Configuration Hierarchy:**

1. Main service config (service settings, WordPress, plots)
2. Event configs (trigger conditions, recording topics)
3. Environment variables (.env file)

---

### TR-3 to TR-8: [Technical requirements for Phases 2-5]

*(To be expanded as implementation progresses)*

---

## Change Log

### 2026-02-12: Initial Requirements Definition

**Source:** User consultation and codebase exploration
**Decisions:**

- Primary use case: Vehicle drive logging
- GPS monitoring: latitude/longitude topics for movement detection
- Start condition: Movement > 20m for 10 seconds
- Stop condition: Stationary > 60 seconds
- Plot types: Time-series line, multi-metric comparison, GPS route map, statistics table
- WordPress: REST API with application passwords (manual review before publish)

**Architecture Choices:**

- SQLite (not InfluxDB) - simpler deployment, adequate performance
- Direct paho-mqtt (not emon_mqtt.py) - need wildcard subscriptions
- matplotlib + folium (not plotly) - static PNGs for WordPress
- Polling (not WebSockets) - matches existing emon_settings_web pattern

**Rationale:**

- Follow existing emon_Suite patterns for consistency
- Minimize external dependencies (no separate database service)
- Power outage recovery critical for unattended operation
- Living requirements document for tracking complex multi-phase development

---

## Notes for Claude Code Development

### Before Starting Each Phase:

1. Read this requirements document
2. Review relevant sections of implementation plan
3. Update todo list with phase-specific tasks
4. Mark requirements as "In Progress" when starting

### After Completing Features:

1. Mark requirements as "Implemented ✅"
2. Update change log with any design decisions
3. Add acceptance criteria checkboxes
4. Document any deviations from original plan

### When User Requests Changes:

1. Add to change log with date, requester, rationale
2. Update affected requirements
3. Estimate implementation effort
4. Update implementation plan if needed

---

## Questions & Decisions Pending

### Q1: Folium PNG Export - Headless Browser?

**Question:** Folium generates HTML maps. Need headless browser (selenium) to capture PNG. Is this acceptable?
**Alternatives:**

- matplotlib basemap (simpler, lower quality)
- Save as interactive HTML (not suitable for WordPress)
- Use static map API (Google/Mapbox) with API key

**Decision:** *Pending - to be decided during Phase 2*

---

### Q2: Multiple Simultaneous Recordings?

**Question:** Should service support multiple recordings running at same time?
**Current Plan:** Single recording at a time (simpler state management)
**Use Case:** Could have multiple trigger configs (solar events + drive logging)

**Decision:** *Pending - initial version: single recording, multi-recording in future*

---

### Q3: Data Retention Policy?

**Question:** How long to keep old recordings? Database could grow large.
**Options:**

- Manual deletion only
- Auto-delete after N days
- Archive to compressed files
- Export to InfluxDB then delete

**Decision:** *Pending - initial version: manual deletion, add retention policy later*

---

## Implementation Progress

### Phase 1: Core Recording Infrastructure

**Timeline:** Week 1-2
**Status:** 🚧 In Progress
**Started:** 2026-02-12

#### Completed Tasks:

- [X] Living requirements document created

#### In Progress:

- [ ] Project structure creation
- [ ] SQLite schema implementation
- [ ] Configuration manager
- [ ] MQTT data recorder
- [ ] GPS trigger monitor
- [ ] Recovery manager
- [ ] Main service orchestrator

#### Next Steps:

1. Create `/python/event_recorder/` directory structure
2. Implement `models.py` with SQLite schema
3. Implement `config_manager.py` for YAML loading
4. Implement `data_recorder.py` for MQTT subscription

---

### Phase 2: Data Processing

**Timeline:** Week 3
**Status:** 📋 Planned

---

### Phase 3: Web Interface

**Timeline:** Week 4-5
**Status:** 📋 Planned

---

### Phase 4: WordPress Integration

**Timeline:** Week 6
**Status:** 📋 Planned

---

### Phase 5: Production Deployment

**Timeline:** Week 7
**Status:** 📋 Planned

---

## References

- **Implementation Plan:** `C:\Users\StephenFewings\.claude\plans\rosy-plotting-lovelace.md`
- **Existing Patterns:**
  - Flask REST API: `/python/emon_settings_web/emon_settings_web.py`
  - MQTT Subscriber: `/python/emonMQTTToInflux.py`
  - Config Management: `/python/pyEmon/pyemonlib/emon_settings.py`
- **Docker Deployment:** `/provisioning/shannstainable/docker-compose.yml`

---

**Last Updated:** 2026-02-12 by Claude Sonnet 4.5
**Next Review:** After Phase 1 completion
