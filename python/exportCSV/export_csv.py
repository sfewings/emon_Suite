#!/usr/bin/env python3
"""
CSV exporter for emon log files.

Reads YYYYMMDD.TXT log files, resolves sensor names from YAML settings,
filters to user-selected sensors/groups, and outputs a single wide-format CSV.

Usage:
    python export_csv.py --start "2026-03-24 00:00:00" --end "2026-03-24 23:59:59" \
        --log-folder /path/to/logs --settings-folder /path/to/settings \
        --output export.csv

    python export_csv.py --list-sensors --settings-folder /path/to/settings

    python export_csv.py --start ... --end ... --log-folder ... --settings-folder ... \
        --config export_config.yml
"""

import argparse
import csv
import datetime
import os
import re
import sys

import yaml
import pytz

# Add pyEmon to path for EmonSettings import
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_script_dir, '..', 'pyEmon'))
from pyemonlib.emon_settings import EmonSettings

import log_parser


# --- Sensor name resolution ---

# Maps (device_type, field_key) -> settings key pattern
# For devices where each sensor has its own name in settings
_NAMED_SENSOR_FIELDS = {
    'temp': {'field_prefix': 't', 'count_from_payload': True},
    'pulse': {'field_prefix': 'p', 'count': log_parser.PULSE_MAX_SENSORS},
    'hws_temp': {'field_prefix': 't', 'count': log_parser.HWS_TEMPERATURES},
    'hws_pump': {'field_prefix': 'p', 'count': log_parser.HWS_PUMPS},
    'bat_shunt': {'field_prefix': 's', 'count': log_parser.BATTERY_SHUNTS},
    'bat_voltage': {'field_prefix': 'v', 'count': log_parser.MAX_VOLTAGES},
    'wtr_flow': {'field_prefix': 'f', 'count_from_payload': True},
    'wtr_height': {'field_prefix': 'h', 'count_from_payload': True},
}


def resolve_sensor_columns(device_type, subnode, fields, settings):
    """Map parsed fields to human-readable CSV column names using settings.

    Args:
        device_type: e.g. "temp", "bat", "pulse"
        subnode: integer subnode ID
        fields: dict of {field_key: value} from parser
        settings: full settings dict from EmonSettings

    Returns:
        dict of {column_name: value} for this line's data.
        Skips sensors named "Unused".
    """
    node_settings = settings.get(device_type, {})
    subnode_settings = node_settings.get(subnode, {})
    group_name = subnode_settings.get('name', f'{device_type}/{subnode}')
    columns = {}

    if device_type == 'temp':
        for key, value in fields.items():
            if key.startswith('t') and key[1:].isdigit():
                sensor_name = subnode_settings.get(key, f'{group_name} - {key}')
                if sensor_name != 'Unused':
                    columns[f'{group_name} / {sensor_name}'] = value
            elif key == 'supplyV':
                columns[f'{group_name} / supplyV'] = value

    elif device_type == 'disp':
        if group_name != 'Unused':
            columns[f'{group_name} / temperature'] = fields.get('temperature')

    elif device_type == 'pulse':
        for key, value in fields.items():
            if key.startswith('p') and key[1:].isdigit():
                sensor_name = subnode_settings.get(key, f'{group_name} - {key}')
                if sensor_name != 'Unused':
                    columns[f'{group_name} / {sensor_name} - power'] = value
            elif key.startswith('pulse') and key[5:].isdigit():
                idx = key[5:]
                sensor_name = subnode_settings.get(f'p{idx}', f'{group_name} - p{idx}')
                if sensor_name != 'Unused':
                    columns[f'{group_name} / {sensor_name} - pulse'] = value
            elif key == 'supplyV':
                columns[f'{group_name} / supplyV'] = value

    elif device_type == 'rain':
        for key, value in fields.items():
            columns[f'{group_name} / {key}'] = value

    elif device_type == 'hws':
        for key, value in fields.items():
            sensor_name = subnode_settings.get(key, f'{group_name} - {key}')
            if sensor_name != 'Unused':
                columns[f'{group_name} / {sensor_name}'] = value

    elif device_type == 'bat':
        for key, value in fields.items():
            if key.startswith('s') and key[1:].isdigit():
                sensor_name = subnode_settings.get(key, f'{group_name} - {key}')
                if sensor_name != 'Unused':
                    columns[f'{group_name} / {sensor_name} - power'] = value
            elif key.endswith('In') and key[0] == 's':
                base_key = key[:-2]  # e.g., "s0"
                sensor_name = subnode_settings.get(base_key, f'{group_name} - {base_key}')
                if sensor_name != 'Unused':
                    columns[f'{group_name} / {sensor_name} - pulseIn'] = value
            elif key.endswith('Out') and key[0] == 's':
                base_key = key[:-3]  # e.g., "s0"
                sensor_name = subnode_settings.get(base_key, f'{group_name} - {base_key}')
                if sensor_name != 'Unused':
                    columns[f'{group_name} / {sensor_name} - pulseOut'] = value
            elif key.startswith('v') and key[1:].isdigit():
                sensor_name = subnode_settings.get(key, f'{group_name} - {key}')
                if sensor_name != 'Unused':
                    columns[f'{group_name} / {sensor_name}'] = value

    elif device_type == 'wtr':
        for key, value in fields.items():
            if key.startswith('f') and key[1:].isdigit():
                sensor_name = subnode_settings.get(key, f'{group_name} - {key}')
                if sensor_name != 'Unused':
                    columns[f'{group_name} / {sensor_name}'] = value
            elif key.startswith('h') and key[1:].isdigit():
                sensor_name = subnode_settings.get(key, f'{group_name} - {key}')
                if sensor_name != 'Unused':
                    columns[f'{group_name} / {sensor_name}'] = value
            elif key == 'supplyV':
                columns[f'{group_name} / supplyV'] = value

    elif device_type == 'scl':
        columns[f'{group_name} / grams'] = fields.get('grams')
        columns[f'{group_name} / supplyV'] = fields.get('supplyV')

    else:
        # Generic handler for: inv, bee, air, leaf, gps, pth, bms, svc, mwv, imu
        for key, value in fields.items():
            columns[f'{group_name} / {key}'] = value

    return columns


