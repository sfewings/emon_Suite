# Event Recorder & WordPress Publisher - Living Requirements

**Version:** 0.2.0
**Last Updated:** 2026-03-05
**Owner:** Stephen Fewings
**Status:** Phases 1–4 Complete · Phase 5 In Progress

---

## Overview

The Event Recorder is an autonomous service that monitors GPS position via MQTT, automatically records vessel track sessions (battery, GPS, temperature, motor data), generates comprehensive plots and statistics, and publishes results to WordPress blog posts. This enables automatic documentation of vessel performance without manual data collection.

**Primary Use Case:** Vessel track logging
**Integration:** Standalone containerised service following emon_Suite patterns

---

## Requirements Status

### Phase 1: Core Recording Infrastructure ✅ Complete

- [x] **FR-1:** GPS position monitoring
- [x] **FR-2:** MQTT data recording with buffering
- [x] **FR-3:** SQLite data persistence
- [x] **TR-1:** Power outage recovery
- [x] **TR-2:** Configuration management

### Phase 2: Data Processing ✅ Complete

- [x] **FR-4:** Time-series line plots (matplotlib)
- [x] **FR-5:** Multi-metric comparison plots
- [x] **FR-6:** GPS route map visualisation (folium + Selenium)
- [x] **FR-7:** Statistics calculation and summary table
- [x] **FR-18:** CSV / KML / GPX export file generation
- [x] **TR-3:** Plot generation pipeline

### Phase 3: Web Interface ✅ Complete

- [x] **FR-8:** Flask REST API endpoints
- [x] **FR-9:** Dashboard with real-time status
- [x] **FR-10:** Recordings history view
- [x] **FR-11:** Configuration editor
- [x] **FR-12:** Manual recording control
- [x] **FR-13:** Image upload functionality
- [x] **FR-19:** Mobile photo upload page with by-line captions

### Phase 4: WordPress Integration ✅ Complete

- [x] **FR-14:** WordPress REST API authentication (app passwords)
- [x] **FR-15:** Media upload to WordPress
- [x] **FR-16:** Blog post creation with embedded images and downloads
- [x] **FR-17:** Automatic publishing after recording
- [x] **FR-20:** WordPress KML/GPX MIME type support (mu-plugin)
- [x] **TR-4:** Error handling and retry logic

### Phase 5: Production Deployment 🚧 In Progress

- [x] **TR-5:** Multi-platform Docker image
- [x] **TR-6:** docker-compose.yml test environment
- [ ] **TR-7:** Health checks
- [x] **TR-8:** End-to-end test suite
- [x] **DOC-1:** Deployment documentation
- [x] **DOC-2:** Configuration examples

---

## Functional Requirements

### FR-1: GPS Position Monitoring

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Monitor GPS latitude and longitude topics to detect vessel movement

**Acceptance Criteria:**

- [x] Subscribe to `gps/latitude/0` and `gps/longitude/0` MQTT topics
- [x] Calculate distance between successive GPS readings using Haversine formula
- [x] Track position changes with configurable polling interval
- [x] Handle missing or malformed GPS messages gracefully

**Implementation Notes:**

- Uses anchor-based position comparison: stores a reference "anchor" point and measures distance from it, then resets anchor once movement threshold is confirmed. This is more reliable than consecutive-point comparison at typical GPS update rates.
- Start condition: movement > 20 m sustained for 10 seconds
- Stop condition: stationary < 5 m for 60 seconds
- State machine: `idle → active → stopping → stopped`
- Implemented in `trigger_monitor.py`

---

### FR-2: MQTT Data Recording

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Record MQTT messages from multiple topics during active recording sessions

**Acceptance Criteria:**

- [x] Subscribe to wildcard topics (e.g., `battery/#`, `gps/#`)
- [x] Buffer messages in memory (batch size: 1000 or 5-second flush)
- [x] Store raw MQTT payloads (topic + payload + timestamp)
- [x] Handle high-frequency messages (100+ msg/sec)
- [x] Support dynamic topic subscription based on configuration

