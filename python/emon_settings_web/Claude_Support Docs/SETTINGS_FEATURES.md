# Enhanced Settings Management Features for emon_influx.py

## Overview
The `emon_influx.py` module has been enhanced to support multiple timestamped settings files while maintaining backward compatibility with the legacy `emon_config.yml` approach.

## Features

### 1. Multiple Timestamped Settings Files
Settings files can now be named using the format: `YYYYMMDD-hhmm.yml`

**Example filenames:**
- `20250122-0900.yml` - Settings effective from January 22, 2025 at 09:00
- `20250115-1430.yml` - Settings effective from January 15, 2025 at 14:30
- `20250101-0000.yml` - Settings effective from January 1, 2025 at 00:00

### 2. Automatic Settings Selection
When processing messages, the system automatically selects the most recent settings file whose timestamp is less than or equal to the current message time. This allows you to:

- Change settings at specific times without restarting the application
- Process historical data with the correct settings that were active at that time
- Support multiple configuration changes throughout a day/week/month

### 3. Backward Compatibility
The system continues to support the legacy `emon_config.yml` file:

- If no timestamped settings files are found, `emon_config.yml` is used as a fallback
- If both timestamped files and `emon_config.yml` exist, timestamped files take precedence
- The `emon_config.yml` serves as the ultimate fallback if no timestamped files match

### 4. Dynamic Settings File Detection
The system monitors for new settings files being created while the script is running:

- New settings files are detected automatically every 60 seconds (configurable)
- Settings are automatically reloaded when a new applicable settings file is detected
- No restart required when adding or switching settings files

### 5. Time-Based Settings Application
Settings are applied based on the timestamp of incoming data:

- When processing log files with historical timestamps, settings from the appropriate period are applied
- When processing live data, the current system time is used to select settings
- Settings changes are logged when they occur

## Usage

### Basic Setup

```python
from pyemonlib.emon_influx import emon_influx

# Settings will be loaded from the settingsPath directory
# The system will automatically detect and use timestamped settings files
influx = emon_influx(
    url="http://localhost:8086",
    settingsPath="./emon_config.yml",  # Can be a file or directory
    batchProcess=True
)
```

### File Organization

```
project_directory/
├── emon_config.yml              # Legacy file (fallback)
├── 20250115-0800.yml            # Settings from Jan 15, 08:00
├── 20250115-1700.yml            # Settings from Jan 15, 17:00
├── 20250120-0000.yml            # Settings from Jan 20, 00:00
└── 20250122-0900.yml            # Settings from Jan 22, 09:00
```

### Processing Historical Data

```python
# When processing historical log data, the correct settings file for that time period
# will be automatically selected
influx.process_file("path/to/historical_logfile.TXT")
```

The system will:
1. Read each log entry with its timestamp
2. Determine which settings file applies to that timestamp
3. Apply the correct configuration for that time period
4. Switch settings automatically if a different time period is encountered

## New Methods

### `_parse_settings_filename(filename)`
Parses a filename to extract the datetime if it matches the `YYYYMMDD-hhmm.yml` format.

**Returns:** 
- `datetime.datetime` object if valid format
- `None` if invalid format

### `_scan_settings_files()`
Scans the settings directory for all valid settings files (both timestamped and legacy).

**Returns:** 
- Sorted list of tuples: `(datetime, filename, full_path)`
- Sorted chronologically (earliest to latest)

### `_get_applicable_settings_file(current_time=None)`
Determines which settings file should be used for a given time.

**Parameters:**
- `current_time`: `datetime.datetime` object (defaults to current system time)

**Returns:**
- Full path to the applicable settings file
- Falls back to `emon_config.yml` if no timestamped files match
- Falls back to original `settingsPath` if nothing else found

### `_load_settings_from_file(filepath)`
Loads and parses a settings YAML file.

**Returns:**
- Parsed settings dictionary on success
- `None` on failure

### `_load_settings()`
Loads settings from the appropriate file based on current time and available files. Called during initialization and whenever settings need to be reloaded.

### `check_and_reload_settings()`
Checks if new settings files have been created and reloads if necessary. Uses system time.

**Returns:**
- `True` if settings were reloaded
- `False` if no changes were needed

### `check_and_reload_settings_by_time(current_time=None)`
Checks if settings need to be changed based on provided time (useful for historical data processing).

**Parameters:**
- `current_time`: `datetime.datetime` object (defaults to current system time)

**Returns:**
- `True` if settings were reloaded
- `False` if no changes were needed

## Configuration

### Adjusting Settings Check Interval

You can modify the interval at which the system checks for new settings files:

```python
influx = emon_influx(settingsPath="./emon_config.yml")
influx.settingsCheckInterval = 30  # Check every 30 seconds instead of 60
```

## Logging and Debugging

The system provides informative console messages:

- When loading settings: `Loaded settings from: filename.yml`
- When detecting new files: `New settings files detected, rescanning...`
- When switching settings: `Switching settings from old_file.yml to new_file.yml`
- Error messages for failed loads or scanning issues

## Implementation Notes

1. **Settings Validation**: Ensure each `.yml` file contains a complete and valid YAML structure matching your original `emon_config.yml` format.

2. **Timestamp Format**: Use strict `YYYYMMDD-hhmm` format. Invalid formats are silently ignored.

3. **Performance**: Scanning for new files happens periodically (every 60 seconds by default) to minimize performance impact.

4. **Backward Compatibility**: Existing code using `emon_influx` requires no changes. The enhanced features work transparently.

5. **Thread Safety**: Settings checks are lightweight and should not cause significant delays in message processing.

## Example Scenarios

### Scenario 1: Daily Configuration Change
```
20250101-0000.yml   # January configuration
20250201-0000.yml   # February configuration
```

### Scenario 2: Peak/Off-Peak Settings
```
20250120-0600.yml   # Off-peak settings (6 AM)
20250120-0900.yml   # Peak settings (9 AM)
20250120-1700.yml   # Peak settings continue (5 PM)
20250120-1900.yml   # Off-peak settings (7 PM)
```

### Scenario 3: Mixed Environment
```
emon_config.yml         # Fallback/default settings
20250115-0000.yml       # Special configuration from Jan 15
```
When processing data:
- Before Jan 15: Uses `emon_config.yml`
- From Jan 15 onwards: Uses `20250115-0000.yml`

---

**Version:** 1.0  
**Date:** January 2025  
**Compatibility:** Python 3.6+
