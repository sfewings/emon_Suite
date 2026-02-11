#!/usr/bin/env python3
"""
Example usage of the enhanced emon_influx.py with multiple settings files.

This demonstrates how the new features work:
1. Time-based settings file selection
2. Automatic detection of new settings files
3. Backward compatibility with emon_config.yml
4. Processing historical data with correct settings
"""

from pyemonlib.emon_influx import emon_influx
import datetime

# Example 1: Basic Usage with Settings Directory
# =============================================
def example_basic_usage():
    """
    Basic usage - settings are automatically selected based on timestamps.
    No code changes needed from original implementation.
    """
    print("Example 1: Basic Usage")
    print("-" * 50)
    
    # Create influx instance - settings will be auto-detected
    influx = emon_influx(
        url="http://localhost:8086",
        settingsPath="./config/emon_config.yml",  # Can point to directory
        batchProcess=True
    )
    
    # Process historical data - settings automatically switch as needed
    influx.process_file("./data/20250115.TXT")  # Uses settings for Jan 15
    influx.process_file("./data/20250120.TXT")  # Auto-switches to Jan 20 settings
    
    print()


# Example 2: Dynamic Settings During Live Processing
# ==================================================
def example_live_processing():
    """
    Live processing with dynamic settings updates.
    New settings files created during runtime are detected automatically.
    """
    print("Example 2: Live Processing with Dynamic Settings")
    print("-" * 50)
    
    influx = emon_influx(
        url="http://localhost:8086",
        settingsPath="./config/",
        batchProcess=False  # Use synchronous writing for live data
    )
    
    # Configure check interval (default is 60 seconds)
    influx.settingsCheckInterval = 30  # Check every 30 seconds for new files
    
    # Simulate processing live data
    # While this runs, new settings files will be detected automatically
    print("Processing live data... (settings checked every 30 seconds)")
    print("You can add new .yml files while this runs - they'll be detected!")
    
    # In real usage:
    # while True:
    #     command, time, line = receive_data_from_serial()
    #     influx.process_line(command, time, line)
    #     # Settings are automatically checked and reloaded as needed
    
    print()


# Example 3: Checking Settings Status
# ===================================
def example_check_settings():
    """
    Inspect which settings files are available and which is active.
    """
    print("Example 3: Inspecting Settings Status")
    print("-" * 50)
    
    influx = emon_influx(settingsPath="./config/")
    
    # View available settings files
    print(f"Available settings files: {len(influx.availableSettingsFiles)}")
    for dt, filename, filepath in influx.availableSettingsFiles:
        print(f"  - {filename} (effective from {dt})")
    
    # View currently loaded settings file
    print(f"\nCurrently loaded: {influx.currentSettingsFile}")
    
    # View settings for specific time
    test_time = datetime.datetime(2025, 1, 20, 14, 30)
    applicable = influx._get_applicable_settings_file(test_time)
    print(f"For timestamp {test_time}: {applicable}")
    
    print()


# Example 4: Manual Settings Reload
# ================================
def example_manual_reload():
    """
    Demonstrate manual settings reload.
    Useful if you want to force a reload at specific times.
    """
    print("Example 4: Manual Settings Operations")
    print("-" * 50)
    
    influx = emon_influx(settingsPath="./config/")
    
    # Manually force a complete settings reload
    print("Current settings file:", influx.currentSettingsFile)
    
    # Force re-scanning for new files
    influx.availableSettingsFiles = influx._scan_settings_files()
    print("Settings files rescanned")
    
    # Check for settings updates (doesn't force reload, just checks)
    settings_changed = influx.check_and_reload_settings()
    if settings_changed:
        print("Settings were reloaded")
    else:
        print("No settings changes needed")
    
    # Check settings for a specific time
    specific_time = datetime.datetime(2025, 1, 15, 8, 0)
    settings_changed = influx.check_and_reload_settings_by_time(specific_time)
    print(f"Settings for {specific_time}: {'changed' if settings_changed else 'no change'}")
    
    print()