**Implementation Notes:**

- `MessageBuffer` class with configurable `max_size` (default 1000) and `flush_interval` (default 5 s)
- Batch `INSERT` to SQLite using `executemany` for performance
- Separate MQTT client from trigger monitor client to allow independent subscriptions
- Implemented in `data_recorder.py`

---

### FR-3: SQLite Data Persistence

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17, schema updated 2026-02-20)
**Description:** Store recording metadata and MQTT messages in SQLite database

**Acceptance Criteria:**

- [x] Create database schema with 4 tables (recordings, recording_data, recording_images, configurations)
- [x] Enable WAL (Write-Ahead Logging) mode for crash resilience
- [x] Create indexes on recording_id and timestamp for query performance
- [x] Support concurrent reads during active recording
- [x] Database file location: `/data/recordings.db`

**Schema:**

```sql
-- recordings: Session metadata
CREATE TABLE recordings (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT CHECK(status IN ('active', 'stopped', 'processing', 'processed', 'published', 'failed')),
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

-- recording_images: Generated plots and user uploads
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

**Schema changes since initial design:**

- `status` CHECK constraint extended with `'processed'` state: represents a recording where data processing (plots, statistics, exports) is complete but the post has not yet been published to WordPress. This state enables the Publish button in the web UI.

---

### FR-4: Time-Series Line Plots

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Generate line plots showing single metrics over time (e.g., speed, voltage)

**Acceptance Criteria:**

- [x] Use matplotlib for plot generation
- [x] Plot dimensions: 12" x 6" at 150 DPI
- [x] Include title, axis labels, grid
- [x] Format x-axis as time (HH:MM:SS)
- [x] Save as PNG to `/data/plots/{recording_id}/`
- [x] Use colour scheme: #667eea (purple) for consistency

**Implementation Notes:**

- Auto-generates a plot for every topic group defined in config `plot_config`
- X-axis timestamps converted to seconds-offset from recording start and formatted as `HH:MM:SS`
- Implemented in `data_processor.py → _generate_time_series_plot()`

---

### FR-5: Multi-Metric Comparison Plots

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Generate plots with multiple metrics on the same axes for comparison

**Acceptance Criteria:**

- [x] Support multiple topics per plot
- [x] Include legend with labelled lines
- [x] Use distinct colours for each metric
- [x] Handle different scales (optional: dual y-axes)

**Implementation Notes:**

- Plot config accepts a list of topics; each is rendered as a separate line with auto-assigned colour
- Legend placed in best position by matplotlib
- Used for multi-battery bank comparisons (e.g., `battery/power/0/0` vs `battery/power/0/1`)

---

### FR-6: GPS Route Map

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17, bug fixes 2026-02-20)
**Description:** Generate map visualisation showing GPS route with start/end markers

**Acceptance Criteria:**

- [x] Use folium library for map generation
- [x] Plot route as polyline on OpenStreetMap tiles
- [x] Add start marker (green) and end marker (red)
- [x] Export map as PNG (headless Chromium via Selenium)
- [x] Auto-zoom to fit route bounds

**Implementation Notes:**

- folium generates an interactive HTML map; Selenium with headless Chromium captures it as PNG
- Chromium installed in Docker image via `apt-get install chromium` (not chromium-driver from pip) — resolved "Chromium not found" error in container
- GPS coordinates extracted using nearest-neighbour timestamp lookup (`bisect` module) rather than exact-match join — resolves dropped points when latitude and longitude timestamps don't align perfectly
- Duplicate route map bug fixed: when multiple GPS streams exist (e.g., two GPS units), each stream now generates its own named route map file rather than overwriting
- `selenium.webdriver.ChromeOptions` configured with `--headless`, `--no-sandbox`, `--disable-dev-shm-usage` for Docker compatibility
- Implemented in `data_processor.py → _generate_route_map()`

**Pending question resolved:** Headless Chromium/Selenium accepted over matplotlib basemap — better map quality, no API key required.

---

### FR-7: Statistics Summary

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17, updated 2026-02-20)
**Description:** Calculate statistics and generate summary table as image

**Acceptance Criteria:**

- [x] Calculate for each configured metric: min, max, mean, median
- [x] GPS-derived: total distance (Haversine), duration
- [x] Energy: total Wh from power × time integration
- [x] Generate table as matplotlib figure
- [x] Format values with appropriate units and precision
- [x] Include recording start and end times in table

**Implementation Notes:**

- Statistics table rendered as a matplotlib `Table` object and saved as PNG
- Start time and end time rows added to top of table (added 2026-02-20)
- Duration computed from start/end timestamps
- Distance computed by summing Haversine distances between consecutive GPS fixes
- Implemented in `data_processor.py → _generate_statistics_summary()`

---

### FR-8: Flask REST API

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** REST API backend for all web UI interactions

**Acceptance Criteria:**

- [x] 11 REST endpoints covering recordings CRUD, image upload, publish, and configuration
- [x] JSON request/response throughout
- [x] CORS support for local development
- [x] Appropriate HTTP status codes

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/recordings` | List all recordings |
| GET | `/api/recordings/<id>` | Get recording detail |
| POST | `/api/recordings` | Create manual recording |
| PUT | `/api/recordings/<id>` | Update recording |
| DELETE | `/api/recordings/<id>` | Delete recording |
| POST | `/api/recordings/<id>/stop` | Stop active recording |
| POST | `/api/recordings/<id>/process` | Trigger data processing |
| POST | `/api/recordings/<id>/publish` | Publish to WordPress |
| POST | `/api/recordings/<id>/images` | Upload image (multipart) |
| GET | `/api/status` | Service status |
| GET/POST | `/api/config` | Read/write YAML config |

