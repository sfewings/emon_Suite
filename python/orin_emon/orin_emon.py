#!/usr/bin/env python3
"""
NVIDIA Orin Temperature & Power Monitor
Reads thermal zones and INA power rails from sysfs / tegrastats.
Works on JetPack/L4T without any third-party dependencies.
Orin EmonCMS Serial Transmitter

Reads Orin thermal zones and INA3221 power rails at a configurable interval,
packages them into EmonShared text packet format (temp1 and bat2), and
transmits over a serial port. Also logs each packet to a daily CSV file.

Packet formats (from EmonShared.cpp):
  temp1,subnode,supplyV,numSensors,temperature[0..numSensors]
  bat2,subnode,power[0..2],pulseIn[0..2],pulseOut[0..2],voltage[0..8]

Claude instructions:
orin_monitor.py queries details from Orin and displays them in a table. I want to design a python script that takes these values and does the following;
1. queries the temperatures and power consumptions on a 1 second interval and packages them into a text packet format as defined in the file emon_share.h and emon_shared.cpp in the emonShared folder. 
2. Temperatures fill a temp packet as defined "temp1,subnode,supplyV,numSensors,temperature[0..numSensors]" where temp1 is the packet signature, subnode is configurable, supplyV is VDD_CPU_CV, num sensors is 5 and each temperature is in 100th of celcius
3. The temperature sensors are cpu_thermal, soc0-thermal, soc1-thermal, soc2-thermal,tj-thermal
4. The power is encoded in two battery packets as defined "bat3,subnode,power[0..2],pulseIn[0..2],pulseOut[0..2],voltage[0..8]" where bat3 is the packet signature, subnode will be 0 and 1, power[0..2] is in mW, (for subnode 0) VDD_GPU_SOC, VDD_CPU_CV, VIN_SYS_5V, (for subnode 1) VDDQ_VDD2_1V8A0, ina3221_ch4. voltage is the voltage of each respective power reading. pulseIn and pulseOut are unused and set to 0.
5. The text packet is trnasmitted on a serial connection (configurable port) at 9600 baud
6. Each text packet is also stored to a CSV log file with the file name set to YYYMMDD.TXT. An example log text file is provided
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

# ─── Configuration defaults ──────────────────────────────────────────────────

DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD_RATE = 9600
DEFAULT_TEMP_SUBNODE = 6
DEFAULT_LOG_DIR = "/home/nvidia/StephenFewings/logs"
DEFAULT_INTERVAL = 5

# Temperature sensors to read (in order)
TEMP_SENSORS = [
    "cpu-thermal",
    "soc0-thermal",
    "soc1-thermal",
    "tj-thermal",
]

# Power rails for battery subnode 0: VDD_GPU_SOC, VDD_CPU_CV, VIN_SYS_5V0
# Power rails for battery subnode 1: VDDQ_VDD2_1V8AO, ina3221_ch4
# Mapped as (hwmon_name, channel_index) tuples
POWER_SUBNODE_0 = [
    ("VDD_GPU_SOC", None),
    ("VDD_CPU_CV", None),
    ("VIN_SYS_5V0", None),
]

POWER_SUBNODE_1 = [
    ("VDDQ_VDD2_1V8AO", None),
    ("ina3221_ch4", None),
]

BATTERY_SHUNTS = 3
MAX_VOLTAGES = 9


# ─── Sensor reading helpers ─────────────────────────────────────────────────

def _read_sysfs_int(path):
    """Read an integer from a sysfs file, return None on failure."""
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _find_thermal_zone(sensor_name):
    """Find the sysfs path for a thermal zone by its type name."""
    base = "/sys/class/thermal"
    if not os.path.isdir(base):
        return None
    for entry in os.listdir(base):
        if not entry.startswith("thermal_zone"):
            continue
        type_file = os.path.join(base, entry, "type")
        try:
            with open(type_file) as f:
                if f.read().strip() == sensor_name:
                    return os.path.join(base, entry, "temp")
        except OSError:
            continue
    return None


def _build_thermal_paths():
    """Build a list of sysfs temp file paths for TEMP_SENSORS."""
    paths = []
    for name in TEMP_SENSORS:
        path = _find_thermal_zone(name)
        paths.append(path)
    return paths


def _build_power_map():
    """
    Scan hwmon ina3221 devices and build a lookup from rail label to
    (voltage_file, current_file) paths.
    """
    rail_map = {}
    hwmon_base = "/sys/class/hwmon"
    if not os.path.isdir(hwmon_base):
        return rail_map

    for hwmon in sorted(os.listdir(hwmon_base)):
        hwmon_path = os.path.join(hwmon_base, hwmon)
        name_file = os.path.join(hwmon_path, "name")
        try:
            with open(name_file) as f:
                sensor_name = f.read().strip()
        except OSError:
            continue

        if sensor_name != "ina3221":
            continue

        idx = 1
        while True:
            voltage_file = os.path.join(hwmon_path, f"in{idx}_input")
            current_file = os.path.join(hwmon_path, f"curr{idx}_input")
            label_file = os.path.join(hwmon_path, f"in{idx}_label")

            if not os.path.exists(voltage_file) and not os.path.exists(current_file):
                break

            label = None
            if os.path.exists(label_file):
                try:
                    with open(label_file) as f:
                        label = f.read().strip()
                except OSError:
                    pass

            # Store by label and also by generic "ina3221_ch{idx}" for unlabelled
            key_generic = f"ina3221_ch{idx}"
            entry = (
                voltage_file if os.path.exists(voltage_file) else None,
                current_file if os.path.exists(current_file) else None,
            )
            if label:
                rail_map[label] = entry
            rail_map[key_generic] = entry

            idx += 1

    return rail_map


def read_temperatures(thermal_paths):
    """
    Read temperatures from sysfs. Returns list of temperatures in
    hundredths of degrees Celsius (int). Missing sensors return 0.
    """
    temps = []
    for path in thermal_paths:
        if path is None:
            temps.append(0)
            continue
        raw = _read_sysfs_int(path)  # millidegrees C
        if raw is not None:
            temps.append(raw // 10)  # convert milli-C to hundredths-C
        else:
            temps.append(0)
    return temps


def read_supply_voltage(rail_map):
    """Read VDD_CPU_CV voltage in mV for the temperature packet supplyV field."""
    entry = rail_map.get("VDD_CPU_CV")
    if entry and entry[0]:
        v = _read_sysfs_int(entry[0])
        return v if v is not None else 0
    return 0


def read_power_rail(rail_map, rail_name):
    """Read power (mW) and voltage (mV) for a named rail. Returns (power_mw, voltage_mv)."""
    entry = rail_map.get(rail_name)
    if entry is None:
        return (0, 0)

    voltage_file, current_file = entry
    voltage_mv = _read_sysfs_int(voltage_file) if voltage_file else None
    current_ma = _read_sysfs_int(current_file) if current_file else None

    power_mw = 0
    v_mv = 0
    if voltage_mv is not None:
        v_mv = voltage_mv
    if voltage_mv is not None and current_ma is not None:
        power_mw = int(voltage_mv * current_ma / 1000)
    elif current_ma is not None:
        # No voltage available, report current as-is (approximate)
        power_mw = 0

    return (power_mw, v_mv)


# ─── Packet formatting ──────────────────────────────────────────────────────

def format_temp_packet(subnode, supply_v, temperatures):
    """
    Format: temp1,subnode,supplyV,numSensors,t0,t1,...
    temperatures: list of int in hundredths of degrees C
    """
    num_sensors = len(temperatures)
    parts = ["temp1", str(subnode), str(supply_v), str(num_sensors)]
    parts.extend(str(t) for t in temperatures)
    return ",".join(parts)


def format_battery_packet(subnode, powers, voltages):
    """
    Format: bat2,subnode,power[0..2],pulseIn[0..2],pulseOut[0..2],voltage[0..8]
    powers: list of 3 power values in mW (int)
    voltages: list of up to 9 voltage values in mV (int)
    """
    parts = ["bat2", str(subnode)]

    # Power values (3)
    for i in range(BATTERY_SHUNTS):
        parts.append(str(powers[i] if i < len(powers) else 0))

    # pulseIn values (3) - unused, set to 0
    for _ in range(BATTERY_SHUNTS):
        parts.append("0")

    # pulseOut values (3) - unused, set to 0
    for _ in range(BATTERY_SHUNTS):
        parts.append("0")

    # Voltage values (up to 9)
    for i in range(MAX_VOLTAGES):
        parts.append(str(voltages[i]/10 if i < len(voltages) else 0))  #Convert mV to 100ths of V for transmit

    return ",".join(parts)


# ─── Serial output ───────────────────────────────────────────────────────────

def open_serial(port, baud):
    """Open a serial port. Returns the serial object or None."""
    try:
        import serial
        ser = serial.Serial(port, baud, timeout=1)
        return ser
    except ImportError:
        print("WARNING: pyserial not installed. Install with: pip install pyserial")
        print("         Serial output disabled.")
        return None
    except Exception as e:
        print(f"WARNING: Cannot open serial port {port}: {e}")
        print("         Serial output disabled.")
        return None


def is_serial_connected(ser):
    """Check if a serial connection is still valid."""
    if ser is None:
        return False
    try:
        # Try to get the connection status
        return ser.is_open
    except Exception:
        return False


def close_serial(ser):
    """Safely close a serial connection."""
    if ser is not None:
        try:
            ser.close()
        except Exception:
            pass


def send_packet(ser, packet_str):
    """
    Send a text packet over the serial port.
    Returns True if successful, False if failed or no connection.
    """
    if ser is None or not is_serial_connected(ser):
        return False
    
    try:
        ser.write((packet_str + "\n").encode("ascii"))
        return True
    except Exception as e:
        print(f"Serial write error: {e}")
        return False


# ─── CSV logging ─────────────────────────────────────────────────────────────

def get_log_filepath(log_dir):
    """Return the log file path for today: YYYYMMDD.TXT"""
    os.makedirs(log_dir, exist_ok=True)
    filename = datetime.now().strftime("%Y%m%d") + ".TXT"
    return os.path.join(log_dir, filename)


def log_packet(log_dir, packet_str):
    """Append a timestamped packet line to today's log file."""
    filepath = get_log_filepath(log_dir)
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    with open(filepath, "a") as f:
        f.write(f"{timestamp},{packet_str}\n")


