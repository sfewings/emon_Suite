# Quick Start Guide - Emon Settings Manager

## 30-Second Setup

### 1. Install Dependencies
```bash
pip install flask pyyaml
```

### 2. Start the Server
```bash
cd python/pyEmon/pyemonlib
python start_settings_manager.py
```

### 3. Open Browser
Navigate to: **http://localhost:5000**

## Common Tasks

### Create a New Settings File

1. Click **+ New File** button
2. Enter filename: `20250122-1430.yml` (use current date/time)
3. Select template: **Minimal** or **Full**
4. Edit content
5. Click **Create File**

### Edit Existing File

1. Click file in left sidebar
2. Make changes in editor
3. Check syntax with **Validate** tab
4. Click **💾 Save Changes**

### Preview Settings

1. Select file
2. Click **Preview** tab
3. View syntax-highlighted YAML

### Valid Filename Formats

✅ `20250122-1430.yml` (recommended - YYYYMMDD-hhmm.yml)
✅ `emon_config.yml` (legacy)
❌ `2025-01-22-14-30.yml` (wrong format)
❌ `settings.yml` (wrong format)

## Command-Line Options

```bash
# Custom settings path
python start_settings_manager.py --settings-path /path/to/config

# Custom port
python start_settings_manager.py --port 8080

# Debug mode with auto-reload
python start_settings_manager.py --debug

# All options
python start_settings_manager.py --settings-path ./config --port 8080 --debug
```

## File Structure

Settings organized by sensor type:

```yaml
temp:        # Temperature sensors
hws:         # Hot water system
wtr:         # Water meters
rain:        # Rain gauge
pulse:       # Power/pulse counters
bat:         # Battery monitors
disp:        # Displays
scl:         # Scales
air:         # Air quality
inv:         # Inverters
bee:         # Beehive monitors
leaf:        # Leaf devices
bms:         # Battery management systems
```

## Tips

💡 Use **Edit** tab to modify YAML
💡 Use **Preview** tab to view with syntax highlighting
💡 Use **Validate** tab to check for errors before saving
💡 File list auto-refreshes every 10 seconds
💡 Create timestamped files for time-based settings switching
💡 Keep `emon_config.yml` as fallback

## Troubleshooting

**Port 5000 already in use?**
```bash
python start_settings_manager.py --port 8080
```

**Files not showing?**
- Check settings path is correct
- Verify files have `.yml` extension
- Check file permissions

**YAML errors?**
- Use spaces, not tabs for indentation
- Ensure `key: value` format (colon + space)
- Use quotes for special characters: `"value: with: colons"`

## Integration with emon Apps

Both `emon_influx.py` and `emon_mqtt.py` automatically detect new settings files. When you create a new timestamped file via the web interface, the emon applications will use it if the current time matches its timestamp.

**Example:** Create `20250122-1430.yml` and it will be active from Jan 22, 2025 at 14:30 onwards.

---

**Need more help?** See [SETTINGS_MANAGER_README.md](SETTINGS_MANAGER_README.md)