**Implementation Notes:**

- Implemented in `web_interface.py` using Flask
- `image_type` field (`'plot'` / `'user_upload'`) included in image list responses and passed through to the WordPress publisher
- Implemented in `web_interface.py`

---

### FR-9: Dashboard with Real-Time Status

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17, bug fix 2026-02-20)
**Description:** Live dashboard showing current service and recording state

**Acceptance Criteria:**

- [x] Display current recording status (active, stopped, etc.)
- [x] Show live elapsed duration for active recording
- [x] 2-second polling auto-refresh
- [x] Active recording card highlighted with red LIVE indicator

**Implementation Notes:**

- Duration display bug fixed: browser was computing duration using local wall clock but comparing against UTC server timestamps, causing incorrect offset. Fixed by computing duration server-side and returning elapsed seconds directly.
- Upload Photo button shown on active recording cards, linking to `/upload?recording_id=<id>`
- Implemented in `web_ui/app.js`

---

### FR-10: Recordings History View

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Paginated list of all past recordings with detail modal

**Acceptance Criteria:**

- [x] List all recordings sorted by date descending
- [x] Show status badge per recording
- [x] Modal detail view with plots, stats, and metadata
- [x] Separate Photos section (user uploads) from Data Visualisations (generated plots)

**Implementation Notes:**

- Modal separates images by `image_type`: user uploads displayed first under "Photos" heading, generated plots under "Data Visualisations"
- Publish button visible for recordings in `processed` status
- Implemented in `web_ui/app.js`

---

### FR-11: Configuration Editor

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** In-browser YAML configuration editing

**Acceptance Criteria:**

- [x] Load current config from `/api/config`
- [x] Edit in `<textarea>` with monospace font
- [x] Save via PUT/POST to `/api/config`
- [x] Validate YAML syntax before saving
- [x] Show success/error feedback

---

### FR-12: Manual Recording Control

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Allow operator to start and stop recordings manually from the web UI

**Acceptance Criteria:**

- [x] Start recording button on dashboard
- [x] Stop button on active recording card
- [x] Confirmation dialog before stopping
- [x] Status updates reflected in UI within 2 seconds

---

