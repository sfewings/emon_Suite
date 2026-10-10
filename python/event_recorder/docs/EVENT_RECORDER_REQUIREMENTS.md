# Event Recorder & WordPress Publisher - Living Requirements

**Version:** 0.4.0
**Last Updated:** 2026-10-09
**Owner:** Stephen Fewings
**Status:** Phases 1–5 complete. Phase 6 (post editor) specified, not started

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
- [x] **FR-21:** Red Shadow web UI theme with sailing background
- [x] **FR-23:** Auto-process on stop setting

### Phase 4: WordPress Integration ✅ Complete

- [x] **FR-14:** WordPress REST API authentication (app passwords)
- [x] **FR-15:** Media upload to WordPress
- [x] **FR-16:** Blog post creation with embedded images and downloads
- [x] **FR-17:** Automatic publishing after recording
- [x] **FR-20:** WordPress KML/GPX MIME type support (mu-plugin)
- [x] **TR-4:** Error handling and retry logic

### Operational Enhancements ✅ Complete

- [x] **FR-22:** MQTT recording status publishing (1 Hz)

### Phase 5: Production Deployment ✅ Complete

- [x] **TR-5:** Multi-platform Docker image
- [x] **TR-6:** docker-compose.yml test environment
- [x] **TR-7:** Health checks
- [x] **TR-8:** End-to-end test suite
- [x] **DOC-1:** Deployment documentation
- [x] **DOC-2:** Configuration examples

### Phase 6: Post Editor 📋 Specified (2026-10-09)

Foundations, needed by the editor and worth doing on their own:

- [x] **TR-9:** Foreign keys enforced, and deleting a recording removes all of it
- [x] **TR-10:** One recording service behind the triggers and the routes
- [x] **TR-11:** Publishing runs in the background and updates its own post
- [x] **TR-12:** Recording, artefact and post state kept apart
- [x] **TR-13:** Web UI runs on iOS 12
- [x] **TR-14:** Recordings survive a restart or a power cut

The editor:

- [x] **FR-24:** Post draft held as blocks, rendered once for preview and publish
- [x] **FR-25:** Ship's log default layout
- [x] **FR-26:** Log lines filled in from the data
- [x] **FR-27:** Event page at `/race/log/`, for a phone and the HUD iPad
- [x] **FR-28:** Which recording the event page opens
- [x] **FR-29:** Photo and note capture
- [x] **FR-30:** Categories and crew from the site, offered not typed
- [ ] **FR-31:** Live while recording

---

## Functional Requirements

### FR-1: GPS Position Monitoring

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17, bug fix 2026-03-05)
**Description:** Monitor GPS latitude and longitude topics to detect vessel movement

**Acceptance Criteria:**

- [x] Subscribe to `gps/latitude/0` and `gps/longitude/0` MQTT topics
- [x] Calculate distance between successive GPS readings using Haversine formula
- [x] Track position changes with configurable polling interval
- [x] Handle missing or malformed GPS messages gracefully
- [x] No false trigger on cold start when vessel is already outside anchor zone

**Implementation Notes:**

- Uses anchor-based position comparison: stores a reference "anchor" point and measures distance from it, then resets anchor once movement threshold is confirmed. This is more reliable than consecutive-point comparison at typical GPS update rates.
- Start condition: movement > 20 m sustained for 10 seconds
- Stop condition: stationary < 5 m for 60 seconds
- State machine: `idle → active → stopping → stopped`
- **Cold-start false trigger fix (2026-03-05):** The `anchor_departure` condition was firing immediately on service start if the vessel was already outside the configured anchor zone. Fixed by adding a `seen_inside_anchor` lazy flag in trigger state. The departure timer only starts after the vessel has been confirmed inside the zone at least once since service start.
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
- `recording_exports` table added (2026-02-26): tracks CSV/KML/GPX files generated per recording.
- `service_settings` table added (2026-03-06): key/value store for runtime-configurable settings (`key TEXT PRIMARY KEY, value TEXT NOT NULL`). Migrated automatically on startup for existing databases.

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
**Status:** ✅ Implemented (2026-02-17, bug fixes 2026-02-20, interactive embed 2026-03-05, offline chart + speed colouring 2026-08-27)
**Description:** Generate map visualisation showing GPS route with start/end markers, over a basemap that works without internet, coloured by speed over ground

**Acceptance Criteria:**

- [x] Plot route over the offline vector chart from enchantee_racing
- [x] Colour the track by speed over ground on a fixed 0–8 kt scale, with a colourbar
- [x] Add start marker (green) and end marker (red)
- [x] Auto-zoom to fit route bounds
- [x] Fall back to plain lat/lon axes when there is no chart, or the track leaves it
- [x] Embed interactive Leaflet/Folium OpenStreetMap map HTML in the WordPress post

**Implementation Notes:**

