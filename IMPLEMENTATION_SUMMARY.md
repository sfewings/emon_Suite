# Implementation Summary: Multiple Settings Files for emon_influx.py

## Overview
Enhanced `emon_influx.py` to support multiple timestamped settings files while maintaining full backward compatibility with the existing `emon_config.yml` approach.

## Changes Made

### 1. Modified `__init__` Method
- **What Changed**: Added settings path tracking and initialization
- **New Instance Variables**:
  - `self.settingsPath`: Path to settings file/directory
  - `self.settingsDirectory`: Directory containing settings files
  - `self.currentSettingsFile`: Currently loaded settings file path
  - `self.availableSettingsFiles`: List of detected settings files
  - `self.lastSettingsFileCheck`: Timestamp of last settings scan
  - `self.settingsCheckInterval`: Interval (in seconds) for checking new files (default: 60)

- **New Behavior**:
  - Calls `_load_settings()` instead of directly opening a file
  - Automatically detects and loads appropriate settings file

### 2. New Helper Methods

#### `_parse_settings_filename(filename)`
- **Purpose**: Parse filenames to extract datetime in `YYYYMMDD-hhmm.yml` format
- **Input**: Filename string
- **Output**: `datetime.datetime` object or `None`
- **Logic**: Uses regex to validate format, then parses to datetime

#### `_scan_settings_files()`
- **Purpose**: Discover all valid settings files in the directory
- **Returns**: Sorted list of tuples `(datetime, filename, full_path)`
- **Sorting**: Chronological order (earliest first), with `emon_config.yml` as fallback
- **Handles**: File system errors gracefully

#### `_get_applicable_settings_file(current_time=None)`
- **Purpose**: Determine which settings file to use for a given time
- **Logic**: Selects most recent file whose timestamp ≤ current_time
- **Fallback Chain**:
  1. Timestamped settings file matching the time
  2. Legacy `emon_config.yml`
  3. Original `settingsPath`
- **Returns**: Full file path or `None`

#### `_load_settings_from_file(filepath)`
- **Purpose**: Load and parse a YAML settings file
- **Error Handling**: Returns `None` on failure, logs error message
- **Returns**: Parsed settings dict or `None`

#### `_load_settings()`
- **Purpose**: Main settings loading logic
- **Steps**:
  1. Scans directory for available files
  2. Determines applicable file for current time
  3. Loads and parses the file
  4. Updates `self.settings` and `self.currentSettingsFile`
  5. Logs status messages

#### `check_and_reload_settings()`
- **Purpose**: Periodic check for new files and settings changes (uses system time)
- **Behavior**:
  - Only performs full scan at specified intervals
  - Detects new settings files
  - Reloads if applicable file changes
- **Returns**: `True` if reloaded, `False` if no changes

#### `check_and_reload_settings_by_time(current_time=None)`
- **Purpose**: Check and reload settings based on provided timestamp
- **Use Case**: Processing historical log files with time-aware settings
- **Parameters**: `current_time` as `datetime.datetime` (defaults to now)
- **Behavior**:
  - Scans for new files at intervals
  - Determines applicable file for given time
  - Reloads if file changes
- **Returns**: `True` if reloaded, `False` if no changes

### 3. Modified `process_line` Method
- **Change**: Added automatic settings check before processing
- **Call**: `self.check_and_reload_settings_by_time(time)` is called first
- **Effect**: Settings are automatically switched based on message timestamp

## File Naming Convention

```
YYYYMMDD-hhmm.yml
```

- **YYYY**: 4-digit year (2000-9999)
- **MM**: 2-digit month (01-12)
- **DD**: 2-digit day (01-31)
- **hh**: 2-digit hour in 24-hour format (00-23)
- **mm**: 2-digit minute (00-59)

**Valid Examples**:
- `20250122-0900.yml` - January 22, 2025 at 09:00
- `20250115-1430.yml` - January 15, 2025 at 14:30
- `emon_config.yml` - Legacy format (supported)

**Invalid Examples**:
- `2025-01-22-0900.yml` - Wrong date format
- `20250122_0900.yml` - Wrong separator
- `settings.yml` - No timestamp

## File Selection Logic

When processing data with timestamp T:

1. **Scan available files** - Get all `.yml` files in directory
2. **Filter by timestamp** - Find files with datetime ≤ T
3. **Select latest** - Use the most recent matching file
4. **Fallback to legacy** - Use `emon_config.yml` if no match found
5. **Log transition** - Report if settings file changed

### Example

For timestamp `2025-01-22 14:30`:

```
Files Available:
├── 20250101-0000.yml    (Jan 1 00:00) ✓ Before → Selected (latest match)
├── 20250115-0800.yml    (Jan 15 08:00) ✓ Before
├── 20250122-1700.yml    (Jan 22 17:00) ✗ After (5 PM > 2:30 PM)
└── emon_config.yml      (Fallback)

Result: Uses 20250115-0800.yml
```

## Key Features

### ✓ Backward Compatibility
- Existing code works without changes
- `emon_config.yml` still works as fallback
- All new features are optional

### ✓ Time-Based Selection
- Settings match timestamps in historical data
- Correct configuration applied to each time period
- Automatic switching during processing

### ✓ Dynamic File Detection
- New files detected automatically
- No restart required
- Configurable check interval (default 60 seconds)

### ✓ Robust Error Handling
- Gracefully handles missing files
- Continues with previous settings if load fails
- Logs all errors and transitions

### ✓ Performance Optimized
- Settings scanning only happens periodically
- File list cached between checks
- Minimal performance impact

## Configuration

### Default Behavior
```python
influx = emon_influx(settingsPath="./emon_config.yml")
# Automatically:
# - Detects timestamped .yml files
# - Checks every 60 seconds for new files
# - Switches settings based on message timestamps
# - Falls back to emon_config.yml if needed
```

### Customize Check Interval
```python
influx = emon_influx(settingsPath="./emon_config.yml")
influx.settingsCheckInterval = 30  # Check every 30 seconds instead of 60
```

### Manual Control
```python
# Force settings reload
influx._load_settings()

# Check for updates (system time)
settings_changed = influx.check_and_reload_settings()

# Check for updates (specific time)
import datetime
time = datetime.datetime(2025, 1, 20, 14, 30)
settings_changed = influx.check_and_reload_settings_by_time(time)
```

## Use Cases

### 1. Historical Data Processing
```python
# Data from different time periods uses correct settings
influx.process_file("logs/20250115.TXT")  # Uses Jan 15 settings
influx.process_file("logs/20250120.TXT")  # Auto-switches to Jan 20 settings
```

### 2. Time-of-Day Configuration
```
config/
├── 20250120-0600.yml   # Off-peak (6 AM)
├── 20250120-0900.yml   # Peak (9 AM)
└── 20250120-1700.yml   # Off-peak (5 PM)
```

### 3. Seasonal Changes
```
config/
├── 20250101-0000.yml   # Winter
├── 20250401-0000.yml   # Spring
├── 20250701-0000.yml   # Summer
└── 20251001-0000.yml   # Autumn
```

### 4. Equipment Changes
```
config/
├── emon_config.yml      # Initial
├── 20250110-1200.yml    # New sensor added
└── 20250120-0800.yml    # Calibration updated
```

## Logging Output

When settings are changed, you'll see:
```
Loaded settings from: 20250115-0800.yml
New settings files detected, rescanning...
Switching settings from 20250115-0800.yml to 20250120-0900.yml (for time 2025-01-20 09:30:00)
```

## Testing Verification

✓ No syntax errors  
✓ Backward compatible with original API  
✓ Settings files detected and scanned correctly  
✓ Timestamp parsing validates format  
✓ Time-based file selection works correctly  
✓ Fallback to `emon_config.yml` functions  
✓ Dynamic file detection integrated  
✓ Error handling robust  

## Files Modified

1. **emon_influx.py**
   - Enhanced `__init__` method
   - Added 7 new methods for settings management
   - Modified `process_line` to check for settings updates

## Files Created (Documentation)

1. **SETTINGS_FEATURES.md** - Comprehensive feature documentation
2. **SETTINGS_QUICK_REFERENCE.md** - Quick reference guide
3. **examples_multiple_settings.py** - Code examples and demonstrations

## Migration Guide

### For Existing Users
No migration needed! Your existing code continues to work:

```python
# This still works exactly as before
influx = emon_influx(settingsPath="./emon_config.yml")
influx.process_files("./data/")
```

### To Use New Features
Simply add timestamped settings files:

```
your_directory/
├── emon_config.yml           ← Keep this as fallback
├── 20250115-0900.yml         ← Add new timestamped files
└── 20250120-1430.yml
```

That's it! Settings will be automatically selected based on timestamps.

## Performance Impact

- **Minimal**: Settings checks happen every 60 seconds (configurable)
- **Memory**: One additional list to cache available files
- **Processing**: No impact on per-message processing time
- **Startup**: Slightly slower due to directory scan (negligible)

## Summary

The enhancement successfully adds robust support for multiple timestamped settings files while maintaining complete backward compatibility. Users can opt-in to the new features or continue using the legacy approach without any code changes.

---

**Status**: ✓ Complete and tested
**Compatibility**: Python 3.6+
**Date**: January 22, 2025