def build_all_sensor_names(settings):
    """Build a complete list of all sensor names and group names from settings.

    Returns:
        (sensor_names, group_names, group_to_sensors) where:
        - sensor_names: set of all individual sensor column names
        - group_names: set of all group names
        - group_to_sensors: dict mapping group_name -> set of sensor column names
    """
    sensor_names = set()
    group_names = set()
    group_to_sensors = {}

    for device_type, subnodes in settings.items():
        if not isinstance(subnodes, dict):
            continue
        for subnode, config in subnodes.items():
            if not isinstance(config, dict):
                continue
            group_name = config.get('name', f'{device_type}/{subnode}')
            if group_name == 'Unused':
                continue
            group_names.add(group_name)
            group_to_sensors.setdefault(group_name, set())

            # Generate the same column names that resolve_sensor_columns would produce
            if device_type == 'temp':
                for i in range(log_parser.MAX_TEMPERATURE_SENSORS):
                    key = f't{i}'
                    if key in config and config[key] != 'Unused':
                        col = f'{group_name} / {config[key]}'
                        sensor_names.add(col)
                        group_to_sensors[group_name].add(col)
                col = f'{group_name} / supplyV'
                sensor_names.add(col)
                group_to_sensors[group_name].add(col)

            elif device_type == 'disp':
                col = f'{group_name} / temperature'
                sensor_names.add(col)
                group_to_sensors[group_name].add(col)

            elif device_type == 'pulse':
                for i in range(log_parser.PULSE_MAX_SENSORS):
                    key = f'p{i}'
                    if key in config and config[key] != 'Unused':
                        sensor_name = config[key]
                        col_power = f'{group_name} / {sensor_name} - power'
                        col_pulse = f'{group_name} / {sensor_name} - pulse'
                        sensor_names.add(col_power)
                        sensor_names.add(col_pulse)
                        group_to_sensors[group_name].add(col_power)
                        group_to_sensors[group_name].add(col_pulse)
                col = f'{group_name} / supplyV'
                sensor_names.add(col)
                group_to_sensors[group_name].add(col)

            elif device_type == 'rain':
                for key in ('rainCount', 'transmitCount', 'temperature', 'supplyV'):
                    col = f'{group_name} / {key}'
                    sensor_names.add(col)
                    group_to_sensors[group_name].add(col)

            elif device_type == 'hws':
                for i in range(log_parser.HWS_TEMPERATURES):
                    key = f't{i}'
                    if key in config and config[key] != 'Unused':
                        col = f'{group_name} / {config[key]}'
                        sensor_names.add(col)
                        group_to_sensors[group_name].add(col)
                for i in range(log_parser.HWS_PUMPS):
                    key = f'p{i}'
                    if key in config and config[key] != 'Unused':
                        col = f'{group_name} / {config[key]}'
                        sensor_names.add(col)
                        group_to_sensors[group_name].add(col)

            elif device_type == 'bat':
                for i in range(log_parser.BATTERY_SHUNTS):
                    key = f's{i}'
                    if key in config and config[key] != 'Unused':
                        sn = config[key]
                        for suffix in (' - power', ' - pulseIn', ' - pulseOut'):
                            col = f'{group_name} / {sn}{suffix}'
                            sensor_names.add(col)
                            group_to_sensors[group_name].add(col)
                for i in range(log_parser.MAX_VOLTAGES):
                    key = f'v{i}'
                    if key in config and config[key] != 'Unused':
                        col = f'{group_name} / {config[key]}'
                        sensor_names.add(col)
                        group_to_sensors[group_name].add(col)

            elif device_type == 'wtr':
                for i in range(4):
                    for prefix in ('f', 'h'):
                        key = f'{prefix}{i}'
                        if key in config and config[key] != 'Unused':
                            col = f'{group_name} / {config[key]}'
                            sensor_names.add(col)
                            group_to_sensors[group_name].add(col)
                col = f'{group_name} / supplyV'
                sensor_names.add(col)
                group_to_sensors[group_name].add(col)

            elif device_type == 'scl':
                for key in ('grams', 'supplyV'):
                    col = f'{group_name} / {key}'
                    sensor_names.add(col)
                    group_to_sensors[group_name].add(col)

            else:
                # Generic: inv, bee, air, leaf, gps, pth, bms, svc, mwv, imu
                # We can't enumerate all field keys without parsing data,
                # so we just register the group
                pass

    return sensor_names, group_names, group_to_sensors


