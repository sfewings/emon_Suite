# API Reference: Enhanced emon_influx Settings Management

## Constructor

```python
emon_influx(url="http://localhost:8086", settingsPath="./emon_config.yml", batchProcess=True)
```

**Parameters**:
- `url`: InfluxDB server URL
- `settingsPath`: Path to settings file or directory containing settings files
- `batchProcess`: Whether to batch write operations

**Auto-Initialized Attributes**:
- `settingsPath`: Stores the path
- `settingsDirectory`: Directory to scan (derived from settingsPath)
- `currentSettingsFile`: Currently loaded settings file (path)
- `availableSettingsFiles`: List of detected settings files
- `settingsCheckInterval`: Seconds between checking for new files (default: 60)

---

## Public Methods

### `check_and_reload_settings()`

Check for new settings files and reload if needed (uses system time).

```python
settings_reloaded = influx.check_and_reload_settings()
```

**Returns**: 
- `True` - Settings were reloaded
- `False` - No changes needed

**Use Case**: Live data processing where you want periodic checks for new settings files

---

### `check_and_reload_settings_by_time(current_time=None)`

Check and reload settings based on a specific time (useful for historical data).

```python
import datetime

# Check for specific time
time = datetime.datetime(2025, 1, 20, 14, 30)
settings_reloaded = influx.check_and_reload_settings_by_time(time)

# Check for current time (uses system time if None)
settings_reloaded = influx.check_and_reload_settings_by_time()
```

**Parameters**:
- `current_time`: `datetime.datetime` object or `None` for current time

**Returns**:
- `True` - Settings were reloaded
- `False` - No changes needed

**Use Case**: Processing historical logs where message timestamps may span different settings periods

---

## Private Methods (For Advanced Use)

### `_parse_settings_filename(filename)`

Parse a filename to extract datetime if it matches `YYYYMMDD-hhmm.yml` format.

```python
dt = influx._parse_settings_filename("20250115-0900.yml")
# Returns: datetime.datetime(2025, 1, 15, 9, 0)

dt = influx._parse_settings_filename("invalid.yml")
# Returns: None
```

**Parameters**:
- `filename`: String filename to parse

**Returns**:
- `datetime.datetime` - Parsed datetime if valid
- `None` - If invalid format

---

### `_scan_settings_files()`

Scan the settings directory for all valid `.yml` files.

```python
files = influx._scan_settings_files()
# Returns: [(dt1, "20250101-0000.yml", "/path/20250101-0000.yml"), ...]
```

**Returns**: List of tuples `(datetime, filename, full_path)`, sorted chronologically

---

### `_get_applicable_settings_file(current_time=None)`

Determine which settings file should be used for a given time.

```python
import datetime

time = datetime.datetime(2025, 1, 20, 14, 30)
filepath = influx._get_applicable_settings_file(time)
# Returns: "/path/to/20250115-0800.yml" (most recent file <= time)
```

**Parameters**:
- `current_time`: `datetime.datetime` or `None` for current time

**Returns**: Full path to applicable settings file, or `None` if none found

---

### `_load_settings_from_file(filepath)`

Load and parse a YAML settings file.

```python
settings = influx._load_settings_from_file("/path/to/settings.yml")
# Returns: dict with parsed YAML content, or None if error
```

**Parameters**:
- `filepath`: Full path to settings file

**Returns**: 
- `dict` - Parsed YAML content
- `None` - If file cannot be loaded

**Errors**: Logged to console but doesn't raise exception

---

### `_load_settings()`

Load settings from the appropriate file based on current time.

```python
influx._load_settings()
```

**Side Effects**:
- Updates `self.settings`
- Updates `self.currentSettingsFile`
- Updates `self.availableSettingsFiles`
- Prints status messages to console

---

## Attributes Reference

### `settingsPath` (str)
Original path provided to constructor. May be file or directory.

### `settingsDirectory` (str)
Directory to scan for settings files (derived from settingsPath).

### `currentSettingsFile` (str or None)
Full path to currently loaded settings file.

### `availableSettingsFiles` (list)
List of detected settings files: `[(datetime, filename, path), ...]`

Sorted chronologically (earliest first).

### `settings` (dict)
The loaded YAML settings (same structure as original emon_config.yml).

### `settingsCheckInterval` (int)
Seconds between directory scans for new files (default: 60).

Can be modified at runtime:
```python
influx.settingsCheckInterval = 30  # Check every 30 seconds
```

### `lineNumber` (int)
Current line number being processed (used in error messages).

---

## Settings File Format

Each `.yml` file should contain the same structure:

```yaml
rain:
  - name: "Sensor Name"
    mmPerPulse: 0.2

temp:
  0:
    name: "Node Name"
    t0: "Sensor 1"
    t1: "Sensor 2"

# ... rest of your sensor configuration
```

---

## Filename Validation

**Valid Formats**:
- `YYYYMMDD-hhmm.yml` - Timestamped settings file
- `emon_config.yml` - Legacy settings file (fallback)

**Invalid Formats**:
- `2025-01-15-0900.yml` - Wrong date separator
- `20250115_0900.yml` - Wrong time separator  
- `settings.yml` - No timestamp
- `20250115.yml` - No time component
- `20250115-09.yml` - Time not 4 digits
- `20250115-0900.txt` - Wrong extension

---

## Error Handling

### File Not Found
If settings file is missing:
- Prints error: `Error: No settings file found in {directory}`
- Sets `self.settings = {}`
- Continues operation (may cause downstream errors)

### Invalid YAML
If settings file has invalid YAML:
- Prints error: `Error loading settings file {path}: {exception}`
- Keeps previous settings
- Continues operation

### Directory Scan Error
If directory cannot be scanned:
- Prints error: `Error scanning settings directory: {exception}`
- Returns empty list of files
- Falls back to legacy file if available

---

## Typical Usage Patterns

### Pattern 1: Process Historical Data
```python
influx = emon_influx(settingsPath="./config/")
influx.process_files("./historical_logs/")
# Settings automatically switch based on log timestamps
```

### Pattern 2: Live Processing
```python
influx = emon_influx(settingsPath="./config/", batchProcess=False)
while True:
    command, time, line = receive_data()
    influx.process_line(command, time, line)
    # Settings checked every 60 seconds for new files
```

### Pattern 3: Manual Control
```python
influx = emon_influx(settingsPath="./config/")

# Force reload for specific time
target_time = datetime.datetime(2025, 1, 20, 14, 30)
influx.check_and_reload_settings_by_time(target_time)

# Check current applicable settings
print(f"Current settings: {influx.currentSettingsFile}")
```

### Pattern 4: Monitor Available Files
```python
influx = emon_influx(settingsPath="./config/")

# List all available settings
for dt, filename, path in influx.availableSettingsFiles:
    print(f"{filename} (effective from {dt})")
```

---

## Console Output Examples

```
Loaded settings from: emon_config.yml
New settings files detected, rescanning...
Loaded settings from: 20250115-0800.yml
Switching settings from 20250115-0800.yml to 20250120-0900.yml (for time 2025-01-20 09:30:00)
```

---

## Integration with process_line

The `process_line` method automatically calls:
```python
def process_line(self, command, time, line):
    self.check_and_reload_settings_by_time(time)  # Automatic!
    if(command in self.dispatch.keys()):
        self.dispatch[command](time, line, self.settings[command])
```

No additional calls needed - it's automatic!

---

**Version**: 1.0  
**Date**: January 2025  
**Python**: 3.6+