### FR-13: Image Upload

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Upload images to a recording from the web UI

**Acceptance Criteria:**

- [x] Multipart file upload via `POST /api/recordings/<id>/images`
- [x] Optional caption/by-line stored with image
- [x] `image_type` set to `'user_upload'` for manually uploaded images
- [x] Images appear in recording detail modal under Photos section

---

### FR-18: CSV / KML / GPX Export

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-26)
**Description:** Generate track data export files in open formats for use in mapping and analysis tools

**Acceptance Criteria:**

- [x] Generate CSV with one row per MQTT message (timestamp, topic, payload)
- [x] Generate KML with GPS route as `<LineString>` placemark
- [x] Generate GPX with GPS route as `<trkseg>` track segment
- [x] Files saved to `/data/plots/{recording_id}/` alongside plot images
- [x] Files uploaded to WordPress media library and linked in Downloads section of post
- [x] Files generated as part of the standard `process` pipeline

**Implementation Notes:**

- KML uses `application/vnd.google-earth.kml+xml` MIME type
- GPX uses `application/gpx+xml` MIME type
- WordPress blocks both MIME types by default — resolved by FR-20
- Implemented in `data_processor.py → _generate_exports()`

---

### FR-19: Mobile Photo Upload Page

**Priority:** Should Have
**Status:** ✅ Implemented (2026-03-04)
**Description:** Dedicated mobile-optimised page for uploading photos from a phone camera roll during an active recording, with an optional by-line caption

**Acceptance Criteria:**

- [x] Served at `/upload` (separate from the main SPA)
- [x] `?recording_id=<id>` URL parameter for bookmarking a specific recording
- [x] Dropdown to select any non-published recording; active recordings shown first with 🔴 LIVE badge
- [x] Large tap-friendly "Select Photo from Album" button (`<input type="file" accept="image/*">`)
- [x] Photo preview displayed before upload
- [x] Optional by-line / caption textarea
- [x] Upload POSTs to existing `POST /api/recordings/<id>/images` endpoint
- [x] Form resets on successful upload; success/error feedback displayed

**Implementation Notes:**

- Implemented as standalone `web_ui/upload.html` + `web_ui/upload.js`
- Uses `FormData` multipart for binary upload
- Active recording cards on the main dashboard include an "📷 Upload Photo" link pointing to `/upload?recording_id=<id>`
- By-line stored as `caption` in `recording_images` table
- `image_type` set to `'user_upload'`; photos appear in WordPress post under a "Photos" `<h2>` section with `<em>` captions, separate from generated plots

---

### FR-20: WordPress KML/GPX MIME Type Support

**Priority:** Must Have
**Status:** ✅ Implemented (2026-03-05)
**Description:** Allow KML and GPX files to be uploaded to the WordPress media library, which blocks these types by default

**Acceptance Criteria:**

- [x] KML files upload successfully via WordPress REST API
- [x] GPX files upload successfully via WordPress REST API
- [x] `source_url` returned by upload is used in post Downloads section
- [x] Fix persists across container restarts

**Implementation Notes:**

- Root cause: WordPress's default `upload_mimes` filter excludes `application/vnd.google-earth.kml+xml` and `application/gpx+xml`. Secondary block from `wp_check_filetype_and_ext` which uses `finfo` and returns a generic type for these formats.
- Fix: WordPress must-use plugin `mu-plugins/allow-geo-files.php` added to test environment. Must-use plugins load automatically on every request without activation.
- Plugin adds both `upload_mimes` and `wp_check_filetype_and_ext` filters.
- Mount in test `docker-compose.yml`: `./mu-plugins:/var/www/html/wp-content/mu-plugins`
- For production WordPress instances, the same plugin file must be deployed manually.
- Located at: `test_event_recorder/mu-plugins/allow-geo-files.php`

---

## Technical Requirements

### TR-1: Power Outage Recovery

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Detect and recover from service interruptions (power loss, container restart)

**Acceptance Criteria:**

