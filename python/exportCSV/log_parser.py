"""
Pure Python parser for emon log file lines.

Parses YYYYMMDD.TXT log files produced by the emon system. Each line has the format:
    DD/MM/YYYY HH:MM:SS,<device_tag>,<payload_fields...>[|relay_bits][:rssi]

No dependency on the compiled emonSuite C++ bindings — parses the text format directly.
Field orders match the Print*Payload functions in EmonShared/EmonShared.cpp.
"""

import re
import datetime
from dataclasses import dataclass, field
from typing import Optional


# Constants matching EmonShared.h
PULSE_MAX_SENSORS = 6
MAX_TEMPERATURE_SENSORS = 4
HWS_TEMPERATURES = 7
HWS_PUMPS = 3
BATTERY_SHUNTS = 3
MAX_VOLTAGES = 9
MAX_BMS_CELLS = 16


@dataclass
class ParsedLine:
    timestamp: datetime.datetime
    device_type: str        # "temp", "pulse", "bat", etc.
    device_tag: str         # "temp1", "pulse3", "bat2", etc.
    subnode: int
    fields: dict            # {field_key: converted_value}
    has_relay: bool = False
    rssi: Optional[int] = None


def _strip_rssi_and_relay(payload_str):
    """Strip RSSI and relay bits from the end of a payload string.

    Returns (cleaned_payload, has_relay, rssi).
    Examples:
        "1,2,3:-78"           -> ("1,2,3", False, -78)
        "1,2,3|00000100:-73"  -> ("1,2,3", True, -73)
        "1,2,3"               -> ("1,2,3", False, None)
    """
    has_relay = False
    rssi = None

    # Extract RSSI from end (:<negative_number>)
    rssi_match = re.search(r':(-?\d+)\s*$', payload_str)
    if rssi_match:
        rssi = int(rssi_match.group(1))
        payload_str = payload_str[:rssi_match.start()]

    # Extract relay bits from end of last field (|XXXXXXXX where X is 0 or 1)
    relay_match = re.search(r'\|([01]{8})\s*$', payload_str)
    if relay_match:
        has_relay = True
        payload_str = payload_str[:relay_match.start()]

    return payload_str, has_relay, rssi


def _parse_timestamp(date_str):
    """Parse timestamp from log line. Handles 24h and AM/PM formats."""
    date_str = date_str.strip()
    if " AM" in date_str or " PM" in date_str:
        return datetime.datetime.strptime(date_str, "%d/%m/%Y %I:%M:%S %p")
    else:
        return datetime.datetime.strptime(date_str, "%d/%m/%Y %H:%M:%S")


def parse_line(raw_line):
    """Parse a single log line into a ParsedLine.

    Args:
        raw_line: Raw line from log file, e.g.:
            "24/03/2026 00:00:00,temp1,4,2790,4,2656,4987,4368,4137|00000100:-73"

    Returns:
        ParsedLine on success, None on parse failure.
    """
    raw_line = raw_line.strip()
    if not raw_line or len(raw_line) < 20:
        return None

    try:
        # Handle legacy format: colon separator after datetime (pre-20190624 files)
        colon_pos = raw_line[19:].find(":")
        if colon_pos != -1:
            # Check if this colon is part of the device separator (not RSSI at end)
            abs_pos = colon_pos + 19
            # Only replace if it's the first separator after datetime
            if raw_line[19] == ':':
                raw_line = raw_line[:abs_pos] + ',' + raw_line[abs_pos + 1:]

        # Handle space instead of comma at position 19 (20211231-20220116 files)
        if len(raw_line) > 19 and raw_line[19] == ' ':
            raw_line = raw_line[:19] + ',' + raw_line[20:]

        # Split into date and payload
        parts = raw_line.split(',', 2)
        if len(parts) < 3:
            return None

        date_str = parts[0]
        device_and_rest = parts[1] + ',' + parts[2]

        # Strip RSSI and relay from payload
        device_and_rest, has_relay, rssi = _strip_rssi_and_relay(device_and_rest)

        # Split into device tag and values
        values = device_and_rest.split(',')
        if len(values) < 1:
            return None

        device_tag = values[0].strip()
        payload_values = values[1:]

        # Extract device type by stripping trailing digits
        device_type = device_tag.rstrip('0123456789')

        # Skip header lines (e.g., "rain,rain,txCount,...")
        if len(payload_values) > 0 and not _is_numeric(payload_values[0]):
            # Check if second value is also non-numeric (header line)
            if device_type == 'rain' and len(payload_values) > 0:
                try:
                    int(payload_values[0])
                except ValueError:
                    return None

        timestamp = _parse_timestamp(date_str)

        # Dispatch to device-specific parser
        parser = _DEVICE_PARSERS.get(device_type)
        if parser is None:
            return None

        result = parser(device_tag, payload_values)
        if result is None:
            return None

        subnode, fields = result

        return ParsedLine(
            timestamp=timestamp,
            device_type=device_type,
            device_tag=device_tag,
            subnode=subnode,
            fields=fields,
            has_relay=has_relay,
            rssi=rssi,
        )

    except Exception:
        return None