# Example 5: Directory Structure
# =============================
def example_directory_structure():
    """
    Show recommended directory structure for settings files.
    """
    print("Example 5: Recommended Directory Structure")
    print("-" * 50)
    
    structure = """
    project_root/
    ├── emon_influx.py
    ├── config/
    │   ├── emon_config.yml              ← Fallback/default settings
    │   ├── 20250101-0000.yml            ← January settings
    │   ├── 20250115-0900.yml            ← Jan 15, 9 AM settings
    │   ├── 20250120-1700.yml            ← Jan 20, 5 PM settings
    │   └── 20250201-0000.yml            ← February settings
    ├── data/
    │   ├── 20250101.TXT
    │   ├── 20250115.TXT
    │   ├── 20250120.TXT
    │   └── 20250201.TXT
    └── main.py
    
    Usage:
        influx = emon_influx(settingsPath="./config/")
        influx.process_files("./data/")
    """
    print(structure)
    print()


# Example 6: Handling Settings Transitions
# ========================================
def example_settings_transitions():
    """
    Demonstrate how settings transitions work when processing data.
    """
    print("Example 6: Settings File Transitions During Processing")
    print("-" * 50)
    
    # Assume we have these settings files:
    # - 20250115-0800.yml (Peak hours)
    # - 20250115-1700.yml (Off-peak hours)
    # - 20250120-0800.yml (New peak hours after maintenance)
    
    example_timeline = """
    Processing 20250115.TXT file:
    
    08:30 - Message with timestamp 2025-01-15 08:30
            Selected settings: 20250115-0800.yml
    
    10:00 - Message with timestamp 2025-01-15 10:00
            Selected settings: 20250115-0800.yml (same, no change)
    
    18:00 - Message with timestamp 2025-01-15 18:00
            Selected settings: 20250115-1700.yml (switched!)
            Logs: "Switching settings from 20250115-0800.yml to 20250115-1700.yml"
    
    Processing 20250120.TXT file:
    
    09:00 - Message with timestamp 2025-01-20 09:00
            Selected settings: 20250120-0800.yml (switched again!)
            Logs: "Switching settings from 20250115-1700.yml to 20250120-0800.yml"
    
    10:30 - Message with timestamp 2025-01-20 10:30
            Selected settings: 20250120-0800.yml (same)
    """
    print(example_timeline)
    print()


# Example 7: Configuration File Template
# ======================================
def example_settings_file_format():
    """
    Show the format of timestamped settings files.
    """
    print("Example 7: Settings File Format")
    print("-" * 50)
    
    yaml_content = """
    # File: 20250115-0900.yml
    # Settings effective from 2025-01-15 09:00
    
    rain:
      - name: "Main Rain Gauge"
        mmPerPulse: 0.2
    
    temp:
      0:
        name: "Temperature Node 1"
        t0: "Indoor Temp"
        t1: "Outdoor Temp"
    
    pulse:
      0:
        name: "Power Node 1"
        p0: "Mains Power"
        p1: "Solar Power"
    
    # ... rest of configuration matching your emon_config.yml structure
    """
    print(yaml_content)
    print()


# Main
# ====
if __name__ == "__main__":
    print("=" * 60)
    print("EMON_INFLUX MULTIPLE SETTINGS FILES - EXAMPLES")
    print("=" * 60)
    print()
    
    # Run examples
    example_directory_structure()
    example_settings_file_format()
    example_basic_usage()
    example_live_processing()
    example_check_settings()
    example_manual_reload()
    example_settings_transitions()
    
    print("=" * 60)
    print("For more information, see:")
    print("  - SETTINGS_FEATURES.md (detailed documentation)")
    print("  - SETTINGS_QUICK_REFERENCE.md (quick reference guide)")
    print("=" * 60)