- GPS coordinates extracted using nearest-neighbour timestamp lookup (`bisect` module) rather than exact-match join — resolves dropped points when latitude and longitude timestamps don't align perfectly
- Duplicate route map bug fixed: when multiple GPS streams exist (e.g., two GPS units), each stream now generates its own named route map file rather than overwriting
- **Interactive WordPress embed (2026-03-05):** `wordpress_publisher._extract_folium_embed()` extracts CDN stylesheet/script tags from the folium HTML `<head>`, the map `<div>` with a fixed pixel height (replacing folium's `height: 100%`), and the initialisation `<script>` block from after `</body>`. This produces a self-contained embeddable snippet. WordPress admin users retain the `unfiltered_html` capability required to preserve `<script>` tags. The folium `.html` file is scanned from the plots directory alongside PNGs; any PNG matching the same stem is excluded from the image upload list.
- Implemented in `data_processor.py → _generate_route_map()`, `chart_map.py`, and `wordpress_publisher.py → _extract_folium_embed()`

**Offline chart and speed colouring (2026-08-27):**

- **Why:** the host has no internet on the water, so folium's OpenStreetMap tiles are unreachable exactly when a recording is processed on the boat. `enchantee_racing` already carries a vector chart of the sailing area as GeoJSON and serves it at `/api/config/<name>`.
- The PNG in the recordings modal and the WordPress post is now matplotlib over that chart, coloured by speed over ground. The interactive folium map is still generated for the post, so a reader ashore gets the OpenStreetMap view as well; it is written with an `_osm` filename suffix so it does not share a stem with the chart PNG and therefore does not exclude it from the upload list.
- **Selenium and Chromium removed.** They existed only to screenshot the folium HTML into a PNG. Nothing screenshots a browser now, so `selenium` is out of `requirements.txt` and the `chromium` / `chromium-driver` apt packages are out of the Dockerfile — several hundred MB off the image. Generating folium HTML needs no browser.
- **Dependency direction:** read-only HTTP from event_recorder to one enchantee_racing endpoint, cached on disk in `charts.cache_dir` (default `/data/charts`). Refreshed before each processing run with `If-Modified-Since`, so a regenerated chart is picked up without a restart and an unchanged one costs a 304. Every failure degrades: unreachable app → cached copy; no cache → plain axes; schema mismatch → that layer is skipped. A recording always processes, whether or not enchantee_racing is running.
- Documents fetched and their pinned schemas are in `chart_map.CHART_DOCUMENTS`. The schema check is deliberate: these are generated files, `depth` is already on its second version, and a renamed property would silently draw a blank layer.
- **Fixed 0–8 kt colour scale**, viridis, matching `enchantee_racing/static/palette.js`, which is generated from the same colormap by `scripts/gen_palette.py`. Fixed rather than per-recording so a colour means a speed and two sails can be compared; speeds above 8 kt clamp to the top colour rather than rescaling.
- Speeds come from the `gps/speed/<n>` topic belonging to the latitude topic. Coordinates and speeds are matched in one pass by `_get_gps_track()`: building them separately is wrong, because a latitude with no longitude inside the tolerance is dropped from the track and shifts every later coordinate away from its speed.
- Track colour has a white casing under it, and the axes aspect is corrected by `1/cos(latitude)`. Equal axis units squash the track east–west by about 15% at 32°S, which is enough to read a wrong bearing off the plot.
- Mark and aid *names* are deliberately not drawn: at track scale they cover the track, which is the subject. Symbols only.
- Chart layer draw order follows enchantee_racing's map page: depth bands, contours, land, structures, navaids, racing marks.
- Configured by the `charts` section of `event_recorder_config.yml`. `base_url` accepts `${ENCHANTEE_URL}`; empty falls back to `http://localhost:5002`.
- Tests: `tests/test_chart_map.py`, which needs no broker and no network.

**Single-message GPS position (2026-08-27):**

- **Why:** `pyemonlib.emon_mqtt.gpsMessage` now publishes `gps/position/<n>` carrying `{"lat":.., "lon":.., "ts":..}` as one payload. The point of the single message is that both halves of a fix are sampled together, so there is nothing to join.
- There were **four** separate joins of the latitude and longitude topics: the route map's nearest-neighbour match, and two duplicated forward-fill loops in the KML and GPX exports. They did not agree with each other. All of it is now one reader.
- `_find_gps_streams()` returns a `GpsStream` per GPS unit, keyed on the topic subnode, preferring `gps/position/<n>`. `_get_track()` returns `List[TrackFix]`, and the route map, KML, GPX and the distance statistic all consume that. Nothing else joins topics.
- `TrackFix` carries both `ts` (arrival, what other topics are matched against, since they are stamped on arrival too) and `fix_ts` (the receiver's own fix time, only `gps/position` has it). GPX `<time>` uses `fix_ts` when present, which is more accurate than when the message reached this service.
- **The split topics are still read.** Every recording already in the database has only those; the sample data has 44,513 `gps/latitude/0` rows and no `gps/position` at all. Deleting the legacy path would lose the route map, exports and distance for every existing recording. It is confined to `_read_latlon_topics()` and used only when a stream has no position topic.
- **Fixed while here:** `_calculate_gps_statistics()` asked for `gps/latitude/0` by name, so a recording carrying only `gps/position/0` reported no distance travelled at all. It now uses the first stream whatever its topics.
- **Fixed while here:** the GPX extension topics were keyed on raw database timestamp *strings* and forward-filled by string comparison. Now parsed to datetimes; comparing `"09:00:00"` against `"09:00:00.123"` lexicographically picks the wrong reading.
- `trigger_monitor` accepts both shapes too, and the example configs now monitor `gps/position/0`. This is a correctness fix and not only tidying: the monitor detects movement by Haversine distance, and between the two split messages it holds a latitude from one fix and a longitude from another. That pairing is a jump the vessel never made, which is a false trigger.
- The position topic is excluded from time-series plot groups: its payload is a JSON object, and a JSON object plotted against time is not a chart.
- Tests: `tests/test_gps_position.py`, covering both payload shapes, malformed payloads, two receivers, and the legacy path. Verified against the real 44,513-row sample database.

**Pending question resolved (2026-08-27):** the offline chart replaces headless Chromium as the source of the route map PNG. The earlier decision preferred Chromium for map quality; it was made before the no-internet case was the normal one, and a tile server the boat cannot reach produces no map at all.

---

### FR-7: Statistics Summary

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17, updated 2026-02-20, HTML table 2026-03-06)
**Description:** Calculate statistics and generate summary table

**Acceptance Criteria:**

- [x] Calculate for each configured metric: min, max, mean, median
- [x] GPS-derived: total distance (Haversine), duration
- [x] Energy: total Wh from power × time integration
- [x] Generate table as matplotlib figure (PNG for web UI modal)
- [x] Format values with appropriate units and precision
- [x] Include recording start and end times in table
- [x] Embed statistics as HTML `<table>` in WordPress post (not as uploaded image)

**Implementation Notes:**

- Statistics table rendered as a matplotlib `Table` object and saved as PNG for use in the recordings modal in the web UI
- Start time and end time rows added to top of table (added 2026-02-20)
- Duration computed from start/end timestamps
- Distance computed by summing Haversine distances between consecutive GPS fixes
- **HTML table for WordPress (2026-03-06):** `data_processor` also writes a `statistics_summary.json` sidecar file alongside the PNG. During publish, `web_interface` loads this JSON and passes it as a `statistics` parameter to `wordpress_publisher.publish_recording()`. The publisher renders it as an HTML `<table>` via `_build_statistics_table_html()`, with rows ordered: start time, end time, duration, distance, max/avg speed, energy, message count. The PNG is excluded from the WordPress media upload.
- Implemented in `data_processor.py → _generate_statistics_summary()` and `wordpress_publisher.py → _build_statistics_table_html()`

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
| GET | `/api/settings` | Get service settings |
| POST | `/api/settings` | Update service settings |
| GET | `/health` | Lightweight health check (Docker/load balancer) |

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

### FR-14: WordPress Authentication

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Authenticate with the WordPress REST API using Application Passwords

**Acceptance Criteria:**

- [x] Use WordPress Application Passwords (WordPress 5.6+)
- [x] Credentials supplied via environment variables (`WP_SITE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD`)
- [x] Connection test endpoint (`GET /api/wordpress/test`) verifies credentials before publish

**Implementation Notes:**

- `HTTPBasicAuth(username, app_password)` used on all requests to `{site_url}/wp-json/wp/v2/`
- App password is a 24-character string with spaces as generated by the WordPress admin panel
- Implemented in `wordpress_publisher.py`

---

### FR-15: WordPress Media Upload

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Upload images and export files to the WordPress media library

**Acceptance Criteria:**

- [x] Upload PNG images as `image/png`
- [x] Upload CSV, KML, GPX export files with correct MIME types
- [x] Return `source_url` for use in post content
- [x] Failed upload of any single file does not abort post creation

**Implementation Notes:**

- Multipart upload via `POST /wp-json/wp/v2/media`
- `source_url` from the response JSON provides the public URL embedded in the post
- KML and GPX upload requires FR-20 mu-plugin on the WordPress instance

---

### FR-16: WordPress Blog Post Creation

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17, updated 2026-03-06)
**Description:** Create structured WordPress blog posts from completed recordings

**Acceptance Criteria:**

- [x] Post structured as: Photos section, Data Visualisations section, Statistics table, Interactive Map, Downloads section
- [x] User-uploaded photos displayed with `<em>` by-line captions under "Photos" heading
- [x] Generated plots embedded under "Data Visualisations" heading
- [x] Statistics rendered as HTML `<table>` (not uploaded image)
- [x] Interactive Leaflet/Folium map embedded inline
- [x] Export files (CSV, KML, GPX) linked in "Downloads" section
- [x] Last user-uploaded photo used as WordPress featured image; falls back to first generated plot
- [x] Post publication date set to recording start time
- [x] Post created as draft by default (`publish_status: "draft"`)

**Implementation Notes:**

- Featured image priority (2026-03-06): user uploads are scanned for the last `image_type='user_upload'` entry; only if none exist does it fall back to the first plot. Previously always used the first plot.
- Post `date` field (ISO 8601) set to `recording['start_time']` so the WordPress post appears dated at the time the recording began, not when it was published.
- Implemented in `wordpress_publisher.py → publish_recording()` and `_build_post_content()`

---

### FR-17: Automatic Publishing After Recording

**Priority:** Must Have
**Status:** ✅ Implemented (2026-02-17)
**Description:** Automatically publish recordings to WordPress after processing completes

**Acceptance Criteria:**

- [x] `auto_publish` flag in event configuration triggers publish after process pipeline
- [x] Manual publish available via `POST /api/recordings/<id>/publish` for draft review
- [x] Recording status transitions: `stopped → processing → processed → published`

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

### FR-21: Web UI Theme — Red Shadow

**Priority:** Should Have
**Status:** ✅ Implemented (2026-03-05)
**Description:** Style the web interface to match the Red Shadow WordPress blog theme used on the vessel's site

**Acceptance Criteria:**

- [x] Red/dark colour palette consistent with Red Shadow WordPress theme
- [x] Background: sailing photo with dark overlay
- [x] Cards/widgets: semi-transparent glassmorphism style with backdrop blur
- [x] Header: red gradient consistent with site identity

**Implementation Notes:**

- CSS custom properties define the colour palette (`--primary: #e53e3e`, `--card-bg: rgba(0,0,0,0.5)`)
- Background image served as static asset; `background-attachment: fixed` for parallax effect
- Glassmorphism cards: `backdrop-filter: blur(10px)` with `rgba` background and `border: 1px solid rgba(255,255,255,0.1)`
- Implemented in `web_ui/style.css` and `index.html`

---

### FR-22: MQTT Recording Status Publishing

**Priority:** Should Have
**Status:** ✅ Implemented (2026-03-06)
**Description:** Publish the status of each active recording via MQTT every second so external displays (e.g., instrument panels, dashboards) can show live recording state

**Acceptance Criteria:**

- [x] Publish once per second while a recording is active
- [x] Topic: `event_recorder/recording/<recording_id>/status`
- [x] Payload (JSON): recording name, duration (HH:MM:SS), duration in seconds, message count, photo count, start time, status
- [x] Publishing does not block or slow down recording

**Implementation Notes:**

