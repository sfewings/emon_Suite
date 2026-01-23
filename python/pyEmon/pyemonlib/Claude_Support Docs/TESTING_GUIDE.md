# Testing Guide: Multiple Settings Files in emon_influx.py

## Test Checklist

### ✓ Unit Tests

#### Test 1: Filename Parsing
```python
def test_parse_settings_filename():
    influx = emon_influx()
    
    # Valid formats
    assert influx._parse_settings_filename("20250115-0900.yml") is not None
    assert influx._parse_settings_filename("20250101-0000.yml") is not None
    assert influx._parse_settings_filename("20251231-2359.yml") is not None
    
    # Invalid formats
    assert influx._parse_settings_filename("emon_config.yml") is None
    assert influx._parse_settings_filename("20250115.yml") is None
    assert influx._parse_settings_filename("2025-01-15-0900.yml") is None
    assert influx._parse_settings_filename("invalid.yml") is None
    
    # Verify datetime values
    dt = influx._parse_settings_filename("20250115-0930.yml")
    assert dt.year == 2025
    assert dt.month == 1
    assert dt.day == 15
    assert dt.hour == 9
    assert dt.minute == 30
```

#### Test 2: Directory Scanning
```python
def test_scan_settings_files():
    # Setup test directory with:
    # - emon_config.yml
    # - 20250101-0000.yml
    # - 20250115-0900.yml
    # - 20250120-1430.yml
    # - invalid_file.txt
    
    influx = emon_influx(settingsPath="./test_config/")
    files = influx._scan_settings_files()
    
    # Should find 4 files (3 timestamped + 1 legacy)
    assert len(files) == 4
    
    # Should be sorted chronologically
    assert files[0][1] == "20250101-0000.yml"
    assert files[1][1] == "20250115-0900.yml"
    assert files[2][1] == "20250120-1430.yml"
    assert files[3][1] == "emon_config.yml"  # Legacy file last
    
    # Invalid file should not be included
    filenames = [f[1] for f in files]
    assert "invalid_file.txt" not in filenames
```

#### Test 3: File Selection by Time
```python
def test_get_applicable_settings_file():
    # Given files:
    # - 20250101-0000.yml
    # - 20250115-0900.yml
    # - 20250120-1430.yml
    # - emon_config.yml
    
    influx = emon_influx(settingsPath="./test_config/")
    
    # Before all timestamped files
    time1 = datetime.datetime(2024, 12, 31, 23, 59)
    file1 = influx._get_applicable_settings_file(time1)
    assert file1.endswith("emon_config.yml")  # Fallback
    
    # Between Jan 1 and Jan 15
    time2 = datetime.datetime(2025, 1, 10, 12, 0)
    file2 = influx._get_applicable_settings_file(time2)
    assert file2.endswith("20250101-0000.yml")
    
    # Between Jan 15 (exact time) and Jan 20
    time3 = datetime.datetime(2025, 1, 15, 9, 0)
    file3 = influx._get_applicable_settings_file(time3)
    assert file3.endswith("20250115-0900.yml")
    
    # Exactly at 20250120-1430
    time4 = datetime.datetime(2025, 1, 20, 14, 30)
    file4 = influx._get_applicable_settings_file(time4)
    assert file4.endswith("20250120-1430.yml")
    
    # After 20250120-1430
    time5 = datetime.datetime(2025, 1, 25, 10, 0)
    file5 = influx._get_applicable_settings_file(time5)
    assert file5.endswith("20250120-1430.yml")  # Still this one (latest)
    
    # Far future
    time6 = datetime.datetime(2026, 12, 31, 23, 59)
    file6 = influx._get_applicable_settings_file(time6)
    assert file6.endswith("20250120-1430.yml")  # Still this one (latest)
```

#### Test 4: Settings Loading
```python
def test_load_settings():
    influx = emon_influx(settingsPath="./test_config/")
    
    # Check that settings were loaded
    assert influx.settings is not None
    assert isinstance(influx.settings, dict)
    assert len(influx.settings) > 0
    
    # Check that current file is tracked
    assert influx.currentSettingsFile is not None
    assert os.path.isfile(influx.currentSettingsFile)
```

#### Test 5: Settings Reload on Time Change
```python
def test_reload_settings_by_time():
    influx = emon_influx(settingsPath="./test_config/")
    
    initial_file = influx.currentSettingsFile
    
    # Check for different time - should reload if applicable file changed
    time1 = datetime.datetime(2025, 1, 10, 12, 0)
    changed = influx.check_and_reload_settings_by_time(time1)
    # Changed could be True or False depending on initial load
    
    # Later time in same period - should not reload
    time2 = datetime.datetime(2025, 1, 10, 15, 0)
    changed = influx.check_and_reload_settings_by_time(time2)
    assert changed == False or influx.currentSettingsFile == initial_file
    
    # Move to different time period - should reload
    time3 = datetime.datetime(2025, 1, 20, 15, 0)
    changed = influx.check_and_reload_settings_by_time(time3)
    # Settings should reflect new time period
```

### ✓ Integration Tests

#### Test 6: Process Line with Settings Check
```python
def test_process_line_integration():
    influx = emon_influx(settingsPath="./test_config/")
    
    # Mock the dispatch method
    messages_processed = []
    def mock_rain_message(time, line, settings):
        messages_processed.append((time, line, settings))
    
    influx.rainMessage = mock_rain_message
    
    # Process a line
    time = datetime.datetime(2025, 1, 15, 10, 0)
    line = "test,data"
    influx.process_line("rain", time, line)
    
    # Verify message was processed
    assert len(messages_processed) == 1
    assert messages_processed[0][0] == time
    assert messages_processed[0][1] == line
```