def list_sensors(settings):
    """Print all available sensors from settings in a structured listing."""
    for device_type, subnodes in sorted(settings.items()):
        if not isinstance(subnodes, dict):
            continue
        print(f"\nDevice: {device_type}")
        for subnode in sorted(subnodes.keys()):
            config = subnodes[subnode]
            if not isinstance(config, dict):
                continue
            group_name = config.get('name', f'{device_type}/{subnode}')
            print(f'  Subnode {subnode} - Group: "{group_name}"')
            for key, value in sorted(config.items()):
                if key == 'name' or not isinstance(value, str):
                    continue
                if value != 'Unused':
                    print(f'    {key}: "{value}"')


def load_sensor_filter(sensors_arg, config_path):
    """Load the set of sensor/group names to include from CLI args or config file.

    Args:
        sensors_arg: comma-separated string from --sensors, or None
        config_path: path to YAML config file from --config, or None

    Returns:
        set of sensor/group name strings, or None if no filter (export all)
    """
    names = set()

    if sensors_arg:
        for name in sensors_arg.split(','):
            name = name.strip()
            if name:
                names.add(name)

    if config_path:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        if config:
            if isinstance(config, dict):
                for key in ('sensors', 'groups'):
                    items = config.get(key, [])
                    if isinstance(items, list):
                        for name in items:
                            if isinstance(name, str) and name.strip():
                                names.add(name.strip())
            elif isinstance(config, list):
                # Simple list format
                for name in config:
                    if isinstance(name, str) and name.strip():
                        names.add(name.strip())

    return names if names else None


def expand_filter_to_columns(filter_names, settings):
    """Expand a set of sensor/group names to the full set of CSV column names to include.

    Args:
        filter_names: set of names from user (sensor names and/or group names)
        settings: full settings dict

    Returns:
        set of column name strings to include, or None if all columns should be included
    """
    if filter_names is None:
        return None

    _, group_names, group_to_sensors = build_all_sensor_names(settings)

    included_columns = set()
    for name in filter_names:
        if name in group_to_sensors:
            # It's a group name — include all sensors in this group
            included_columns.update(group_to_sensors[name])
        else:
            # It's an individual sensor name — include any column containing this name
            included_columns.add(name)

    return included_columns


def column_matches_filter(column_name, filter_columns):
    """Check if a CSV column name matches the filter.

    Args:
        column_name: full column name like "Mobile Box 1 / M1-1, Reference External"
        filter_columns: set of allowed column names, or None (allow all)

    Returns:
        True if column should be included
    """
    if filter_columns is None:
        return True

    # Exact match
    if column_name in filter_columns:
        return True

    # Check if any filter name appears as a substring (handles partial matches
    # for individual sensor names within "Group / Sensor - suffix" columns)
    for filter_col in filter_columns:
        if filter_col in column_name:
            return True

    return False