- Dedicated paho-mqtt client (`_status_mqtt_client`) separate from the data recording client; connected with `loop_start()` in a daemon thread
- `_status_publisher_loop()` runs in a daemon thread, snapshots `active_recordings` each iteration to avoid race conditions with trigger callbacks
- `_publish_recording_status()` queries database for recording metadata and counts on each call; QoS 0, no retain
- Payload example: `{"recording_id": 5, "name": "Track 2026-03-06", "duration": "01:23:45", "duration_seconds": 5025, "message_count": 18432, "photo_count": 3, "start_time": "2026-03-06 ...", "status": "active"}`
- Implemented in `main.py`

---

### FR-23: Auto-Process on Stop Setting

**Priority:** Should Have
**Status:** ✅ Implemented (2026-03-06)
**Description:** User-configurable setting to automatically trigger data processing as soon as a recording stops, without requiring a manual press of the Process button

**Acceptance Criteria:**

- [x] Toggle switch on Settings page ("Recording Behaviour" card)
- [x] Setting persisted in database (`service_settings` table, key `auto_process_on_stop`)
- [x] When enabled, processing starts automatically in a background thread when recording stops
- [x] Processing failure logged but does not crash the service
- [x] Setting survives service restarts (persisted in SQLite, not in memory)

**Implementation Notes:**

- `service_settings` table: key/value store added to SQLite schema via migration for existing databases
- `database.get_setting()` / `database.set_setting()` in `models.py`
- `GET /api/settings` and `POST /api/settings` in `web_interface.py`
- `_auto_process_recording(recording_id)` in `main.py` runs in a `daemon=True` thread; instantiates `DataProcessor` inline (same pattern as the manual process endpoint) to avoid circular imports
- Toggle switch in `index.html` with Red Shadow CSS toggle style (active state uses `#e53e3e`)
- `loadSettings()` and `saveAutoProcessSetting()` in `app.js`; settings tab loads both WordPress status and service settings on navigation

---

### Phase 6 background: what the posts on enchantee.org actually look like

Phase 6 replaces a workflow that is already happening by hand. Track Log posts are
published and then reworked in wp-admin: the 7-Oct-2026 Track Log was retitled ("Terra15
software team Crew"), had the crew and a story typed into its description, gained a photo
through the classic editor, and was given the Twilight category. The editor exists so that
work is done on the boat, on the day, before the post goes out.

What it should produce was read from the 40 most recent posts outside Track Logs
(Dec 2025 to Aug 2026). They follow one pattern closely enough to be the default layout:

- The **crew** as the first paragraph ("Henry, Steve"), then the **time** ("5:30-8:20"),
  then often the **wind** ("NNE 12-14kts"), each its own short paragraph.
- **One to three short paragraphs** of story. The median is about 40 words, and many
  posts are under 20.
- **Zero to five photos**, full width, as core image blocks (`size-large`,
  `wp-image-NNN`), almost never captioned. Several are phone screenshots of the
  instruments.
- **No** headings, galleries, tags, featured image or `<!--more-->` break.
- **Two categories** as a rule: Ship's Log plus one of Twilight, Club event, Rottnest,
  Dolphins or Whales. Days off the water use Arduino, Maintenance or No Sail.

A Track Log post is 45 to 117 KB of HTML. A hand-written post is about 2 KB. The gap
between the two is what FR-25 closes.

The site is behind Apache Basic auth (`docs/APACHE_HTACCESS_AUTH_FIX.md`), which is why
none of this was visible from outside.

---

### FR-24: Post Draft Held as Blocks

**Priority:** Must Have
**Status:** ✅ Implemented (2026-10-09), with the differences noted below
**Description:** Each recording that is going to become a post has a draft, stored as an
ordered list of blocks rather than as HTML, and a single renderer turns that draft into
WordPress block markup for both the preview and the published post

**Acceptance Criteria:**

- [x] `post_drafts` gains the draft: `title`, `excerpt`, `categories` (JSON),
      `crew` (JSON), `story`, `wind`, `blocks` (JSON), `revision`. `wp_post_id`,
      `wp_modified`, `post_state` came with TR-11 and TR-12
- [x] Two kinds of block, in `post_renderer.py`:
  - **Content blocks:** `paragraph`, `photo`, `note`, `more`
  - **Auto blocks:** `track_summary`, `crew_photos`, `log_lines`, `story`, `photos`,
        `route_map`, `statistics`, `interactive_map`, `charts`, `downloads`
- [x] Auto blocks are references, re-rendered from current data on every preview and
      publish, and can be moved or removed like any other
- [x] `post_renderer.render()` replaces `_build_post_content()`, which now calls it.
      Preview and publish draw from the same gathered inputs
      (`RecordingService._gather()`); they differ only in the URLs and attachment ids
      in the `PostContext`
- [x] Delimited core blocks: `wp:paragraph`, `wp:heading`, `wp:image` (with an
      attachment id: `{"id":N,"sizeSlug":"large"}`, `wp-image-N` and the 1024 px URL),
      `wp:list`, `wp:more`, `wp:html`
- [x] A recording with no draft publishes as today: the Track Log layout is the default
      until FR-25 is approved. The draft is stored on first edit
- [x] `GET/PUT /api/recordings/<id>/draft`. A save names the revision it is based on
      and is refused (409, with the current draft) if another has happened since
- [x] `GET /preview?id=<id>[&layout=track_log|ship_log]`: the post as a page
- [x] `tests/test_post_renderer.py`

**Differences from the specification:**

- **Statistics are a `wp:html` block, not `wp:table`.** A core table block cannot keep
  the inline styles the posts' table has, so it would have looked different. Revisit if
  the table should take the theme's own styling.
- **Categories are stored as names, not WordPress ids,** because the publisher resolves
  names today. FR-30, which brings the site's real category list, is the place to
  switch.
- **`story` and `wind` are draft fields** with auto blocks that read them, rather than
  paragraph blocks. That fits FR-27's one Story textarea; a `paragraph` block exists for
  text placed anywhere else.
- **The preview is plain-styled, not the red-shadow theme.** Vendoring the theme CSS
  needs it fetched from enchantee.org; that is left for the event page (FR-27). The
  preview draws the more-break as a dashed line so what the home page shows is visible.
- **No `featured_image_id` yet.** The existing rule (last crew photo, else the route
  map) is kept until FR-27 has a way to choose.

**Implementation Notes:**

- **Verified identical to today's post.** Recording 5 on the dev rig, rendered by the
  pre-FR-24 builder taken from git and by the Track Log layout, with block comments and
  editor classes stripped: identical to a reader, 61,289 characters each, a crew photo
  with an escaped caption included. The only intended difference appears once images are
  uploaded: the large size and the attachment id, so WordPress adds `srcset`.
- **Verified against WordPress:** a ship's-log draft published to the dev rig's blog
  (post 58), and WordPress's own `parse_blocks()` reads it as `core/paragraph` x5,
  `core/image`, `core/more`, then the data sections, with the title and three
  categories from the draft. Whether the block editor opens every block without a
  validation warning needs a browser; not yet checked.
- The publisher's content helpers moved to `post_renderer.py` (`local_time`,
  `format_duration`, `apply_template`, `pop_primary_route_map`,
  `statistics_table_html`, `extract_folium_embed`); the publisher keeps thin
  delegating methods for its callers.

- The current output is raw HTML with only `wp:more` and `wp:html` delimited, so
  wp-admin opens it as one Classic block. The 7-Oct post shows what follows: the classic
  editor rewrote the photo it added as `<a><img class="alignnone ...">` with `&nbsp;`
  spacers. Real blocks keep a post editable in the block editor if it is ever opened
  there.
- Bare `<img src>` with no `wp-image-N` class is why recorder posts get no `srcset` and
  serve the full `-scaled` file. With the class and the attachment id, WordPress adds
  `srcset`, `sizes` and lazy loading itself.
- Captions stay escaped through `html.escape`, as `_build_figure_html()` does now. The
  description is currently inserted into the HTML unescaped; the renderer escapes every
  field the crew can type.
- Preview CSS: a vendored copy of the red-shadow theme stylesheet, so the preview looks
  like the site without the Pi needing the internet.

---

### FR-25: Ship's Log Default Layout

**Priority:** Must Have
**Status:** ✅ Implemented and made the default (2026-10-09, approved by the owner after
reviewing the preview). Notes join with FR-29; the wind line is typed until FR-26
**Description:** A new draft starts in the shape of the hand-written posts, with the
recorder's data below the more-break instead of in front of the story

**Acceptance Criteria:**

- [x] Default block order (`post_renderer.LAYOUT_SHIP_LOG`):
  1. `log_lines`: crew, time and wind, each its own paragraph (FR-26)
  2. `story`: the draft's story, a blank line between paragraphs; the recording's
        description until there is one
  3. `photos` (notes join here, in time order, with FR-29)
  4. `route_map`, the static chart PNG
  5. `more`
  6. `statistics`, `interactive_map`, `charts`, `downloads`