def _is_numeric(s):
    """Check if a string represents a number (int or float, possibly negative)."""
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# --- Per-device parsers ---
# Each returns (subnode, fields_dict) or None on failure.
# Field keys match the settings YAML keys for sensor name resolution.

def _parse_temp(device_tag, values):
    """temp1,subnode,supplyV,numSensors,t0[,t1[,t2[,t3]]]"""
    if len(values) < 4:
        return None
    subnode = int(values[0])
    supply_v = int(values[1]) / 1000.0
    num_sensors = int(values[2])
    num_sensors = min(num_sensors, MAX_TEMPERATURE_SENSORS)

    fields = {'supplyV': supply_v}
    for i in range(num_sensors):
        if i + 3 < len(values):
            fields[f't{i}'] = int(values[i + 3]) / 100.0

    return subnode, fields


def _parse_disp(device_tag, values):
    """disp1,subnode,temperature"""
    if len(values) < 2:
        return None
    subnode = int(values[0])
    temperature = int(values[1]) / 100.0

    return subnode, {'temperature': temperature}


def _parse_pulse(device_tag, values):
    """pulse3,subnode,power[0..5],pulse[0..5],supplyV"""
    if device_tag in ('pulse3',):
        if len(values) < 1 + PULSE_MAX_SENSORS * 2 + 1:
            return None
        subnode = int(values[0])
        fields = {}
        for i in range(PULSE_MAX_SENSORS):
            fields[f'p{i}'] = int(values[1 + i])
        for i in range(PULSE_MAX_SENSORS):
            fields[f'pulse{i}'] = int(values[1 + PULSE_MAX_SENSORS + i])
        fields['supplyV'] = int(values[1 + PULSE_MAX_SENSORS * 2])
        return subnode, fields
    else:
        # Legacy pulse/pulse2: pulse2,power[0..3],pulse[0..3],supplyV (no subnode)
        n_sensors = 4
        if len(values) < n_sensors * 2 + 1:
            return None
        subnode = 0
        fields = {}
        for i in range(n_sensors):
            fields[f'p{i}'] = int(values[i])
        for i in range(n_sensors):
            fields[f'pulse{i}'] = int(values[n_sensors + i])
        fields['supplyV'] = int(values[n_sensors * 2])
        return subnode, fields


def _parse_rain(device_tag, values):
    """rain,rainCount,transmitCount,temperature,supplyV (no subnode)"""
    if len(values) < 4:
        return None
    # Skip header lines where values aren't numeric
    try:
        rain_count = int(values[0])
    except ValueError:
        return None

    fields = {
        'rainCount': rain_count,
        'transmitCount': int(values[1]),
        'temperature': int(values[2]) / 100.0,
        'supplyV': int(values[3]) / 1000.0,
    }
    return 0, fields


def _parse_hws(device_tag, values):
    """hws,t0..t6,p0..p2 (no subnode)"""
    if len(values) < HWS_TEMPERATURES + HWS_PUMPS:
        return None
    fields = {}
    for i in range(HWS_TEMPERATURES):
        fields[f't{i}'] = int(values[i])
    for i in range(HWS_PUMPS):
        fields[f'p{i}'] = int(values[HWS_TEMPERATURES + i])
    return 0, fields


