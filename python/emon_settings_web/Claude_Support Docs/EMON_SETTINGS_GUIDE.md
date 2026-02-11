# Integration Guide: Using EmonSettings in New Modules

## Quick Start

To add settings management to a new emon module:

### 1. Import the Module
```python
import pyemonlib.emon_settings as emon_settings
```

### 2. Initialize in __init__
```python
def __init__(self, settingsPath="./emon_config.yml"):
    # Initialize settings manager
    self.settings_manager = emon_settings.EmonSettings(settingsPath)
    
    # Rest of initialization...
```

### 3. Create Settings Property
```python
@property
def settings(self):
    """Property to access current settings from settings manager."""
    return self.settings_manager.get_settings()
```

### 4. Check for Settings Updates
```python
def process_message(self, data):
    # For live data (use system time)
    self.settings_manager.check_and_reload_settings()
    
    # Or for historical data with timestamps
    import datetime
    timestamp = datetime.datetime(2025, 1, 15, 10, 30)
    self.settings_manager.check_and_reload_settings_by_time(timestamp)
    
    # Use settings
    config = self.settings[key]
```

## EmonSettings API Reference

### Constructor
```python
EmonSettings(settingsPath="./emon_config.yml")
```
- Initializes settings manager
- Scans directory for available settings files
- Loads initial settings
- Parameter can be file path or directory path

### Public Methods

#### `get_settings()`
Returns current settings dictionary
```python
settings = self.settings_manager.get_settings()
config = settings['sensor_name']
```

#### `get_current_settings_file()`
Returns path to currently loaded settings file
```python
current_file = self.settings_manager.get_current_settings_file()
print(f"Using: {current_file}")
```

#### `get_available_settings_files()`
Returns list of all available settings files
```python
files = self.settings_manager.get_available_settings_files()
for dt, filename, path in files:
    print(f"{filename} - effective from {dt}")
```

#### `check_and_reload_settings()`
Checks for new files and reloads if needed (system time based)
```python
# Called in message processing loop
reloaded = self.settings_manager.check_and_reload_settings()
if reloaded:
    print("Settings updated!")
```

#### `check_and_reload_settings_by_time(current_time=None)`
Checks for new files based on provided timestamp
```python
import datetime
# For historical data
time = datetime.datetime(2025, 1, 20, 14, 30)
self.settings_manager.check_and_reload_settings_by_time(time)

# For current time (if not specified)
self.settings_manager.check_and_reload_settings_by_time()
```

#### `reload_settings()`
Forces immediate reload of settings
```python
self.settings_manager.reload_settings()
```

### Configuration Properties

#### `settingsCheckInterval`
Seconds between checking for new files (default: 60)
```python
# Check every 30 seconds instead of 60
self.settings_manager.settingsCheckInterval = 30
```

## Complete Example Module

```python
import pyemonlib.emon_settings as emon_settings

class MyEmonModule:
    def __init__(self, settingsPath="./emon_config.yml"):
        # Initialize settings manager
        self.settings_manager = emon_settings.EmonSettings(settingsPath)
        
        # Rest of initialization
        self.data_buffer = []
    
    @property
    def settings(self):
        """Property to access current settings from settings manager."""
        return self.settings_manager.get_settings()
    
    def process_message(self, timestamp, data):
        # Check for settings changes (time-aware)
        self.settings_manager.check_and_reload_settings_by_time(timestamp)
        
        # Get current config
        sensor_config = self.settings.get('sensor_config', {})
        
        # Process data with current settings
        # ...
    
    def process_live_data(self, data):
        # Check for settings changes (system time)
        self.settings_manager.check_and_reload_settings()
        
        # Use settings
        # ...
    
    def reload_settings_now(self):
        """Force immediate settings reload"""
        self.settings_manager.reload_settings()
        print(f"Settings reloaded from {self.settings_manager.get_current_settings_file()}")
```

## Settings File Format

All settings files should be valid YAML with consistent structure:

```yaml
# Each settings file (e.g., 20250115-0900.yml)
# should contain the same structure

rain:
  - name: "Main Gauge"
    mmPerPulse: 0.2

temp:
  0:
    name: "Temp Node 1"
    t0: "Inside Temperature"
    t1: "Outside Temperature"

# ... rest of configuration
```