- [x] No `<h2>Track Summary</h2>` and no Date or Duration lines above the break; the
      time line carries that, as `H:MM-H:MM` local
- [x] Headings appear only below the break, over the data sections
- [x] Photos render full width, `size-large`, uncaptioned unless a caption was typed
- [x] The more-break is always present and always above any `wp:html` block, because
      the theme renders the homepage with `the_content()` and the map scripts collapse
      the listing without it (FR-16)
- [x] **No featured image** (changed 2026-10-09, after the first published test). It was
      kept at first (last crew photo, else the route map), but a theme that shows
      featured images prints it above the content, and the first photo appeared twice
      on the dev blog. The hand-written posts set none; red-shadow on enchantee.org was
      checked and shows none on a post or the home page, and the site has no sharing
      tags that would use one. The publisher sends `featured_media: 0`, so a post
      published earlier with one loses it when it is next updated

**Implementation Notes:**

- The default applies to every new draft, and to a recording with no draft when it is
  published. `post_renderer.DEFAULT_LAYOUT` is `'ship_log'`; the `post_layout` service
  setting set to `'track_log'` puts the old post back, and an unknown value falls back to
  the ship's log.
- A recording published before this as a Track Log keeps that layout on enchantee.org.
  If it is ever published again (TR-11 permitting), it goes out as a ship's log unless
  its draft says otherwise.

---

### FR-26: Log Lines Filled In From the Data

**Priority:** Should Have
**Status:** ✅ Implemented (2026-10-10). `post_suggestions.wind_line()`,
`RecordingService.computed_lines()`; tests `tests/test_log_lines.py`

**Implementation Notes:**

- **Wind:** circular mean of `anemometer/windDirection/2` on sixteen points, and the
  10th to 90th percentile of `windSpeed/2`, rounded. Blank under 60 samples or 10
  minutes of data, or when the mean direction vector is shorter than 0.6 (roughly a
  spread of 55 degrees either side). Checked against a replayed Frostbite race: the
  whole recording averaged 277 degrees, steadiness 0.96, speeds 8.2 to 12.9 kts, so
  "W 8-13 kts"; the 245 degrees of the first readings were at the mooring.
- **Crew text or the recording's.** `wind` and the new `time_line` draft field hold what
  the crew typed; empty means the recording's, which every draft carries as
  `draft['computed']` (never stored, cached for a minute). The page shows the
  recording's value until it is typed over, with where it came from beneath, and a
  "Reset to the recording's" link once it has been. Saving the recording's own value,
  or nothing, saves as no text of the crew's, so the line keeps following the data;
  while recording, the time keeps moving on.
- **Distance** is in nautical miles in the statistics table. It is not added to the log
  lines, which keep the three the hand-written posts have.
- **Crew** suggestions came with FR-30.
**Description:** The three lines typed at the top of every hand-written post are worked out
from the recording, shown filled in, and remain editable

**Acceptance Criteria:**

- [ ] **Time:** local start and end as `H:MM-H:MM`, matching "5:30-8:20". While
      recording, the start and "now"
- [ ] **Wind:** from the recorded `anemometer/windDirection/2` (TWD) and
      `anemometer/windSpeed/2` (TWS), the topics the racing app reads. Direction as a
      16-point compass name of the circular mean; speed as the 10th to 90th percentile
      range, rounded to whole knots. Format `NNE 12-14 kts`
- [ ] Wind is left blank, not guessed, when there is less than ten minutes of wind data
      or the direction spread is too wide to name one quarter
- [ ] **Crew:** chips, offered from names used in earlier drafts and in the first
      paragraph of past Ship's Log posts (FR-30). Rendered as one comma-separated
      paragraph
- [ ] Each line has an override. Once the crew types over a computed line it stops
      being recomputed, and a "reset to data" control brings the computed value back
- [ ] **Distance in nautical miles**, in the log lines and in the statistics table.
      The table currently mixes km with knots; the hand-written posts use knots

---

### FR-27: Event Page at `/race/log/`

**Priority:** Must Have
**Status:** ✅ Implemented (2026-10-09). The page at `/log/` (`event_page.py`,
`web_ui/log/`) with title, crew, time, wind, short description, story, photos, notes,
categories, preview and publish; per-field autosave; the switcher; the back link
(shown at `/race/log/` only). The nginx route `/race/log/` is in
`provisioning/enchantee/etc/nginx/sites-available/default`, and the racing app's Log
link and recording dot are built (racing DESIGN 9.13). Tests:
`tests/test_event_page.py`; the dev rig's `front` profile serves the Pi's paths on
localhost:8000. Not yet tried on the boat's iPad or a phone

**Progress notes:**

- **Per field, not per draft.** `post_drafts.field_revisions` holds the revision each
  field last changed at, and `PUT log/api/draft/<id>` saves only the fields it names
  under a write lock, so different fields from two devices never undo each other and,
  for one field, the later save stands. The page compares each field's revision on every
  5 s poll: overtaken while idle, it takes the other device's text and offers its own
  back ("Put that back"); overtaken mid-edit, it shows the other text and lets the edit
  carry on, to land as the later save.
- **One Publish button.** A recording not yet processed, or processed before it
  changed, is drawn first, inside the same background job ("Drawing the charts"). The
  dashboard's Publish gains this too.
- **Replacing the recorder's guesses** (after first testing on an iPhone, 2026-10-09):
  while Title and Short description still hold what the recorder filled in, focusing
  them selects all of it, so typing replaces it. A field the crew have saved has a
  revision and is left alone. The selection is made just after focus, and the focusing
  tap's mouseup is cancelled, because iOS Safari otherwise places the caret over it.
- **The trigger's description is not the crew's.** A triggered recording starts with its
  event's config description ("Record when vessel departs from home anchor..."), which
  had become the default short description and, through the story's fallback, the
  opening paragraph of a post nobody wrote up. A description identical to the event's
  config text is now treated as none, so the short description starts empty and the
  publisher's own excerpt is used. Any other description is the crew's and is kept.
- **The categories** are enchantee.org's surveyed list until FR-30 fetches the live one.
- **Crew suggestions** come from earlier drafts, most-sailed first. Names from past posts
  on the site come with FR-30.
**Description:** One page, built for a phone and for the iPad that shows the racing app full
time, where the crew edits the post for the current sail. It replaces `upload.html`

**Acceptance Criteria:**

- [ ] Served by event_recorder at `log/` on its own port, and reached through nginx at
      **`/race/log/`** (and `/events/log/`). See Implementation Notes for why it lives
      under the racing app's prefix
- [ ] Every URL in the page and its script is relative, so it works at both prefixes
      and on port 5000
- [ ] `?id=<recording_id>` opens a specific recording; with no `id` the page applies
      FR-28. `?from=gar|map|race|hud` records where the crew came from
- [ ] One column, top to bottom:
  1. **Header bar**, sticky: the back link, the recording state ("● REC 1:23 4.2 nm",
        or "Stopped", or "Published"), and the switcher when FR-28 finds more than one
        candidate
  2. **Photo** and **Note** buttons, large, side by side (FR-29)
  3. **Title**
  4. **Crew** chips with an add field
  5. **Time and wind** lines, filled in (FR-26)
  6. **Short description**, one line, which becomes the excerpt
  7. **Story**, a textarea in which a blank line starts a new paragraph
  8. **Notes**, timestamped, each editable, deletable or movable into the story
  9. **Photos**, a strip of thumbnails; tap for caption, position, remove, featured
  10. **Categories** chips (FR-30)
  11. **Preview** and **Publish**
- [ ] **Back link:** at the left of the header, labelled with the page the crew came
      from ("‹ GAR", "‹ Map", "‹ Race"), defaulting to GAR when `from` is missing.
      A relative link (`../gar`, `../map`, `../`), never `history.back()`, which has
      nothing to go back to after an upload or when the page was opened fresh
- [ ] The back link is shown only when the page is at `/race/log/`. At `/events/log/`
      or on port 5000 those relative links would land outside the racing app, and there
      is no racing app to go back to
- [ ] Navigation uses `location.assign` on tap as well as the anchor, as the racing app
      does, for iOS 12 (racing DESIGN 9.8.1)
- [ ] **Autosave**, no Save button: each field saves on blur and 1.5 s after typing
      stops, with a quiet "Saved" mark beside it
- [ ] **Per-field revisions:** a save carries the revision it was based on. A phone and
      the iPad editing different fields never overwrite each other; the same field
      edited on both keeps the later save and shows the other device "Changed on
      another device" with its text
- [ ] The page polls the draft every 5 s while open, so an edit on one device appears on
      the other
