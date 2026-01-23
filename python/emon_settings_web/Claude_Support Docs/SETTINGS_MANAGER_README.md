# Emon Settings Manager - Web Interface

A modern web-based interface for managing emon timestamped settings files. Create, view, edit, and manage configuration files with real-time validation and preview.

## Features

✅ **List All Settings Files** - View all available configuration files with timestamps
✅ **View File Contents** - Read YAML file contents with syntax highlighting
✅ **Edit Settings** - Built-in YAML editor with real-time character/line count
✅ **Create New Files** - Generate new settings files with guided creation wizard
✅ **Delete Files** - Remove obsolete settings files (with confirmation)
✅ **Validate YAML** - Real-time YAML syntax validation
✅ **Preview Mode** - View rendered YAML with syntax highlighting
✅ **Responsive Design** - Works on desktop, tablet, and mobile devices
✅ **Modern UI** - Clean, intuitive interface with visual feedback

## Installation

### Prerequisites

- Python 3.6 or higher
- pip (Python package manager)

### Setup

1. **Install required packages:**

```bash
pip install flask pyyaml
```

The packages should be installed in your Python environment that includes the emon suite.

## Usage

### Starting the Server

#### Option 1: Using the startup script

```bash
# From the pyemonlib directory
python start_settings_manager.py
```

#### Option 2: Direct Python execution

```bash
python -m pyemonlib.emon_settings_web
```

#### Option 3: With custom settings path

```bash
python start_settings_manager.py --settings-path /path/to/config --port 5000
```

#### Option 4: Enable debug mode (with auto-reload)

```bash
python start_settings_manager.py --debug
```

### Accessing the Web Interface

Once the server is running, open your browser and navigate to:

```
http://localhost:5000
```

If you changed the port:

```
http://localhost:YOUR_PORT
```

## Web Interface Guide

### Main Screen

The interface is divided into two main areas:

1. **Left Sidebar** - Lists all available settings files
2. **Main Content Area** - Editor and preview panels

### Managing Settings Files

#### Viewing a File

1. Click on any file in the left sidebar
2. The file contents will load in the editor
3. Use the tabs to switch between Edit, Preview, and Validate views

#### Creating a New File

1. Click the **+ New File** button at the top of the sidebar
2. Enter a filename in one of these formats:
   - `YYYYMMDD-hhmm.yml` (e.g., `20250122-1430.yml`)
   - `emon_config.yml` (legacy format)
3. Choose a template:
   - **Empty** - Start with blank file
   - **Minimal** - Basic structure with common sections
   - **Full** - Complete example with all sensor types
4. Edit the content if needed
5. Click **Create File**

#### Editing a File

1. Select a file from the sidebar
2. Make changes in the editor
3. Use the **Validate** tab to check YAML syntax
4. Click **💾 Save Changes** to save

#### Deleting a File

1. Select a file (cannot delete `emon_config.yml`)
2. Click **🗑️ Delete** button
3. Confirm the deletion

### Editor Tabs

#### Edit Tab
- Full YAML editor with monospace font
- Character and line count display
- Real-time change tracking

#### Preview Tab
- Syntax-highlighted YAML display
- Read-only view of file contents
- Automatically updates when switching tabs

#### Validate Tab
- Click **Validate YAML** to check syntax
- Shows detailed error messages if invalid
- Provides feedback before saving

## File Format

### Timestamped Format (YYYYMMDD-hhmm.yml)

Files are automatically selected based on current timestamp. The most recent file with a timestamp ≤ current time is used.

**Example files:**
```
20250101-0000.yml  (Jan 1, 2025 at 00:00 - baseline config)
20250415-0800.yml  (Apr 15, 2025 at 08:00 - spring config)
20251001-1600.yml  (Oct 1, 2025 at 16:00 - fall config)
```

### Legacy Format (emon_config.yml)

Used as fallback if no timestamped files exist or are applicable.

## Configuration File Structure

The settings file is YAML format. Common sections include:

### Temperature Sensors
```yaml
temp:
  0:
    name: House temperatures
    t0: Sensor location
    t1: Another location
    # ... t2, t3, etc.
```

### Hot Water System
```yaml
hws:
  0:
    name: HWS name
    t0: Panel temperature
    t1: Water temperature
    # ... more sensors and pumps
    p0: Pump name
    p1: Another pump
```

### Water Meters
```yaml
wtr:
  0:
    name: Water usage point
    f0: Flow meter name
    f0_litresPerPulse: 0.1  # Calibration value
    h0: Level sensor name
```