## File Naming Convention

### Valid Filenames
- `YYYYMMDD-hhmm.yml` - Timestamped settings
- `emon_config.yml` - Legacy settings (fallback)

### Examples
- `20250115-0900.yml` - January 15, 2025 at 09:00
- `20250120-1430.yml` - January 20, 2025 at 14:30
- `emon_config.yml` - Default/fallback

## Settings Selection Logic

When processing data with timestamp T:

1. **Scan** - Find all `*.yml` files in directory
2. **Filter** - Find files with timestamp ≤ T
3. **Select** - Use most recent matching file
4. **Fallback** - Use `emon_config.yml` if no match
5. **Load** - Parse and load selected file

Example with files:
```
20250101-0000.yml  (Jan 1, 00:00)
20250115-0800.yml  (Jan 15, 08:00)
20250120-1430.yml  (Jan 20, 14:30)
emon_config.yml    (fallback)

For timestamp 2025-01-15 10:00:
→ Uses 20250115-0800.yml (most recent ≤ timestamp)

For timestamp 2025-01-10 12:00:
→ Uses 20250101-0000.yml (only file ≤ timestamp)

For timestamp 2024-12-31 23:59:
→ Uses emon_config.yml (no timestamped files ≤ timestamp)
```

## Error Handling

The module gracefully handles errors:

- **Missing file** - Falls back to `emon_config.yml`
- **Invalid YAML** - Logs error, keeps previous settings
- **Directory error** - Logs error, uses cached file list
- **Invalid filename** - Silently skips non-matching names

## Performance Considerations

- **Check Interval** - Only scans every 60 seconds (configurable)
- **Memory** - Single list cached for available files
- **CPU** - Minimal impact, no per-message overhead
- **I/O** - Only reads when settings change detected

## Best Practices

1. **Keep settings files consistent** - Same structure in all files
2. **Use meaningful timestamps** - Date/time when settings become active
3. **Organize by time** - Earlier files first chronologically
4. **Test fallback** - Ensure `emon_config.yml` exists
5. **Monitor console** - Check for setting change messages
6. **Adjust interval** - Increase check interval if directory has many files

## Troubleshooting

### Settings not changing
- Check filename format: `YYYYMMDD-hhmm.yml` exactly
- Verify timestamp is in past relative to processed time
- Check file permissions (must be readable)
- Look for console error messages

### No settings file found
- Ensure `emon_config.yml` exists as fallback
- Check directory path in constructor
- Verify at least one `*.yml` file exists

### Old settings being used
- Most recent file ≤ message timestamp is selected
- Add new file with earlier timestamp if needed
- Check message timestamps match local timezone

## Examples from Existing Modules

### emon_influx.py Pattern
```python
def __init__(self, url="...", settingsPath="./emon_config.yml", ...):
    self.settings_manager = emon_settings.EmonSettings(settingsPath)
    # ...

@property
def settings(self):
    return self.settings_manager.get_settings()

def process_line(self, command, time, line):
    # Time-aware settings check (for historical data)
    self.settings_manager.check_and_reload_settings_by_time(time)
    if(command in self.dispatch.keys()):
        self.dispatch[command](time, line, self.settings[command])
```

### emon_mqtt.py Pattern
```python
def __init__(self, mqtt_server="localhost", settingsPath="./emon_config.yml"):
    self.settings_manager = emon_settings.EmonSettings(settingsPath)
    # ...

@property
def settings(self):
    return self.settings_manager.get_settings()

def process_line(self, command, line):
    # System time check (for live data)
    self.settings_manager.check_and_reload_settings()
    if(command in self.dispatch.keys()):
        self.dispatch[command](line, self.settings[command])
```

## Summary

The `EmonSettings` module provides:
- ✅ Centralized settings management
- ✅ Support for timestamped configuration files
- ✅ Automatic file detection and selection
- ✅ Backward compatible with `emon_config.yml`
- ✅ Easy integration into new modules
- ✅ Robust error handling
- ✅ Minimal performance impact

Use it in any new emon module for consistent, maintainable settings management!

---

**Module Location**: `python/pyEmon/pyemonlib/emon_settings.py`  
**Current Users**: emon_influx.py, emon_mqtt.py  
**API Status**: Stable  
**Last Updated**: January 22, 2026