- [x] On startup, query `SELECT * FROM recordings WHERE status='active'`
- [x] For each interrupted recording:
  - [x] Move to `'stopped'` state if vessel is stationary
  - [x] Resume recording if vessel is still moving
- [x] Process any recordings stuck in `'stopped'` or `'processing'` states
- [x] Maximum data loss: 5 seconds (buffer flush interval)

**Implementation Notes:**

- `RecoveryManager.recover()` called from `main.py` before normal service loop starts
- Also handles recordings stuck in `'processing'` state by re-triggering data processor
- Implemented in `recovery_manager.py`

---

### TR-2: Configuration Management

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Load and manage YAML configuration files with time-based selection

**Acceptance Criteria:**

- [x] Load main config: `/config/event_recorder_config.yml`
- [x] Load event configs from: `/config/events/*.yml`
- [x] Support time-based config selection (YYYYMMDD-HHMM.yml pattern)
- [x] Fallback to default config if no dated file matches
- [x] Validate YAML syntax on load
- [x] Support environment variable substitution (`${VAR_NAME}`)

**Implementation Notes:**

- Config files sorted by filename date descending; most recent file not newer than current date is selected
- Implemented in `config_manager.py`

---

### TR-3: Plot Generation Pipeline

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17, bugs fixed 2026-02-20)
**Description:** Automated multi-plot generation triggered after recording stops

**Acceptance Criteria:**

- [x] Generate all configured plots automatically when recording status transitions to `'stopped'`
- [x] Save all plots to `/data/plots/{recording_id}/`
- [x] Register each plot in `recording_images` table
- [x] Update recording status to `'processed'` on completion, `'failed'` on error
- [x] Generate exports (CSV, KML, GPX) in same pipeline pass

**Bug fixes applied:**

- `status` was not updating to `'processed'` after processing — fixed by ensuring the status update commit occurred after all processing steps, not only on the success path
- GPS route map not generated in auto-plot mode — fixed by ensuring the route map step ran when triggered by the recording stop event as well as manual process requests
- Start/end times not appearing in statistics table — added as first rows in table generation

---

### TR-4: Error Handling and Retry Logic

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Resilient HTTP communication with WordPress REST API

**Acceptance Criteria:**

- [x] Exponential backoff retry: 1 s, 2 s, 4 s (3 attempts)
- [x] Retry on 5xx server errors only; client errors (4xx) returned immediately
- [x] Per-operation error logging with status code and response body
- [x] Failed export uploads logged but do not abort post creation

**Implementation Notes:**

- `_retry_request()` in `wordpress_publisher.py`
- Upload failures return `None`; caller skips the failed item but continues

---

### TR-5: Multi-Platform Docker Image

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Docker image buildable for amd64 and arm64 platforms

**Acceptance Criteria:**

- [x] `Dockerfile` based on `python:3.12-slim`
- [x] Chromium and dependencies installed for folium map export
- [x] `build.sh` / `build.cmd` scripts for cross-platform buildx builds
- [x] Debug variant support (`debugpy` remote attach on port 5678)

**Implementation Notes:**

- Chromium installed via `apt-get install chromium` — the pip `chromedriver-autoinstaller` package does not work reliably in Alpine/slim images
- `DEBUG=1` environment variable enables `debugpy` listener before Flask starts

---

### TR-6: Docker Compose Test Environment

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Self-contained docker-compose environment for integration testing

**Acceptance Criteria:**

- [x] `test_event_recorder/docker-compose.yml` with all required services
- [x] Services: mosquitto, test_wordpress, test_mysql, event_recorder, emon_settings_web
- [x] Environment variables from `.env` file (WordPress credentials, MQTT host)
- [x] Data and config bind-mounted from host for persistence across restarts
- [x] `mu-plugins` directory mounted for WordPress MIME type plugin

---

### TR-7: Health Checks

**Priority:** Should Have
**Status:** 📋 Not Yet Implemented
**Description:** Docker HEALTHCHECK instructions and `/health` endpoint