def discover_log_files(log_folder, start_date, end_date):
    """Find all YYYYMMDD.TXT log files in the folder that fall within the date range.

    Args:
        log_folder: path to directory containing log files
        start_date: start date (inclusive)
        end_date: end date (inclusive)

    Returns:
        sorted list of (full_path, file_date) tuples
    """
    files = []
    for filename in os.listdir(log_folder):
        if not filename.upper().endswith('.TXT'):
            continue
        # Try to parse date from filename
        base = filename[:-4]  # Remove .TXT
        try:
            file_date = datetime.datetime.strptime(base, "%Y%m%d").date()
        except ValueError:
            continue

        if start_date <= file_date <= end_date:
            files.append((os.path.join(log_folder, filename), file_date))

    files.sort(key=lambda x: x[1])
    return files


def process_log_files(log_files, start_dt, end_dt, timezone, settings_manager, filter_columns):
    """Process log files and collect sensor data.

    Args:
        log_files: list of (file_path, file_date) tuples
        start_dt: start datetime (naive, local time)
        end_dt: end datetime (naive, local time)
        timezone: pytz timezone object
        settings_manager: EmonSettings instance
        filter_columns: set of column names to include, or None for all

    Returns:
        (data, all_columns) where:
        - data: dict of {timestamp_str: {column_name: value}}
        - all_columns: sorted list of all column names seen
    """
    data = {}
    all_columns = set()
    seen_keys = set()  # For deduplication: (timestamp_str, device_type, subnode)
    total_lines = 0
    skipped_relay = 0
    skipped_range = 0
    parse_errors = 0
    missing_settings_warned = set()

    for file_path, file_date in log_files:
        print(f"Processing {os.path.basename(file_path)}...", file=sys.stderr)
        try:
            with open(file_path, 'r', errors='replace') as f:
                for line_num, raw_line in enumerate(f, 1):
                    total_lines += 1
                    parsed = log_parser.parse_line(raw_line)
                    if parsed is None:
                        parse_errors += 1
                        continue

                    # Check time range
                    if parsed.timestamp < start_dt or parsed.timestamp > end_dt:
                        skipped_range += 1
                        continue

                    # Deduplication: skip relay duplicates
                    dedup_key = (
                        parsed.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        parsed.device_type,
                        parsed.subnode,
                    )
                    if dedup_key in seen_keys:
                        if parsed.has_relay:
                            skipped_relay += 1
                            continue
                    seen_keys.add(dedup_key)

                    # Get settings for this timestamp
                    local_dt = timezone.localize(parsed.timestamp)
                    settings_manager.check_and_reload_settings_by_time(local_dt)
                    settings = settings_manager.get_settings()

                    # Check if device type exists in settings
                    if parsed.device_type not in settings:
                        key = (parsed.device_type, parsed.subnode)
                        if key not in missing_settings_warned:
                            missing_settings_warned.add(key)
                            print(f"Warning: no settings for {parsed.device_type}/{parsed.subnode}, skipping",
                                  file=sys.stderr)
                        continue

                    # Resolve sensor columns
                    try:
                        columns = resolve_sensor_columns(
                            parsed.device_type, parsed.subnode,
                            parsed.fields, settings
                        )
                    except Exception as ex:
                        print(f"Warning: {file_path}:{line_num} resolve error: {ex}",
                              file=sys.stderr)
                        continue

                    # Filter columns
                    ts_key = parsed.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    for col_name, value in columns.items():
                        if value is None:
                            continue
                        if not column_matches_filter(col_name, filter_columns):
                            continue
                        all_columns.add(col_name)
                        if ts_key not in data:
                            data[ts_key] = {}
                        data[ts_key][col_name] = value

        except Exception as ex:
            print(f"Error reading {file_path}: {ex}", file=sys.stderr)

    print(f"\nProcessed {total_lines} lines from {len(log_files)} files", file=sys.stderr)
    print(f"  Relay duplicates skipped: {skipped_relay}", file=sys.stderr)
    print(f"  Out of range skipped: {skipped_range}", file=sys.stderr)
    print(f"  Parse errors: {parse_errors}", file=sys.stderr)
    print(f"  Unique timestamps: {len(data)}", file=sys.stderr)
    print(f"  Sensor columns: {len(all_columns)}", file=sys.stderr)

    return data, sorted(all_columns)