#### Test 7: Process Multiple Files with Settings Changes
```python
def test_process_files_with_settings_changes():
    influx = emon_influx(settingsPath="./test_config/")
    
    settings_switches = []
    original_load = influx._load_settings
    
    def track_settings_load():
        settings_switches.append(influx.currentSettingsFile)
        original_load()
    
    influx._load_settings = track_settings_load
    
    # Process multiple files with different date ranges
    # Each should switch to appropriate settings
    
    # Would need test data files with appropriate timestamps
```

#### Test 8: New File Detection
```python
def test_new_file_detection():
    influx = emon_influx(settingsPath="./test_config/")
    
    initial_files = influx._scan_settings_files()
    initial_count = len(initial_files)
    
    # Create a new settings file
    new_file = os.path.join(influx.settingsDirectory, "20250125-1000.yml")
    with open(new_file, 'w') as f:
        f.write("test: data\n")
    
    # Scan again
    new_files = influx._scan_settings_files()
    
    # Should detect the new file
    assert len(new_files) == initial_count + 1
    
    # Clean up
    os.remove(new_file)
```

### ✓ Manual Tests

#### Test 9: Backward Compatibility
```python
# Test that original usage still works
def test_backward_compatibility():
    # Old-style usage with single file
    influx = emon_influx(
        url="http://localhost:8086",
        settingsPath="./emon_config.yml",
        batchProcess=True
    )
    
    # Should load without errors
    assert influx.settings is not None
    assert influx.currentSettingsFile is not None
    assert influx.currentSettingsFile.endswith("emon_config.yml")
```

#### Test 10: Console Output Verification
```python
# Run with various settings files and verify console output
def test_console_output():
    # Create test environment with:
    # - emon_config.yml
    # - 20250101-0000.yml
    # - 20250115-0900.yml
    
    influx = emon_influx(settingsPath="./test_config/")
    
    # Verify console shows:
    # "Loaded settings from: 20250101-0000.yml"
    # or similar message
    
    # Process messages at different times
    # Verify console shows setting switches:
    # "Switching settings from 20250101-0000.yml to 20250115-0900.yml"
```

## Test Data Setup

### Directory Structure
```
test_config/
├── emon_config.yml              # Minimal valid YAML
├── 20250101-0000.yml            # Valid timestamped file
├── 20250115-0900.yml            # Valid timestamped file
└── 20250120-1430.yml            # Valid timestamped file
```

### Minimal emon_config.yml Content
```yaml
rain:
  - name: "Test Gauge"
    mmPerPulse: 0.2

temp:
  0:
    name: "Test Node"
    t0: "Temp 1"

pulse:
  0:
    name: "Power Node"
    p0: "Power 1"
```

### Test Timestamped Files
Each should be identical YAML structure (can be same as above).

## Running Tests

### Using pytest
```bash
pytest test_emon_influx.py -v
```

### Using unittest
```bash
python -m unittest test_emon_influx -v
```

### Manual verification
```python
# Quick manual check
from pyemonlib.emon_influx import emon_influx

# Create instance
influx = emon_influx(settingsPath="./config/")

# Verify attributes exist
print(f"Settings: {influx.settings}")
print(f"Current file: {influx.currentSettingsFile}")
print(f"Available files: {len(influx.availableSettingsFiles)}")

# List files
for dt, filename, path in influx.availableSettingsFiles:
    print(f"  {filename} (from {dt})")

# Test file selection
import datetime
time = datetime.datetime(2025, 1, 20, 14, 30)
applicable = influx._get_applicable_settings_file(time)
print(f"For {time}: {applicable}")
```

## Expected Behavior

### Scenario 1: Single emon_config.yml
- Loads without error
- Uses emon_config.yml as currentSettingsFile
- No console messages about switching

### Scenario 2: Multiple Timestamped Files
- Loads most recent applicable file
- Shows "Loaded settings from: YYYYMMDD-hhmm.yml"
- Settings match selected file

### Scenario 3: Missing Files
- Falls back to emon_config.yml
- Prints error if neither exists
- Continues operation (settings may be empty)

### Scenario 4: Time-Based Selection
- Selects correct file for given timestamp
- Switches automatically during message processing
- Logs transitions to console

### Scenario 5: New File Detection
- Periodically scans for new files
- Detects additions without restart
- Switches to new file if applicable

## Edge Cases to Test

1. **Empty Directory** - Should fall back to settingsPath
2. **Missing settingsPath** - Should print error but continue
3. **Corrupted YAML** - Should print error, keep previous settings
4. **Unreadable File** - Should print error, continue
5. **Very Old Timestamp** - Should use earliest file
6. **Very Future Timestamp** - Should use latest file
7. **Exact Match Time** - Should use matching file
8. **Millisecond Differences** - Should select correctly
9. **Timezone Issues** - Verify datetime handling
10. **Concurrent File Changes** - Verify thread safety

## Performance Testing

### Metrics to Monitor
- Time to scan directory
- Time to parse filename
- Memory for file list storage
- Performance impact per message

### Load Test
```python
# Process many messages
influx = emon_influx(settingsPath="./config/")

import time
start = time.time()

# Process 10000 messages
for i in range(10000):
    dt = datetime.datetime(2025, 1, 15, 9, 0)
    influx.process_line("rain", dt, f"test,data,{i}")

elapsed = time.time() - start
print(f"Processed 10000 messages in {elapsed:.2f} seconds")
print(f"Average: {elapsed/10000*1000:.3f} ms per message")
```

---

**Test Status**: Ready for implementation  
**Coverage**: Core functionality, edge cases, integration points  
**Date**: January 2025