---

### TR-8: End-to-End Test Suite

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Automated tests covering the full recording-to-publish cycle

**Acceptance Criteria:**

- [x] `tests/test_full_cycle.py` — full recording lifecycle
- [x] `tests/test_phase3_web.py` — REST API endpoint tests
- [x] `tests/test_wordpress.py` — WordPress publisher integration tests
- [x] `tests/test_wordpress_mock.py` — mocked WordPress API tests

---

### DOC-1: Deployment Documentation

**Priority:** Should Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Documentation sufficient for a new operator to deploy the service

**Deliverables:**

- [x] `docs/README.md` — service overview, setup, configuration reference
- [x] `test_event_recorder/README.md` — test environment setup guide
- [x] `test_event_recorder/WORDPRESS_SETUP.md` — WordPress application password setup
- [x] `docs/PROJECT_SUMMARY.md` — architecture and design decisions

---

### DOC-2: Configuration Examples

**Priority:** Should Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Commented example configuration files

**Deliverables:**

- [x] `config_examples/event_recorder_config.yml`
- [x] `config_examples/events/20260212-1000.yml`
- [x] `config_examples/wordpress_config.example.yml`
- [x] `tests/.env.example`

---

## Change Log

### 2026-03-05: Phases 1–4 Completion Update

**Source:** Post-implementation review against git log (commits f3bc3d0 – 8e2aeef)
**Updated by:** Claude Sonnet 4.6

**Summary of changes documented:**

- Marked all Phase 1–4 requirements as implemented
- Expanded FR-8 through FR-17 from placeholder stubs to full detail
- Added three new requirements not in original spec:
  - **FR-18** CSV/KML/GPX export generation
  - **FR-19** Mobile photo upload page
  - **FR-20** WordPress KML/GPX MIME type plugin
- Updated FR-3 schema: added `'processed'` to status CHECK constraint
- Documented all bug fixes applied post-initial-implementation:
  - Recording status not updating to `processed` (fbd0494)
  - GPS route map not generated in auto-plot mode (36c3a6f)
  - GPS coordinate matching using nearest-neighbour lookup (ec27332)
  - Chromium not found in Docker (b7dd20f)
  - Statistics table missing start/end time (10b4626)
  - Active recording duration UTC offset in browser (9d684a7)
  - Publish button not shown for `processed` recordings (82bf48c)
  - Duplicate route map when multiple GPS streams present (772e8d8)
- Resolved all three pending design questions (Q1, Q2, Q3)
- Added anchor-based GPS trigger approach to FR-1 notes
- Added `'vessel'` / `'track'` terminology note (renamed from `'vehicle'` / `'drive'`)
- Updated Phase 5 status: TR-5, TR-6, TR-8, DOC-1, DOC-2 complete; TR-7 (health checks) pending

---

### 2026-02-12: Initial Requirements Definition

**Source:** User consultation and codebase exploration

**Decisions:**

- Primary use case: Vessel track logging
- GPS monitoring: latitude/longitude topics for movement detection
- Start condition: Movement > 20 m for 10 seconds
- Stop condition: Stationary > 60 seconds
- Plot types: Time-series line, multi-metric comparison, GPS route map, statistics table
- WordPress: REST API with application passwords (manual review before publish)

**Architecture Choices:**

- SQLite (not InfluxDB) — simpler deployment, adequate performance
- Direct paho-mqtt (not emon_mqtt.py) — need wildcard subscriptions
- matplotlib + folium (not plotly) — static PNGs for WordPress
- Polling (not WebSockets) — matches existing emon_settings_web pattern

---

## Questions & Decisions

### Q1: Folium PNG Export — Headless Browser?

**Decision (2026-02-17):** ✅ Resolved — Headless Chromium via Selenium
- Chromium installed in Docker image (`apt-get install chromium`)
- Provides higher-quality maps than matplotlib basemap with no API key required
- `--no-sandbox`, `--disable-dev-shm-usage` required for Docker