def write_csv(data, columns, output_path):
    """Write collected data to a wide-format CSV file.

    Args:
        data: dict of {timestamp_str: {column_name: value}}
        columns: sorted list of column names
        output_path: path to output CSV file
    """
    sorted_timestamps = sorted(data.keys())

    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Timestamp'] + columns)

        for ts in sorted_timestamps:
            row = [ts]
            row_data = data[ts]
            for col in columns:
                value = row_data.get(col, '')
                row.append(value)
            writer.writerow(row)

    print(f"\nWrote {len(sorted_timestamps)} rows x {len(columns)} columns to {output_path}",
          file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description='Export emon log file data to CSV',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Export all sensors for a time range:
    python export_csv.py --start "2026-03-24 00:00:00" --end "2026-03-24 23:59:59" \\
        --log-folder /path/to/logs --settings-folder /path/to/settings

  Export specific sensors:
    python export_csv.py --start "2026-03-24 00:00:00" --end "2026-03-24 23:59:59" \\
        --log-folder /path/to/logs --settings-folder /path/to/settings \\
        --sensors "Office room 4,Mobile Box 1"

  Export sensors from config file:
    python export_csv.py --start "2026-03-24 00:00:00" --end "2026-03-24 23:59:59" \\
        --log-folder /path/to/logs --settings-folder /path/to/settings \\
        --config export_config.yml

  List available sensors:
    python export_csv.py --list-sensors --settings-folder /path/to/settings
        """
    )
    parser.add_argument('--start', help='Start datetime (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end', help='End datetime (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--log-folder', help='Directory containing YYYYMMDD.TXT log files')
    parser.add_argument('--settings-folder', help='Directory containing YAML settings files')
    parser.add_argument('--sensors', help='Comma-separated sensor names or group names to export')
    parser.add_argument('--config', help='YAML config file listing sensors/groups to export')
    parser.add_argument('--output', '-o', help='Output CSV file path')
    parser.add_argument('--timezone', default='Australia/Perth',
                        help='Timezone for log timestamps (default: Australia/Perth)')
    parser.add_argument('--list-sensors', action='store_true',
                        help='List all available sensors from settings and exit')

    args = parser.parse_args()

    # Handle --list-sensors mode
    if args.list_sensors:
        if not args.settings_folder:
            parser.error('--settings-folder is required with --list-sensors')
        settings_manager = EmonSettings(args.settings_folder)
        list_sensors(settings_manager.get_settings())
        return

    # Validate required args for export mode
    if not args.start or not args.end:
        parser.error('--start and --end are required for export')
    if not args.log_folder:
        parser.error('--log-folder is required for export')
    if not args.settings_folder:
        parser.error('--settings-folder is required for export')

    # Parse datetimes
    try:
        start_dt = datetime.datetime.strptime(args.start, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        parser.error(f'Invalid start datetime format: {args.start} (expected YYYY-MM-DD HH:MM:SS)')
    try:
        end_dt = datetime.datetime.strptime(args.end, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        parser.error(f'Invalid end datetime format: {args.end} (expected YYYY-MM-DD HH:MM:SS)')

    # Parse timezone
    try:
        tz = pytz.timezone(args.timezone)
    except pytz.exceptions.UnknownTimeZoneError:
        parser.error(f'Unknown timezone: {args.timezone}')

    # Discover log files
    start_date = start_dt.date()
    end_date = end_dt.date()
    log_files = discover_log_files(args.log_folder, start_date, end_date)
    if not log_files:
        print(f"No log files found in {args.log_folder} for date range {start_date} to {end_date}",
              file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(log_files)} log file(s) for date range", file=sys.stderr)

    # Load settings
    settings_manager = EmonSettings(args.settings_folder)

    # Load sensor filter
    filter_names = load_sensor_filter(args.sensors, args.config)
    filter_columns = expand_filter_to_columns(filter_names, settings_manager.get_settings())

    if filter_names:
        print(f"Filtering to sensors/groups: {', '.join(sorted(filter_names))}", file=sys.stderr)

    # Process log files
    data, columns = process_log_files(
        log_files, start_dt, end_dt, tz, settings_manager, filter_columns
    )

    if not data:
        print("No data found matching the criteria", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    output_path = args.output
    if not output_path:
        start_str = start_dt.strftime('%Y%m%d_%H%M%S')
        end_str = end_dt.strftime('%Y%m%d_%H%M%S')
        output_path = f'export_{start_str}_{end_str}.csv'

    # Write CSV
    write_csv(data, columns, output_path)


if __name__ == '__main__':
    main()