- [ ] **Publish** is disabled while recording, and says why. After publishing, the page
      shows the post link and the fields lock (TR-11)
- [ ] Inputs and textareas are at least 16 px, or iOS zooms the page on every focus
- [ ] Meets the iOS 12 floor in full (TR-13)
- [ ] Scrolling is allowed. The racing app's no-scrolling rule is for the cockpit
      screens; this page is used in a quiet moment, not at a mark rounding

**Implementation Notes:**

- **Why `/race/log/` and not `/events/...`:** the racing app's manifest has
  `"scope": "./"`, which behind nginx is `/race/`. That scope is what keeps GAR, Map and
  Race in one full-screen Home Screen window. A link out of it, to `/events/...`, opens
  on the phone in an overlay browser with a Done button (the exact fault recorded in
  racing DESIGN 9.8.1), while the iOS 12 iPad, which ignores scope, stays full screen.
  Serving the page inside `/race/` keeps both devices in the same window and makes the
  back link an ordinary relative link. The code stays in event_recorder; only nginx
  routes it.
- nginx, beside the existing `/race/` block. The longer prefix wins, so it needs no
  ordering care:

  ```nginx
      location /race/log/ {
          proxy_pass http://127.0.0.1:5000/log/;
          proxy_http_version 1.1;
          proxy_set_header Host              $http_host;
          proxy_set_header X-Real-IP         $remote_addr;
          proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
          # photo uploads, as on /events/
          client_max_body_size 100m;
      }
      location = /race/log { return 301 /race/log/; }
  ```

- `client_max_body_size` matters: nginx's default is 1 MB, and a phone photo is 3 to
  6 MB. `/events/` already sets 100m for the same reason.
- The page is not a racing app page and does not poll `/api/state`; it talks only to
  event_recorder. Because the page is at `log/`, a relative `api/draft` resolves to
  `/race/log/api/draft` and reaches the recorder as `/log/api/draft`. So the editor is a
  Flask blueprint mounted at `/log`, carrying its own API, thumbnails and preview under
  that prefix, all calling the same recording service (TR-10) as the existing routes.
  Nothing in the page reaches outside `log/` except the back link.

---

### FR-28: Which Recording the Event Page Opens

**Priority:** Must Have
**Status:** ✅ Implemented (2026-10-09). `RecordingService.editor_choice()`,
`recordings.event_key`, `editor_default: true` on `anchor_track_recording`; tests
`tests/test_editor_choice.py`. One refinement to rule 3: the default event is preferred
only among recordings from the same outing (started within 12 hours of the newest), so a
week-old unpublished anchor recording never displaces today's sail
**Description:** With no `id`, the event page opens the recording a sail on Enchantee is
most likely to be, without asking

**Acceptance Criteria:**

- [ ] Order of preference:
  1. an **active** recording from the event marked `editor_default` (today,
        `anchor_track_recording`)
  2. otherwise the most recent active recording of any event
  3. otherwise the newest **unpublished** recording, preferring the `editor_default`
        event
- [ ] When more than one recording qualifies, the header shows "1 of 2 ▾", which opens
      a short list (event, start time, status). Otherwise the switcher is not shown
- [ ] Recordings gain an **`event_key`** column, set in `_on_trigger_start()` from the
      event's key (`anchor_track_recording`), and `manual` for recordings started from
      the web UI
- [ ] Existing rows are backfilled once by migration from the name prefix
      (`anchor_track_recording - 2026-...`). Nothing after that reads the name to find
      the event, because the name is the post title and the crew edits it
- [ ] The preference is an event-config flag, `editor_default: true`, not a key written
      into the code. The event files are versioned by date, and a hard-coded key would
      stop matching silently on the day the event is renamed
- [ ] Only the chosen recording gets a draft automatically. Another recording of the
      same sail is reachable through the switcher and does not become a second post
      unless someone opens it and edits it

**Implementation Notes:**

- `track_recording` (movement) and `anchor_track_recording` (leaving the home anchor) are
  both enabled in `events/20260904-1200.yml`, so one sail produces two recordings. The
  anchor one spans the whole outing, which is what a post describes; the movement one
  can split a day at every long stop.
- That file's comment above `anchor_track_recording` still says "disabled by default";
  correct it when adding the flag.
- This supersedes Q2: simultaneous recordings are normal.

---

### FR-29: Photo and Note Capture

**Priority:** Must Have
**Status:** ✅ Implemented (2026-10-09). `photos.py`, `event_page.py`, `web_ui/log/`;
tests `tests/test_photos_notes.py`

**Implementation Notes:**

- **Photo button** is a `<label>` for an off-screen file input, not a button that clicks
  it: a label's tap reaches the input on every iOS, a scripted click does not. `multiple`
  is allowed; files go up one at a time with a count.
- **Kept per photo:** the original, the `_web.jpg` copy (at most 2048 px, upright, JPEG,
  which is the `image_path` stored and what goes to WordPress), and `thumbs/<name>.jpg`
  (400 px) for the page. A PNG screenshot with transparency becomes an opaque JPEG. A
  file Pillow cannot read is kept as it came, with no thumbnail.
- **Taken at:** EXIF `DateTimeOriginal`, read as Perth time (fixed +8, no daylight
  saving there) unless the photo carries `OffsetTimeOriginal`; the upload time
  otherwise. Stored in the new `recording_images.taken_at`.
- **Notes** are the draft's `notes` field, `[{ts, lat, lon, text}]`, kept in time order.
  Adding one appends inside one write-locked transaction, so notes from two devices at
  once are all kept (tested with six). The page edits, removes or moves a note into the
  story by saving the field.
- **Position** comes from the recording's own track: the `gps/position/0` fix nearest
  the note's time, within two minutes, falling back to the split latitude and longitude
  topics; none if no fix is that close.
- **In the post**, the `photos` block tells photos and notes in the order they happened,
  notes as plain paragraphs.
- **Found doing it:** the publisher built its media list without `large_url`, so posts
  were getting the full-size image despite FR-24. Fixed, and the FR-24 test now checks
  the image URL rather than only the attachment class.
**Description:** The two things the crew adds during a sail, a photo and a one-line note,
each one tap from the top of the event page, each placed on the track by its time

**Acceptance Criteria:**

- [ ] **Photo:** `<input type="file" accept="image/*">`, which on iOS offers the camera or
      the library, works over plain HTTP, and hands over HEIC as JPEG
- [ ] Uploaded photos are kept as the original plus a 2048 px web copy and a 400 px
      thumbnail, with EXIF orientation applied. The web copy is what goes to WordPress
- [ ] The photo's EXIF `DateTimeOriginal` (phone clock, usually right) places it on the
      track and orders it among notes and story; when absent, the upload time is used
- [ ] **Note:** tapping Note opens a one-line field in place, under the buttons. No
      dialog. The time and position are taken **when the field opens**, not when typing
      ends
- [ ] Notes are stored as `{ts, lat, lon, text}` content blocks, editable and
      deletable, and render in the post as paragraphs in time order after the story
- [ ] "Move into story" turns a note into a story paragraph
- [ ] A photo or note added to a published recording is refused, as uploads are now

**Implementation Notes:**

- Pillow is already in the image for matplotlib; it handles the resize and orientation.
- EXIF time is local phone time with no zone; read it as Perth local (+8), the same
  explicit offset the racing app uses, not the container's `TZ=UTC`.

---

### FR-30: Categories and Crew Offered, Not Typed

**Priority:** Should Have
**Status:** ✅ Implemented (2026-10-09). `post_suggestions.py`; rules under `post:` in
`event_recorder_config.yml`; tests `tests/test_suggestions.py`

**Implementation Notes:**

- **Learning the site:** `RecordingService.refresh_from_site()` runs at start and every
  30 minutes, in its own thread so a slow hotspot never holds the main loop. When the
  site answers it caches the category list (most used first) and the crew counts from
  the first paragraph of the latest 100 Ship's Log posts, in the service settings
  `wp_categories` and `wp_crew_counts`, which is what the page uses at sea.
- **A crew line** is a first paragraph whose every part is one to three capitalised
  words; "2:20-4:20" or a sentence is not one. A part whose later words are names that
  sail alone is split: "Nagako, Catherine Steve" is three people.
- **Rules are config, rule types are code.** `always`, `moved` (fixes spanning more
  than `metres`), `weekday_evening` (boat time, +8), `race_started` (a `race/event` of
  type `start`), `track_enters` (`bbox`). All are answered in SQL with `json_extract`,
  and the answer is cached for a minute per recording, as the page asks every 5 s.
- **A recording nobody wrote up** publishes with its suggested categories: publishing
  now uses the draft the page would show, stored or not.