---

### Q2: Multiple Simultaneous Recordings?

**Decision (2026-02-17):** ✅ Resolved — Single recording at a time (initial version)
- State machine enforces one active recording
- Multi-recording deferred to future enhancement if needed

---

### Q3: Data Retention Policy?

**Decision (2026-02-17):** ✅ Resolved — Manual deletion for initial version
- No automatic retention or archiving implemented
- Recordings and data remain in SQLite until manually deleted via web UI or direct DB access
- Future enhancement: configurable auto-delete after N days

---

## Implementation Progress

### Phase 1: Core Recording Infrastructure

**Status:** ✅ Complete
**Completed:** 2026-02-17

- [x] Project structure and Dockerfile
- [x] SQLite schema (`models.py`)
- [x] Configuration manager (`config_manager.py`)
- [x] MQTT data recorder (`data_recorder.py`)
- [x] GPS trigger monitor with anchor-based detection (`trigger_monitor.py`)
- [x] Power-outage recovery manager (`recovery_manager.py`)
- [x] Main service orchestrator (`main.py`)

---

### Phase 2: Data Processing

**Status:** ✅ Complete
**Completed:** 2026-02-17 (bugs fixed through 2026-02-26)

- [x] Time-series line plots (matplotlib)
- [x] Multi-metric comparison plots
- [x] GPS route map (folium + Selenium/Chromium)
- [x] Statistics summary table with start/end time
- [x] CSV / KML / GPX export generation
- [x] Haversine distance and Wh energy calculation
- [x] Nearest-neighbour GPS coordinate timestamp matching
- [x] Duplicate route map fix for multi-GPS-stream recordings

---

### Phase 3: Web Interface

**Status:** ✅ Complete
**Completed:** 2026-02-17 (additions through 2026-03-04)

- [x] Flask REST API — 11 endpoints (`web_interface.py`)
- [x] Vanilla JS SPA (`web_ui/app.js`, `index.html`, `style.css`)
- [x] Real-time dashboard with 2-second polling
- [x] Recordings history with modal detail view
- [x] YAML configuration editor
- [x] Manual start/stop recording controls
- [x] UTC timezone fix for active recording duration display
- [x] Mobile photo upload page (`upload.html`, `upload.js`)
- [x] Upload Photo button on active recording cards

---

### Phase 4: WordPress Integration

**Status:** ✅ Complete
**Completed:** 2026-02-17 (additions through 2026-03-05)

- [x] WordPress REST API with Application Password authentication
- [x] Image media upload returning `{'id', 'url'}` from `source_url`
- [x] Export file upload (CSV, KML, GPX)
- [x] Structured HTML post: Photos section, Data Visualisations section, Downloads section
- [x] User photo by-line captions displayed with `<em>` in Photos section
- [x] First generated plot used as WordPress featured image
- [x] Draft-first publish workflow
- [x] WordPress mu-plugin for KML/GPX MIME type unblocking

---

### Phase 5: Production Deployment

**Status:** 🚧 In Progress

- [x] Multi-platform Docker build scripts (`build.sh`, `build.cmd`)
- [x] Test docker-compose environment with all services
- [x] WordPress mu-plugins bind-mount in docker-compose
- [ ] Docker HEALTHCHECK instructions (TR-7)
- [x] End-to-end test suite
- [x] Deployment and configuration documentation

---

## References

- **Existing Patterns:**
  - Flask REST API: `/python/emon_settings_web/emon_settings_web.py`
  - MQTT Subscriber: `/python/emonMQTTToInflux.py`
  - Config Management: `/python/pyEmon/pyemonlib/emon_settings.py`
- **Docker Deployment:** `/provisioning/shannstainable/docker-compose.yml`
- **WordPress MIME type plugin:** `test_event_recorder/mu-plugins/allow-geo-files.php`

---

**Last Updated:** 2026-03-05 by Claude Sonnet 4.6
**Next Review:** After TR-7 (health checks) implementation and first production deployment
