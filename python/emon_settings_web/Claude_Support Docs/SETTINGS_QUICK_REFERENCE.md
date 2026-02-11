# Quick Reference: Multiple Settings Files in emon_influx.py

## Quick Start

### File Naming Convention
```
YYYYMMDD-hhmm.yml
│       │ │  └─ Minutes (00-59)
│       │ └──── Hours (00-23)
│       └────── Date (YYYY=year, MM=month, DD=day)
```

### Valid Examples
- `20250122-0900.yml` ✓
- `20250115-1430.yml` ✓
- `20250101-0000.yml` ✓
- `emon_config.yml` ✓ (legacy, still supported)

### Invalid Examples
- `2025-01-22-0900.yml` ✗ (wrong date format)
- `20250122_0900.yml` ✗ (underscore instead of dash)
- `settings_20250122.yml` ✗ (date not in right position)

## How It Works

### Selecting Settings Files
When processing a message timestamped at `2025-01-22 14:30`:

```
Available files:           Applicable to 2025-01-22 14:30?
20250101-0000.yml         ✓ (Jan 1 is before Jan 22) → SELECTED
20250115-0800.yml         ✓ (Jan 15 is before Jan 22)
20250122-1700.yml         ✗ (5 PM is after 2:30 PM)
20250125-0000.yml         ✗ (Jan 25 is after Jan 22)
emon_config.yml           (fallback if no match)
```

**Result:** Uses `20250115-0800.yml` (latest file before the message time)

## Common Use Cases

### Case 1: Time-of-Day Settings Changes
```
project/
├── settings/
│   ├── 20250120-0600.yml    # Off-peak hours (6 AM - 9 AM)
│   ├── 20250120-0900.yml    # Peak hours (9 AM - 5 PM)
│   └── 20250120-1700.yml    # Off-peak hours (5 PM onwards)
```

When processing:
- 08:00 → Uses `20250120-0600.yml`
- 11:00 → Uses `20250120-0900.yml`
- 18:00 → Uses `20250120-1700.yml`

### Case 2: Seasonal Configuration
```
project/
├── emon_config.yml          # Default/winter
├── 20250401-0000.yml        # Spring
├── 20250701-0000.yml        # Summer
└── 20251001-0000.yml        # Autumn
```

### Case 3: Equipment Changes
```
project/
├── emon_config.yml                  # Initial setup
├── 20250110-1200.yml                # New sensor added
└── 20250120-0800.yml                # Old sensor removed, new calibration
```

## Integration with Existing Code

**No changes required!** The enhancement is transparent:

```python
# Your existing code works exactly the same
from pyemonlib.emon_influx import emon_influx

influx = emon_influx(settingsPath="./")
influx.process_files("./data/")
```

The system automatically:
- Scans for all `.yml` files in the directory
- Selects the right settings based on message timestamps
- Reloads settings when new files appear (every 60 seconds)

## Configuration Tuning

### Change Settings Check Interval
```python
influx = emon_influx(settingsPath="./")
influx.settingsCheckInterval = 30  # Check every 30 seconds
```

### Disable Automatic Checking
```python
# Just don't call check_and_reload_settings()
# It's called automatically from process_line()
# but you can prevent calls if needed
```

## Monitoring

Settings changes are logged to console:
```
Loaded settings from: 20250115-0800.yml
New settings files detected, rescanning...
Switching settings from 20250115-0800.yml to 20250120-0900.yml (for time 2025-01-20 09:30:00)
```

## Troubleshooting

### Settings not changing?
1. Check filename format: `YYYYMMDD-hhmm.yml` exactly
2. Verify the date/time is in the past relative to processed messages
3. Check file permissions (must be readable)
4. Look for console error messages

### No settings file found?
- Ensure `emon_config.yml` exists as a fallback
- Check directory path in `settingsPath`
- Verify at least one `*.yml` file exists

### Old settings being used?
- The most recent file ≤ message timestamp is selected
- Add a new file with an earlier timestamp if needed
- Check message timestamps match your local timezone

## Examples

### Processing Historical Data with Changing Settings
```python
influx = emon_influx(settingsPath="./config/")

# Process log file from Jan 15
# Automatically uses applicable settings file for that date
influx.process_file("./logs/20250115.TXT")

# Process log file from Jan 20
# Automatically switches to settings file for Jan 20
influx.process_file("./logs/20250120.TXT")
```

### Live Processing with Dynamic Settings Updates
```python
influx = emon_influx(settingsPath="./config/")

# While the script is running, you can add new settings files
# They'll be detected and applied automatically
# (checked every 60 seconds)

while True:
    # Process incoming data
    # Settings are automatically checked for updates
    influx.process_line(command, timestamp, data)
```

## File Content

Each settings file should contain the same structure as your original `emon_config.yml`:

```yaml
# Example 20250120-0900.yml
rain:
  - name: "Main Gauge"
    mmPerPulse: 0.2

temp:
  0:
    name: "Temp Node 1"
    t0: "Temperature Sensor 1"
    t1: "Temperature Sensor 2"

# ... rest of your configuration
```

---

**Key Points:**
- ✓ Multiple settings files supported
- ✓ Backward compatible with `emon_config.yml`
- ✓ Automatic time-based selection
- ✓ Dynamic file detection
- ✓ No code changes needed
- ✓ Transparent operation