- **Categories are never created** by the publisher. A name the site does not have is
  left off the post with a warning. Category names are still stored as names, matched
  case-insensitively (and unescaped, as a guard) against the site's.
- Verified on the dev rig: on start the recorder learnt the local blog's 10 categories
  and Henry and Steve from the crew line of the ship's-log post published in FR-24.
**Description:** Categories are chosen from the site's real list, with likely ones already
ticked; crew names are offered from those used before

**Acceptance Criteria:**

- [ ] Whenever WordPress is reachable (at the dock), fetch and cache the category list
      and the crew names. Both are then available offline at sea
- [ ] Categories are chips from the cached list. A category is never created from free
      text; `create_post` stops creating categories by name
- [ ] Ticked by default, each untickable:
  - **Track Logs**: always
  - **Ship's Log**: when the boat moved
  - **Twilight**: start on a weekday after 16:00 local
  - **Club event**: a `race/event` of type `start` was recorded during the recording
  - **Rottnest**: the track enters the Rottnest bounding box (in config)
- [ ] Rules live in config, so a new rule needs no code
- [ ] Crew: names from earlier drafts, plus the first paragraph of past Ship's Log
      posts, ordered by how often they appear

**Implementation Notes:**

- `race/event` is published by the racing app for event_recorder to log, but no event
  config records it yet. Add `race/#` to `record_topics` for `anchor_track_recording`.
  That also gives the title a suggestion from the event's `course`.

---

### FR-31: Live While Recording

**Priority:** Could Have
**Status:** 📋 Specified (2026-10-09)
**Description:** The draft and its preview are useful while the recording is still running

**Acceptance Criteria:**

- [ ] A light summary is kept for each active recording and refreshed every 10 s:
      duration, distance, max SOG and a downsampled track. No matplotlib
- [ ] The event page header and the preview's auto blocks use that summary until the
      recording stops; the full processing runs on stop as now
- [ ] The preview's live map is drawn in the browser with the racing app's offline
      chart code (`geo.js`, `palette.js`), which already matches the recorder's route
      maps
- [ ] The summary is also what FR-22 publishes, replacing its per-second `COUNT(*)` over
      `recording_data`

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
- [x] Pipeline triggered automatically in background when `auto_process_on_stop` setting is enabled (FR-23)

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
**Status:** ✅ Implemented (2026-03-06)
**Description:** Docker HEALTHCHECK instruction and dedicated `/health` endpoint

**Acceptance Criteria:**

- [x] `GET /health` endpoint returns `{"status": "ok"}` with HTTP 200 when service is healthy
- [x] `GET /health` returns HTTP 503 if database is unreachable
- [x] Dockerfile `HEALTHCHECK` instruction points to `/health`
- [x] Health check uses stdlib `urllib.request` (no external package dependency)

**Implementation Notes:**

- `/health` performs a minimal database round-trip (`get_database_stats()`) to confirm SQLite is reachable; this is fast (no full table scans) and catches the most likely failure mode
- Returns HTTP 503 on error so Docker marks the container unhealthy rather than silently passing
- Dockerfile parameters: `--interval=30s --timeout=10s --start-period=30s --retries=3`
- `start-period=30s` accounts for Chromium and MQTT connection setup time on first start
- Using `urllib.request` in the CMD avoids the overhead of importing the `requests` package for a one-liner health probe
- Implemented in `web_interface.py` and `Dockerfile`

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

### TR-9: Foreign Keys Enforced, and Deleting a Recording Removes All of It

**Priority:** Must Have
**Status:** ✅ Implemented (2026-10-09)
**Description:** The schema declares `ON DELETE CASCADE` on every child table, but SQLite
ignores it unless each connection turns foreign keys on, and `get_connection()` never did

**Acceptance Criteria:**

- [x] `PRAGMA foreign_keys=ON` on every connection in `Database.get_connection()`,
      except migrations, which pass `foreign_keys=False`
- [x] Deleting a recording removes its `recording_data`, `recording_images` and
      `recording_exports` rows (`post_drafts` joins the list when FR-24 adds it)
- [x] The delete route also removes `uploads/<id>/`, not only `plots/<id>/`
- [x] A one-off cleanup removes child rows already orphaned by past deletes, marked done
      by the `orphans_removed` service setting so it never rescans `recording_data`
- [x] Child tables left pointing at the dropped `recordings_old` are repaired
- [x] A buffered row for a recording deleted meanwhile is dropped, not allowed to fail
      the batch
- [x] `tests/test_foreign_keys.py`

**Implementation Notes:**

- Before this, `delete_recording()` deleted only the `recordings` row. Every deleted
  recording has left all of its MQTT rows in the database on the Pi's SD card.
- **The dangling reference, found while doing this.** The `processed` migration renames
  `recordings` to `recordings_old`, creates the new table and drops the old one. Since
  SQLite 3.26 a rename rewrites the `REFERENCES` in every child table to the new name
  whether foreign keys are on or not, so `recording_data` and `recording_images` were
  left referencing `"recordings_old"`, which the migration then dropped. With
  enforcement off nothing noticed. With it on, every insert into `recording_data` fails
  with `no such table: main.recordings_old`, which on the Pi would stop all recording.
  Any database old enough to have taken that migration (Feb to Mar 2026) is affected.
  - **Repair:** `_repair_dangling_references()` edits the stored `CREATE TABLE` text
    under `PRAGMA writable_schema`, bumps `schema_version`, and requires
    `PRAGMA integrity_check` to say `ok` before the transaction commits. No rows are
    copied; on the Pi `recording_data` is most of the file.
  - **Prevention:** migrations run with `PRAGMA legacy_alter_table=ON`, which stops the
    rewrite.
- **Why a bad row is dropped rather than retried:** `MessageBuffer._flush_buffer()` keeps
  a failed batch and retries it. Once foreign keys are enforced, one row for a missing
  recording would fail every flush from then on and block all recording. No code path
  produces such a row today; the guard is there because the cost of being wrong is
  every recording.
- Verified on the dev rig (`dev/README.md`): a Frostbite replay produced two recordings;
  deleting one through the API removed its 67,067 rows and left the other's 47,934.

---

### TR-10: One Recording Service Behind the Triggers and the Routes

**Priority:** Must Have
**Status:** ✅ Implemented (2026-10-09)
**Description:** Start, stop, process and publish each happen in exactly one place, called
by the GPS triggers and by the Flask routes alike

**Acceptance Criteria:**

- [x] `recording_service.py`: `RecordingService` owns start, stop, stop-all, process,
      background process, reset, delete and publish. The draft joins it with FR-24
- [x] `_on_trigger_start()` / `_on_trigger_stop()` in `main.py` and the start, stop,
      process, reset, delete and publish routes in `web_interface.py` call it rather than
      repeating its steps
- [x] Routes only parse the request and shape the response. A refusal is a
      `RecordingError` carrying the HTTP status the route returns
- [x] `tests/test_recording_service.py`

**Implementation Notes:**

- Duplication before: auto-process existed in both `main.py` and the stop route; the
  publish route held about 170 lines of publishing logic. Both are now in the service,
  with the publish logic moved unchanged (TR-11 reworks it).
- **The bugs the split caused, now fixed:**
  - A manually started recording never entered `_recordings_this_run`, so the
    clock-step repair skipped it. The set is now the service's, and every start adds
    to it.
  - `service.stop()` ended only triggered recordings on shutdown. `stop_all()` ends
    whatever the data recorder is recording.
  - `/api/status` counted only triggered recordings as active. It now counts what is
    being recorded.
  - Manual recordings were stored with `trigger_type` `gps_movement`, the
    `create_recording()` default. They are now `manual`.
- A trigger can fire its stop after the crew has stopped the same recording from the web
  UI. The service refuses to stop a recording that is not active, and the trigger
  handler takes that as the answer: the recording keeps the end time the crew gave it.
- `WebInterface` takes the service as `recording_service`; without one, as in the
  tests, it builds a service that records nothing.
- Verified on the dev rig: a manual recording and a Frostbite replay ran together, the
  status showed both, the anchor recording stopped itself, and `docker stop` ended the
  manual and movement recordings through `stop_all()`.
- **Left for later at the time, since done as TR-14:** a clean shutdown ended the
  recordings in progress, so restarting the container mid-sail ended that sail's
  recording. This note originally said a power cut, by contrast, let recovery resume an
  active recording. That was wrong: `should_resume_recording()` was never called, and
  recovery ended every interrupted recording too.

---

### TR-11: Publishing Runs in the Background and Updates Its Own Post

**Priority:** Must Have
**Status:** ✅ Implemented (2026-10-09). The draft button arrives with the event page
**Description:** Publishing is a job with progress, not one HTTP request, and a recording
publishes to one post for its whole life

**Acceptance Criteria:**