### Rain Gauge
```yaml
rain:
  0:
    name: Rain gauge
    mmPerPulse: 0.2  # Calibration value
```

### Power Pulse Counters
```yaml
pulse:
  0:
    name: Power monitoring
    p0: Solar production
    p0_wPerPulse: 0.25  # Calibration
    p1: Consumption
    p1_wPerPulse: 1
```

### Battery Monitors
```yaml
bat:
  0:
    name: Battery monitor
    s0: Current sensor
    v0: Voltage sensor
    v0_reference: true  # Reference voltage
```

## API Endpoints

For developers integrating with custom applications:

### List Files
```
GET /api/settings/list
```

Returns:
```json
{
  "success": true,
  "files": [
    {
      "filename": "20250122-1430.yml",
      "path": "/path/to/file",
      "datetime": "2025-01-22T14:30:00",
      "isCurrent": true
    }
  ],
  "current": "20250122-1430.yml"
}
```

### Read File
```
GET /api/settings/read/<filename>
```

Returns:
```json
{
  "success": true,
  "filename": "20250122-1430.yml",
  "content": "..."
}
```

### Save File
```
POST /api/settings/save
```

Request:
```json
{
  "filename": "20250122-1430.yml",
  "content": "..."
}
```

### Validate YAML
```
POST /api/settings/validate
```

Request:
```json
{
  "content": "..."
}
```

### Delete File
```
POST /api/settings/delete/<filename>
```

## Troubleshooting

### Port Already in Use

If you get "Address already in use" error:

1. Use a different port:
   ```bash
   python start_settings_manager.py --port 8080
   ```

2. Or find and kill the process using the port (see your OS documentation)

### Files Not Loading

1. Verify the settings path is correct
2. Check file permissions (files should be readable)
3. Ensure YAML files have `.yml` extension
4. Check console output for error messages

### YAML Validation Errors

1. Check indentation (YAML is whitespace-sensitive)
2. Ensure colons are followed by spaces: `key: value`
3. Use quotes for values with special characters: `name: "Some: Value"`
4. Check for tab characters (use spaces instead)

### Changes Not Saving

1. Check YAML syntax in Validate tab
2. Ensure you have write permissions to the directory
3. Check available disk space
4. Look for error messages in console

## Advanced Usage

### Running on Different Host/Port

```bash
# Make accessible from network (not just localhost)
# Modify emon_settings_web.py line with app.run()
# Change: host='0.0.0.0'
```

### Integration with Systemd (Linux)

Create `/etc/systemd/system/emon-settings-manager.service`:

```ini
[Unit]
Description=Emon Settings Manager Web Interface
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/emon/emon_Suite/python/pyEmon/pyemonlib
ExecStart=/usr/bin/python3 start_settings_manager.py --settings-path /etc/emon/config
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable emon-settings-manager
sudo systemctl start emon-settings-manager
```

### Integration with Supervisor

Create `/etc/supervisor/conf.d/emon-settings-manager.conf`:

```ini
[program:emon-settings-manager]
command=/usr/bin/python3 start_settings_manager.py --settings-path /etc/emon/config
directory=/home/pi/emon/emon_Suite/python/pyEmon/pyemonlib
autostart=true
autorestart=true
stderr_logfile=/var/log/emon/settings_manager.err.log
stdout_logfile=/var/log/emon/settings_manager.out.log
```

Update and start:
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start emon-settings-manager
```

## Performance Notes

- File list refreshes automatically every 10 seconds when not editing
- Settings validation happens in real-time as you type
- Large files (>1MB) may slow down preview rendering
- YAML parsing uses safe_load for security

## Security Considerations

⚠️ **Important:** This web interface should be used in trusted networks only.

Security features implemented:
- Path traversal protection (no `..` in filenames)
- YAML safe_load (no arbitrary code execution)
- File extension validation
- Read-only file operations for preview

**Recommendations:**
- Run on localhost only or behind firewall
- Restrict network access using firewall rules
- Use HTTPS with reverse proxy (nginx, Apache)
- Implement authentication if exposed to network
- Keep Flask and PyYAML updated

## Browser Compatibility

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+
- Mobile browsers (iOS Safari, Chrome Mobile)

## License

Same as emon suite

## Support

For issues or feature requests, please refer to the main emon suite documentation.

---

**Last Updated:** January 2026
**Version:** 1.0