def _parse_bat(device_tag, values):
    """bat2,subnode,power[0..2],pulseIn[0..2],pulseOut[0..2],voltage[0..8]"""
    if len(values) < 1 + BATTERY_SHUNTS * 3 + MAX_VOLTAGES:
        return None
    subnode = int(values[0])
    idx = 1
    fields = {}
    for i in range(BATTERY_SHUNTS):
        fields[f's{i}'] = int(values[idx + i])
    idx += BATTERY_SHUNTS
    for i in range(BATTERY_SHUNTS):
        fields[f's{i}In'] = int(values[idx + i])
    idx += BATTERY_SHUNTS
    for i in range(BATTERY_SHUNTS):
        fields[f's{i}Out'] = int(values[idx + i])
    idx += BATTERY_SHUNTS
    for i in range(MAX_VOLTAGES):
        fields[f'v{i}'] = int(values[idx + i]) / 100.0
    return subnode, fields


def _parse_wtr(device_tag, values):
    """wtr3,subnode,supplyV,numSensors,flowCount[0..n],waterHeight[0..m]"""
    if len(values) < 3:
        return None
    subnode = int(values[0])
    supply_v = int(values[1]) / 1000.0
    num_sensors_byte = int(values[2])
    num_flow = num_sensors_byte & 0x0F
    num_height = (num_sensors_byte & 0xF0) >> 4

    fields = {'supplyV': supply_v}
    idx = 3
    for i in range(num_flow):
        if idx + i < len(values):
            fields[f'f{i}'] = int(values[idx + i])
    idx += num_flow
    for i in range(num_height):
        if idx + i < len(values):
            fields[f'h{i}'] = int(values[idx + i])
    return subnode, fields


def _parse_scl(device_tag, values):
    """scl,subnode,grams,supplyV"""
    if len(values) < 3:
        return None
    subnode = int(values[0])
    fields = {
        'grams': int(values[1]),
        'supplyV': int(values[2]) / 1000.0,
    }
    return subnode, fields


def _parse_inv(device_tag, values):
    """inv3,subnode,activePower,apparentPower,batteryVoltage,batteryDischarge,
       batteryCharging,pvInputPower,batteryCapacity,totalWh"""
    if len(values) < 9:
        return None
    subnode = int(values[0])
    fields = {
        'activePower': int(values[1]),
        'apparentPower': int(values[2]),
        'batteryVoltage': int(values[3]) / 10.0,
        'batteryDischarge': int(values[4]),
        'batteryCharging': int(values[5]),
        'pvInputPower': int(values[6]),
        'batteryCapacity': int(values[7]),
        'totalWh': int(values[8]),
    }
    return subnode, fields


def _parse_bee(device_tag, values):
    """bee,subnode,beeInRate,beeOutRate,beesIn,beesOut,tempIn,tempOut,grams,supplyV"""
    if len(values) < 9:
        return None
    subnode = int(values[0])
    fields = {
        'beeInRate': int(values[1]),
        'beeOutRate': int(values[2]),
        'beesIn': int(values[3]),
        'beesOut': int(values[4]),
        'temperatureIn': int(values[5]) / 100.0,
        'temperatureOut': int(values[6]) / 100.0,
        'grams': int(values[7]),
        'supplyV': int(values[8]) / 1000.0,
    }
    return subnode, fields


def _parse_air(device_tag, values):
    """air,subnode,pm0p3,pm0p5,pm1p0,pm2p5,pm5p0,pm10p0"""
    if len(values) < 7:
        return None
    subnode = int(values[0])
    fields = {
        'pm0p3': int(values[1]),
        'pm0p5': int(values[2]),
        'pm1p0': int(values[3]),
        'pm2p5': int(values[4]),
        'pm5p0': int(values[5]),
        'pm10p0': int(values[6]),
    }
    return subnode, fields