- [x] `POST /api/recordings/<id>/publish` checks what it can at once and returns 202
      with the job; `GET` on the same URL reports it (`running`, `done`, `failed`, with
      a `step` such as "Uploading 3 of 16"). A second publish while one runs is 409.
      The dashboard follows the job
- [x] The WordPress post id is stored, in a new `post_drafts` table (`wp_post_id`,
      `wp_modified`, `wp_status`), which FR-24 extends with the draft
- [x] A later publish of the same recording **updates** that post
      (`POST /wp/v2/posts/<id>`) rather than creating another
- [x] Before updating, the post's `modified_gmt` is compared with the stored
      `wp_modified`. If it changed, the post was edited in wp-admin, and the publish is
      refused (409) with a message instead of overwriting that work
- [x] A post deleted or trashed in WordPress is published afresh. Failing to *check*
      is a 503, never read as "gone", which would make a second post
- [x] Recordings published before this have a link but no post id (enchantee.org's
      existing Track Logs). While that post can still be found by its link, whether
      `?p=N` or a pretty slug, publishing again is refused (409); once it is deleted
      there, the recording publishes as a new post
- [x] "Send as WordPress draft": the API takes `auto_publish: false`. The button is
      FR-27's
- [x] `tests/test_publish.py`, against a fake WordPress

**Implementation Notes:**

- Before, reset then publish created a duplicate post, and a publish held the request
  open for its whole length: 27 s on the dev rig's local network, minutes from a
  phone hotspot, with no progress.
- Rule of ownership: the local draft is the master until the post is published.
  Afterwards it is WordPress, and the event page locks.
- Jobs are held in memory. A restart mid-publish loses the job, not the post: the next
  attempt finds the post by its stored id, or by its link if the id was never stored.
- The publisher takes `post_id` and a `progress(step, done, total)` callback; media
  already uploaded are reused by the existing name-and-size check, so an update of an
  unchanged recording sent nothing but the post (2 s on the rig).