# ─── Main loop ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Orin sensor to EmonShared serial transmitter"
    )
    parser.add_argument(
        "--port", "-p", type=str, default=DEFAULT_SERIAL_PORT,
        help=f"Serial port (default: {DEFAULT_SERIAL_PORT})",
    )
    parser.add_argument(
        "--baud", "-b", type=int, default=DEFAULT_BAUD_RATE,
        help=f"Baud rate (default: {DEFAULT_BAUD_RATE})",
    )
    parser.add_argument(
        "--temp-subnode", type=int, default=DEFAULT_TEMP_SUBNODE,
        help=f"Temperature packet subnode (default: {DEFAULT_TEMP_SUBNODE})",
    )
    parser.add_argument(
        "--log-dir", type=str, default=DEFAULT_LOG_DIR,
        help=f"Directory for CSV log files (default: {DEFAULT_LOG_DIR})",
    )
    parser.add_argument(
        "--interval", "-i", type=int, default=DEFAULT_INTERVAL,
        help=f"Query/transmit interval in seconds (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--no-serial", action="store_true",
        help="Disable serial output (log only)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print packets to stdout",
    )
    args = parser.parse_args()

    # Build sensor paths once at startup
    print("Initialising sensors...")
    thermal_paths = _build_thermal_paths()
    rail_map = _build_power_map()

    found_temps = sum(1 for p in thermal_paths if p is not None)
    print(f"  Temperature sensors: {found_temps}/{len(TEMP_SENSORS)}")
    for i, name in enumerate(TEMP_SENSORS):
        status = "OK" if thermal_paths[i] else "NOT FOUND"
        print(f"    {name}: {status}")

    found_rails = []
    for rails in [POWER_SUBNODE_0, POWER_SUBNODE_1]:
        for name, _ in rails:
            found = name in rail_map
            found_rails.append(found)
            print(f"    {name}: {'OK' if found else 'NOT FOUND'}")
    print(f"  Power rails: {sum(found_rails)}/{len(found_rails)}")

    # Open serial port
    ser = None
    serial_enabled = not args.no_serial
    last_reconnect_attempt = 0
    reconnect_interval = 5  # Retry every 5 seconds
    
    if serial_enabled:
        ser = open_serial(args.port, args.baud)
        if ser:
            print(f"  Serial: {args.port} @ {args.baud} baud")
        else:
            print(f"  Serial: Failed to open {args.port} - will retry if device appears")

    print(f"  Log dir: {args.log_dir}")
    print("Running... (Ctrl+C to stop)\n")

    # Handle graceful shutdown
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while running:
        try:
            # Attempt to reconnect serial if disabled and enough time has passed
            if serial_enabled and not is_serial_connected(ser):
                current_time = time.time()
                if current_time - last_reconnect_attempt >= reconnect_interval:
                    close_serial(ser)
                    ser = open_serial(args.port, args.baud)
                    last_reconnect_attempt = current_time
                    if ser:
                        print(f"Serial reconnected: {args.port}")
                    elif args.verbose:
                        print(f"Serial reconnect attempt failed for {args.port}")
            
            # ── Temperature packet ──
            temperatures = read_temperatures(thermal_paths)
            supply_v = read_supply_voltage(rail_map)
            temp_pkt = format_temp_packet(args.temp_subnode, supply_v, temperatures)

            if send_packet(ser, temp_pkt):
                if args.verbose:
                    print(f"[SERIAL] {temp_pkt}")
            elif args.verbose and serial_enabled:
                print(f"[LOG ONLY] {temp_pkt}")
            
            log_packet(args.log_dir, temp_pkt)

            # ── Battery packet subnode 0: VDD_GPU_SOC, VDD_CPU_CV, VIN_SYS_5V0 ──
            powers_0 = []
            voltages_0 = []
            for rail_name, _ in POWER_SUBNODE_0:
                p, v = read_power_rail(rail_map, rail_name)
                powers_0.append(p)
                voltages_0.append(v)

            bat0_pkt = format_battery_packet(0, powers_0, voltages_0)

            if send_packet(ser, bat0_pkt):
                if args.verbose:
                    print(f"[SERIAL] {bat0_pkt}")
            elif args.verbose and serial_enabled:
                print(f"[LOG ONLY] {bat0_pkt}")
            
            log_packet(args.log_dir, bat0_pkt)

            # ── Battery packet subnode 1: VDDQ_VDD2_1V8AO, ina3221_ch4 ──
            powers_1 = []
            voltages_1 = []
            for rail_name, _ in POWER_SUBNODE_1:
                p, v = read_power_rail(rail_map, rail_name)
                powers_1.append(p)
                voltages_1.append(v)

            bat1_pkt = format_battery_packet(1, powers_1, voltages_1)

            if send_packet(ser, bat1_pkt):
                if args.verbose:
                    print(f"[SERIAL] {bat1_pkt}")
            elif args.verbose and serial_enabled:
                print(f"[LOG ONLY] {bat1_pkt}")
            
            log_packet(args.log_dir, bat1_pkt)

            time.sleep(args.interval)

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(args.interval)

    # Cleanup
    print("\nShutting down...")
    close_serial(ser)
    print("Done.")


if __name__ == "__main__":
    main()