def _parse_leaf(device_tag, values):
    """leaf2,subnode,odometer,range,batteryTemp,batterySOH,batteryWH,batteryChargeBars,chargeTimeRemaining"""
    if len(values) < 7:
        return None
    subnode = int(values[0])
    fields = {
        'odometer': int(values[1]),
        'range': int(values[2]),
        'batteryTemperature': int(values[3]),
        'batterySOH': int(values[4]),
        'batteryWH': int(values[5]),
        'batteryChargeBars': int(values[6]),
    }
    # leaf2 has chargeTimeRemaining
    if len(values) >= 8:
        fields['chargeTimeRemaining'] = int(values[7])
    return subnode, fields


def _parse_gps(device_tag, values):
    """gps,subnode,latitude,longitude,course,speed"""
    if len(values) < 5:
        return None
    subnode = int(values[0])
    fields = {
        'latitude': float(values[1]),
        'longitude': float(values[2]),
        'course': float(values[3]),
        'speed': float(values[4]),
    }
    return subnode, fields


def _parse_pth(device_tag, values):
    """pth,subnode,pressure,temperature,humidity"""
    if len(values) < 4:
        return None
    subnode = int(values[0])
    fields = {
        'pressure': float(values[1]),
        'temperature': float(values[2]),
        'humidity': float(values[3]),
    }
    return subnode, fields


def _parse_bms(device_tag, values):
    """bms,subnode,batteryVoltage,batterySoC,current,resCapacity,temperature,
       lifetimeCycles,cell0..cell15
    Note: values are already converted in the C++ Print function (÷10, ÷1000 applied)."""
    if len(values) < 7:
        return None
    subnode = int(values[0])
    fields = {
        'batteryVoltage': float(values[1]),
        'batterySoC': float(values[2]),
        'current': float(values[3]),
        'resCapacity': float(values[4]),
        'temperature': float(values[5]),
        'lifetimeCycles': int(values[6]),
    }
    for i in range(MAX_BMS_CELLS):
        if 7 + i < len(values):
            fields[f'cell{i}'] = float(values[7 + i])
    return subnode, fields


def _parse_svc(device_tag, values):
    """svc,subnode,motorTemperature,controllerTemperature,capVoltage,batteryCurrent,rpm"""
    if len(values) < 6:
        return None
    subnode = int(values[0])
    fields = {
        'motorTemperature': int(values[1]),
        'controllerTemperature': int(values[2]),
        'capVoltage': float(values[3]),
        'batteryCurrent': float(values[4]),
        'rpm': int(values[5]),
    }
    return subnode, fields


def _parse_mwv(device_tag, values):
    """mwv,subnode,windSpeed,windDirection,temperature"""
    if len(values) < 4:
        return None
    subnode = int(values[0])
    fields = {
        'windSpeed': float(values[1]),
        'windDirection': float(values[2]),
        'temperature': float(values[3]),
    }
    return subnode, fields


def _parse_imu(device_tag, values):
    """imu,subnode,accX,accY,accZ,magX,magY,magZ,gyroX,gyroY,gyroZ,heading"""
    if len(values) < 11:
        return None
    subnode = int(values[0])
    fields = {
        'acc0': float(values[1]),
        'acc1': float(values[2]),
        'acc2': float(values[3]),
        'mag0': float(values[4]),
        'mag1': float(values[5]),
        'mag2': float(values[6]),
        'gyro0': float(values[7]),
        'gyro1': float(values[8]),
        'gyro2': float(values[9]),
        'heading': float(values[10]),
    }
    return subnode, fields


def _parse_base(device_tag, values):
    """base,time — not user-visible sensor data, skip."""
    return None


# Dispatch table mapping device_type -> parser function
_DEVICE_PARSERS = {
    'temp': _parse_temp,
    'disp': _parse_disp,
    'pulse': _parse_pulse,
    'rain': _parse_rain,
    'hws': _parse_hws,
    'bat': _parse_bat,
    'wtr': _parse_wtr,
    'scl': _parse_scl,
    'inv': _parse_inv,
    'bee': _parse_bee,
    'air': _parse_air,
    'leaf': _parse_leaf,
    'gps': _parse_gps,
    'pth': _parse_pth,
    'bms': _parse_bms,
    'svc': _parse_svc,
    'mwv': _parse_mwv,
    'imu': _parse_imu,
    'base': _parse_base,
}