- **Verified against a real WordPress** (the dev rig's `wordpress` profile):
  - first publish created post 21; a second publish updated post 21
  - the post retitled through wp-cli, as if in wp-admin: the next publish was refused
    with the 409 message and the title left as edited
  - a recording given only a `?p=20` link was refused while post 20 existed, and
    published as post 40 once it was deleted
  - the same with post 40's pretty link: found by slug and refused
- **Found doing it:** the post date is sent as Perth local time, which WordPress
  interprets in the site's own timezone. A blog on UTC therefore schedules every post 8
  hours ahead (`future`). The dev blog is set to Australia/Perth for that reason;
  enchantee.org's posts have the right dates, so it must be too.

---

### TR-12: Recording, Artefact and Post State Kept Apart

**Priority:** Should Have
**Status:** ✅ Implemented (2026-10-09), with the differences noted below
**Description:** `recordings.status` holds the recording's life and the post's life in one
field. The editor needs them separately

**Acceptance Criteria:**

- [x] Recording state, `recordings.status`: `active`, `stopped`, `failed`. `failed` now
      means only that nothing was recorded
- [x] Artefact state, `recordings.artefacts`: `none`, `processing`, `fresh`, `stale`,
      **`failed`**, with `processed_at`
- [x] Post state, `post_drafts.post_state`: `none`, `publishing`, `wp_draft`,
      `published`, `publish_failed`, with `post_error`
- [x] Migration maps the existing statuses onto the three fields
- [x] Every recording read carries all three, and a derived `stage` for display
- [x] `tests/test_status_split.py`

**Implementation Notes:**

- **Differences from the specification:**
  - Artefacts gain `failed`. Without it a processing error had nowhere to go but the
    recording's own status, which is the conflation this requirement removes.
  - Stale is set when the *recording* changes after processing: stopped after being
    processed mid-recording, or moved by the clock-step repair. Not when photos change:
    processing never touches the crew's photos, which go to the post straight from
    `recording_images`.
  - Post state has no `editing`. Whether a draft is being edited is FR-24's to say,
    when the draft exists.
- **Compatibility:** columns are added, not the table rebuilt, so the CHECK constraint
  still allows the old values; nothing writes them. The API keeps `status` (now the
  recording's own) and adds `artefacts`, `post_state`, `post_error` and `stage`.
  `stage` uses the old status names plus `publishing`, so the dashboard and upload page
  switched from `status` to `stage` with their logic unchanged. `?status=` on the list
  filters by stage.
- **The migration's map:**

  | old `status` | becomes | post |
  |---|---|---|
  | `processing` | `stopped`, artefacts `none` | |
  | `processed` | `stopped`, `fresh` | `published` if it has a `wordpress_url` |
  | `published` | `stopped`, `fresh` | `published` |
  | `failed`, "...WordPress..." | `stopped`, `fresh` | `publish_failed`, message kept |
  | `failed`, "No data recorded..." | `failed` | |
  | `failed`, anything else | `stopped`, artefacts `failed` | |

  A post id stored by TR-11 with no state becomes `published` (or `wp_draft`). The
  `processed`-with-a-link rule matters on the Pi: the old way to add a photo to a
  published Track Log, or republish one, was to reset it to processed first.
- **Reset** now clears a failed process or publish and nothing else. A published
  recording publishes again without it (TR-11), so a published recording is refused,
  and the dashboard's button is "Clear the failure", shown only for those.
- **Locking (Q5)** is by post state: photos and title are refused once the post is
  `wp_draft` or `published`, and accepted after a failed publish.
- **Recovery** had to change, or it would have broken: it queued every `stopped`
  recording for processing, which after the split is every finished recording. It now
  queues only those with no artefacts, resets interrupted processing, and turns a
  publish interrupted by a restart into `publish_failed`. `get_recovery_summary()`
  counts by stage; it used `.value` on plain strings and raised whenever called.
- Verified on the dev rig: the migration ran on the day's database, the published
  recording came out `published`, and recovery queued only the two never-processed
  recordings rather than all of them.

---

### TR-14: Recordings Survive a Restart or a Power Cut

**Priority:** Must Have
**Status:** ✅ Implemented (2026-10-09), asked for after a restart during the first
iPhone test ended the recording being tested
**Description:** A recording in progress carries on after the service restarts, whether
the restart was clean (an edit on the jetty, a container update) or a power cut

**Acceptance Criteria:**

- [x] A clean shutdown saves what is buffered and leaves every recording in progress
      active (`RecordingService.suspend_all()`), as a power cut leaves them
- [x] On start, recovery resumes an active recording whose last data is within
      `RESUME_WITHIN` (6 hours), including one interrupted before any data arrived
- [x] A resumed recording records its own topics again: `recordings.record_topics`,
      stored at start; older rows take them from their event config
- [x] A triggered recording is handed back to its trigger in its recording state
      (`GPSTriggerMonitor.resume_monitor()`), so the trigger's own stop condition ends
      it: the anchor recording when the boat is back on the mooring
- [x] One silent for longer than that is ended at its last data, not at restart time,
      so it does not claim the hours the Pi was off; one that never recorded anything
      has failed, as before
- [x] One whose event is no longer in the config, which nothing would ever stop, is
      ended at its last data; of two active recordings of one event, the later carries on
- [x] `tests/test_resume.py`

**Implementation Notes:**

- Until this, nothing resumed. A clean shutdown ended recordings (`stop_all`), and
  recovery ended any a power cut left active: `should_resume_recording()` existed but
  was never called. The anchor trigger's cold-start guard (FR-1) then refuses to start
  another away from the mooring, so any interruption mid-sail lost the rest of it.
- A resumed recording is not added to `recordings_this_run`: its earlier rows were
  written on the previous run's clock, which the clock-step repair has no measure of.
- Verified on the dev rig mid-replay: on `docker restart`, "Leaving recording 9 active",
  then on start "Monitor 'track_recording': resumed with recording 9", and recording 9
  went on from 576 rows to over 1,278 with no new recording started.

---

### TR-13: Web UI Runs on iOS 12

**Priority:** Must Have
**Status:** ✅ Implemented (2026-10-09), with one recorded exception
**Description:** The boat's iPad mini 3 is on iOS 12 and shows the racing app full time.
Anything it opens has to run there

**Acceptance Criteria:**

- [x] No optional chaining (`?.`) or nullish coalescing (`??`): Safari 13.1+. Also
      checked: `replaceAll`, `matchAll`, `Promise.allSettled`, `Array.at`,
      `structuredClone`
- [x] No `clamp()` or `dvh` without a fallback ahead of it
- [x] No flexbox `gap`, except in `style.css` and `upload.html` (below)
- [x] `tests/test_ios12_floor.py` checks every `.js` file and inline `<script>` and
      `<style>` in `web_ui/`, so a new page is covered without being listed

**Implementation Notes:**

- `web_ui/app.js` used `?.` on seven lines (241, 247, 248, 252, 307, 670, 909). On
  iOS 12 that is a syntax error, so the whole dashboard script failed to load there.
  `upload.js` was clean.
- **The exception:** the dashboard's `style.css` and `upload.html` use flexbox `gap` in
  17 places. iOS 12 ignores it rather than failing, so items lose their spacing and
  nothing breaks, and both pages are being replaced by the event page (FR-27). They are
  listed in `FLEX_GAP_LEGACY` in the test rather than reworked. Nothing new may join
  that list.

---

## Change Log

### 2026-10-09: Phase 6, Post Editor, Specified

**Source:** Design review of event_recorder, and the 40 most recent hand-written posts on
enchantee.org (read through the REST API)
**Updated by:** Claude Opus 5.5

**Summary of changes documented:**

- Added Phase 6 to the status list, and a background section on the site's real posts
- Added FR-24 to FR-31: draft model and renderer, ship's log layout, computed log lines,
  the event page at `/race/log/`, default recording selection, photo and note capture,
  categories and crew, live updating
- Added TR-9 to TR-13, found in the review: foreign keys never enforced, logic split
  between `main.py` and the routes, publish blocking and duplicating, one status field
  for two lifecycles, dashboard broken on iOS 12
- Q2 superseded: two recordings of one sail are normal
- Added Q4 (where the editor lives) and Q5 (who owns a post)
- Companion entry in the racing app: DESIGN 9.13, the Log link
- Version bumped to 0.4.0

---

### 2026-03-06: Post-Theme and Operational Enhancements Update

**Source:** Post-implementation review against git log (commits 8ad94b5 – a083528)
**Updated by:** Claude Sonnet 4.6

**Summary of changes documented:**

- Added FR-14, FR-15, FR-17 detailed sections (previously listed only in status table)
- Added full FR-16 section covering WordPress post structure; updated with 2026-03-06 changes: last user photo as featured image, post date set to recording start time
- Added three new requirements:
  - **FR-21** Red Shadow web UI theme with sailing background and glassmorphism cards
  - **FR-22** MQTT recording status publishing at 1 Hz
  - **FR-23** Auto-process on stop setting with persistent SQLite storage and Settings page toggle
- Updated FR-1: documented cold-start anchor_departure false trigger fix (`seen_inside_anchor` guard)
- Updated FR-6: documented interactive Leaflet/Folium HTML map embedding in WordPress post (`_extract_folium_embed()`)
- Updated FR-7: documented statistics HTML table in WordPress post (JSON sidecar pattern, PNG excluded from upload)
- Updated FR-8: added `/api/settings` GET and POST endpoints to endpoint table
- Updated FR-3 schema notes: added `recording_exports` and `service_settings` table entries
- Updated TR-3: added auto-process on stop as trigger for processing pipeline
- Updated Phase 3 and Phase 4 implementation progress sections
- Added new "Operational Enhancements" implementation progress section
- TR-7 (health checks) implemented: `GET /health` endpoint + Dockerfile HEALTHCHECK updated
- Phase 5 marked complete; overall status updated to "All Phases Complete"
- Version bumped to 0.3.0

---

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

**Superseded (2026-10-09):** one recording per event, several at once. `track_recording`
and `anchor_track_recording` are both enabled and both record every sail. FR-28 decides
which of them the editor opens.

---

### Q4: Where Does the Post Editor Live?

**Decision (2026-10-09):** ✅ In event_recorder, reached from the racing app

- **Not a racing app page.** The racing app is designed for the cockpit: no scrolling,
  no modal dialogs, glance and go. Writing a post is the opposite job. The recordings,
  photos and WordPress publisher are all here, and racing DESIGN section 2 already keeps
  the two apart.
- **But served under the racing app's prefix**, at `/race/log/`, so it opens inside the
  racing app's Home Screen window on the phone and on the iPad (FR-27).
- The racing app gets one link to it, "Log", and a recording dot (racing DESIGN 9.13).
  The photo and note buttons are on the event page, not on the racing screens.

---

### Q5: Who Owns a Post, the Pi or WordPress?

**Decision (2026-10-09):** ✅ The Pi until published, WordPress afterwards

- Two-way sync between a local draft and wp-admin was rejected: the boat is offline at
  sea, and merging two edited copies of a post is not worth building for one author.
- Before publishing, the local draft is the only copy. After publishing, the event page
  locks, and edits are made in wp-admin.
- A republish is allowed only if wp-admin has not touched the post since (TR-11), so
  work done there is never overwritten.

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
**Completed:** 2026-02-17 (additions through 2026-03-06)

- [x] Flask REST API — 13 endpoints (`web_interface.py`)
- [x] Vanilla JS SPA (`web_ui/app.js`, `index.html`, `style.css`)
- [x] Real-time dashboard with 2-second polling
- [x] Recordings history with modal detail view
- [x] YAML configuration editor
- [x] Manual start/stop recording controls
- [x] UTC timezone fix for active recording duration display
- [x] Mobile photo upload page (`upload.html`, `upload.js`)
- [x] Upload Photo button on active recording cards
- [x] Red Shadow theme with sailing background and glassmorphism cards (FR-21)
- [x] Settings page: Recording Behaviour card with auto-process toggle (FR-23)
- [x] `GET /api/settings` and `POST /api/settings` endpoints
- [x] `service_settings` table in SQLite with migration

---

### Phase 4: WordPress Integration

**Status:** ✅ Complete
**Completed:** 2026-02-17 (additions through 2026-03-06)

- [x] WordPress REST API with Application Password authentication
- [x] Image media upload returning `{'id', 'url'}` from `source_url`
- [x] Export file upload (CSV, KML, GPX)
- [x] Structured HTML post: Photos section, Data Visualisations section, Statistics table, Interactive Map, Downloads section
- [x] User photo by-line captions displayed with `<em>` in Photos section
- [x] Last user-uploaded photo used as WordPress featured image (falls back to first plot)
- [x] Post publication date set to recording start time
- [x] Statistics rendered as HTML `<table>` in post (not uploaded PNG)
- [x] Interactive Leaflet/Folium map embedded inline in post
- [x] Draft-first publish workflow
- [x] WordPress mu-plugin for KML/GPX MIME type unblocking

---

### Operational Enhancements

**Status:** ✅ Complete
**Completed:** 2026-03-06

- [x] MQTT recording status publishing at 1 Hz (FR-22) — `main.py`
- [x] Auto-process on stop setting with SQLite persistence (FR-23) — `main.py`, `models.py`, `web_interface.py`
- [x] Cold-start anchor_departure false trigger fix — `trigger_monitor.py`

---

### Phase 5: Production Deployment

**Status:** ✅ Complete
**Completed:** 2026-03-06

- [x] Multi-platform Docker build scripts (`build.sh`, `build.cmd`)
- [x] Test docker-compose environment with all services
- [x] WordPress mu-plugins bind-mount in docker-compose
- [x] Docker HEALTHCHECK instruction pointing to `/health` (TR-7)
- [x] End-to-end test suite
- [x] Deployment and configuration documentation

---

### Phase 6: Post Editor

**Status:** 📋 Specified, not started (2026-10-09)

Suggested order, each step useful without the next:

1. **Foundations:** TR-9 (foreign keys), TR-13 (iOS 12), TR-10 (recording service),
   TR-11 (background publish, stored post id), TR-12 (state split)
2. **Draft and renderer:** FR-24, with the current post layout as the first draft
   template so published posts do not change. Then FR-25 as the new default
3. **Event page:** FR-27, FR-28, FR-29 and FR-30 for stopped recordings, the
   `/race/log/` nginx route, and the Log link in the racing app (racing DESIGN 9.13)
4. **Computed lines and live mode:** FR-26 and FR-31

- [x] Step 1: foundations (2026-10-09), plus the dev rig, `dev/README.md`
- [x] Step 2: draft and renderer (2026-10-09), ship's log the default
- [x] Step 3: event page and Log link (2026-10-09)
- [ ] Step 4: computed lines and live mode

---

## References

- **Existing Patterns:**
  - Flask REST API: `/python/emon_settings_web/emon_settings_web.py`
  - MQTT Subscriber: `/python/emonMQTTToInflux.py`
  - Config Management: `/python/pyEmon/pyemonlib/emon_settings.py`
- **Docker Deployment:** `/provisioning/shannstainable/docker-compose.yml`
- **WordPress MIME type plugin:** `test_event_recorder/mu-plugins/allow-geo-files.php`

---

**Last Updated:** 2026-10-09 by Claude Opus 5.5
**Next Review:** After Phase 6 step 1
