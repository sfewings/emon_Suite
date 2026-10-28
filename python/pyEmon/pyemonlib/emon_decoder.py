"""Decode one emon serial line into Readings, once, for every sink (DESIGN 4.1).

Before this module, emon_mqtt.py and emon_influx.py each decoded every payload type, and
they did not agree: different topic layouts, different scaling (rain is a tip count on
MQTT and millimetres in Influx), different channels skipped, and a different publish
order for batteries and the IMU. Both of those outputs are relied on, by Node-RED, the
race app, event_recorder and every Grafana dashboard, so neither may change by a byte
(DESIGN 4.1).

So each decoded quantity is an Emission carrying up to three things:

    reading   the canonical, named, scaled Reading for the emon/... envelope, or None
    mqtt      a thunk returning the legacy (topic, value) exactly as emon_mqtt published it
    influx    a thunk returning the legacy (measurement, tags, value) as emon_influx wrote it

The legacy parts are thunks, evaluated by the sink in order, because that is how the old
code failed. A channel missing from emon_config raised KeyError part-way through a
message, inside a try that swallowed it, so everything before it was published and
nothing after. The MQTT and Influx functions read different settings keys and so failed
at different points. A sink that evaluates its thunks in order and stops at the first
exception reproduces exactly that, separately for each sink. tests/legacy holds the old
modules verbatim and tests/test_decoder_regression.py holds this module to them.

Where the two old functions published in a different order (battery, IMU heading), the
quantity is emitted twice, once per sink, so that each sink's order is kept. The canonical
reading rides on one of the pair.

The canonical value is the Influx one where Influx had one, because that is the named and
scaled form; otherwise the MQTT one. Canonical names never raise: a missing name falls
back to the field name, and a channel named Unused gets no envelope.
"""

from __future__ import annotations

import json
import re
import time as _time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import pyemonlib.emonSuite as emonSuite
from pyemonlib.emon_feed import UNUSED, Reading

LegacyMqtt = Tuple[str, Any]
LegacyInflux = Tuple[str, Tuple[Tuple[str, str], ...], Any]


@dataclass
class Emission:
    reading: Optional[Reading]
    mqtt: Optional[Callable[[], LegacyMqtt]] = None
    influx: Optional[Callable[[], LegacyInflux]] = None
    unused: bool = False
    """The channel is named Unused in emon_config. The MQTT sink leaves its legacy topic
    out unless told otherwise (owner's decision, 19 Oct 2026); Influx is unchanged."""


def node_type(line: str) -> str:
    """'pulse' from 'pulse2,0,...': the dispatch key, as both old process_line did."""
    return line.split(",", 1)[0].rstrip("0123456789")


def find_v_reference(config: Mapping) -> int:
    """X where 'vX_reference' is True, else -1. Verbatim from the old modules."""
    for k, val in config.items():
        if isinstance(k, str) and k.endswith("_reference"):
            m = re.match(r"^v(\d+)_reference$", k)
            if m and val is True:
                return int(m.group(1))
    return -1


def _rssi_value(line: str) -> Optional[int]:
    if ":" not in line:
        return None
    try:
        return int(line.split(":")[1])
    except (IndexError, ValueError):
        return None


class _Out:
    """Collects the emissions for one line, with safe lookups for canonical names."""

    def __init__(self, node: str, sub: Optional[int], ns: Mapping, t: float, line: str):
        self.node, self.sub, self.ns, self.t, self.line = node, sub, ns, t, line
        self.rssi = _rssi_value(line)
        self.items: List[Emission] = []

    def setting(self, sub: Any, key: str, default: Any = None) -> Any:
        try:
            value = self.ns[sub][key]
        except (KeyError, TypeError, IndexError):
            return default
        return default if value is None else value

    @property
    def group(self) -> str:
        return str(self.setting(self.sub if self.sub is not None else 0, "name", "") or "")

    def reading(self, field: str, value: Any, unit: str, kind: str, idx: Any = None,
                name: Optional[str] = None) -> Optional[Reading]:
        """The canonical reading, or None for a channel or a whole node named Unused."""
        if name == UNUSED or self.group == UNUSED:
            return None
        label = name if name else (field if idx is None else f"{field} {idx}")
        return Reading(node=self.node, sub=self.sub, field=field, value=value, unit=unit,
                       kind=kind, idx=idx, group=self.group, name=str(label), t=self.t,
                       rssi=self.rssi)

    def unused(self, sub: Any, key: str) -> bool:
        return self.setting(sub, key) == UNUSED

    def emit(self, reading: Optional[Reading], mqtt=None, influx=None, unused=False) -> None:
        self.items.append(Emission(reading, mqtt, influx, unused))


def _tags(sensor: str, group: Optional[str], name: str) -> Tuple[Tuple[str, str], ...]:
    tags = [("sensor", sensor)]
    if group is not None:
        tags.append(("sensorGroup", group))
    tags.append(("sensorName", name))
    return tuple(tags)


def _rssi(o: _Out, name_fn: Callable[[], str]) -> None:
    """The RSSI reading, as both old publishRSSI did, last in every message.

    Not published when the packet came through more than one relay, because then nobody
    knows which hop the RSSI belongs to. Through one relay, the relay path is appended.
    """
    line = o.line
    if ":" not in line:
        return
    vals = line.split(":")
    relay = None
    if "|" in vals[0]:
        relay = vals[0].split("|")[1]
        if relay.count("1") > 1:
            return

    def legacy_name() -> str:
        name = name_fn()
        return name + "-" + relay if relay is not None else name

    def mqtt():
        return (f"rssi/{legacy_name()}", int(vals[1]))

    def influx():
        name = legacy_name()
        return ("rssi", (("sensor", f"rssi/{name}"), ("sensorGroup", "RSSI"),
                         ("sensorName", name)), int(vals[1]))

    try:
        value = int(vals[1])
    except ValueError:
        value = None
    reading = None
    if value is not None:
        # The node type is in the name: one location often has several node types under
        # one group name (a 'Kitchen' display and a 'Kitchen' air sensor), and each has
        # its own RSSI (DESIGN 5).
        label = f"rssi ({o.node})" if relay is None else f"rssi ({o.node} via {relay})"
        reading = o.reading("rssi", value, "dBm", "rssi", idx=relay, name=label)
    o.emit(reading, mqtt, influx)


# --------------------------------------------------------------------------------------
# One function per payload type, in the order of the old dispatch tables. Each mirrors
# the old mqtt and influx functions side by side; the comments name anything odd that is
# kept on purpose.
# --------------------------------------------------------------------------------------

def _rain(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadRain()
    if not emonSuite.EmonSerial.ParseRainPayload(line, p):
        return None
    o = _Out("rain", 0, ns, t, line)
    mm = o.setting(0, "mmPerPulse")
    rain = o.reading("rain", p.rainCount * mm if mm is not None else p.rainCount,
                     "mm" if mm is not None else "count", "rain")
    # MQTT carries the raw tip count; Influx carries mm.
    o.emit(rain,
           lambda: ("rain", p.rainCount),
           lambda: ("rain", _tags("rain", "rain gauge", ns[0]["name"]),
                    p.rainCount * ns[0]["mmPerPulse"]))
    o.emit(o.reading("temperature", p.temperature / 100, "degC", "temperature"),
           lambda: ("temperature/rain/0", p.temperature / 100),
           lambda: ("temperature", _tags("temperature/rain", "rain gauge", ns[0]["name"]),
                    p.temperature / 100))
    # MQTT published supplyV unscaled, in mV; Influx in V and with no sensorGroup tag.
    o.emit(o.reading("supplyV", p.supplyV / 1000, "V", "voltage"),
           lambda: ("supplyV/rain", p.supplyV),
           lambda: ("supplyV", _tags("supply voltage", None, ns[0]["name"]), p.supplyV / 1000))
    _rssi(o, lambda: ns[0]["name"])
    return o.items


def _temp(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadTemperature()
    if not emonSuite.EmonSerial.ParseTemperaturePayload(line, p):
        return None
    s = p.subnode
    o = _Out("temp", s, ns, t, line)
    for sensor in range(p.numSensors):
        value = p.temperature[sensor] / 100
        o.emit(o.reading("temperature", value, "degC", "temperature", sensor,
                         o.setting(s, f"t{sensor}")),
               lambda sensor=sensor, value=value: (f"temperature/temp/{s}/{sensor}", value),
               lambda sensor=sensor, value=value: (
                   "temperature", _tags(f"temperature/temp/{s}/{sensor}", ns[s]["name"],
                                        ns[s][f"t{sensor}"]), value),
               o.unused(s, f"t{sensor}"))
    o.emit(o.reading("supplyV", p.supplyV / 1000, "V", "voltage"),
           lambda: (f"supplyV/temp/{s}", p.supplyV / 1000),
           lambda: ("supplyV", _tags(f"supplyV/temp/{s}", ns[s]["name"], ns[s]["name"]),
                    p.supplyV / 1000))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _disp(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadDisp()
    if not emonSuite.EmonSerial.ParseDispPayload(line, p):
        return None
    s = p.subnode
    o = _Out("disp", s, ns, t, line)
    o.emit(o.reading("temperature", p.temperature / 100, "degC", "temperature"),
           lambda: (f"temperature/disp/{s}", p.temperature / 100),
           lambda: ("temperature", _tags(f"temperature/disp/{s}", ns[s]["name"], ns[s]["name"]),
                    p.temperature / 100))
    _rssi(o, lambda: ns[s]["name"] + " display")
    return o.items


def _pulse(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadPulse()
    if not emonSuite.EmonSerial.ParsePulsePayload(line, p):
        return None
    s = p.subnode
    o = _Out("pulse", s, ns, t, line)
    for sensor in range(emonSuite.PULSE_MAX_SENSORS):
        name = o.setting(s, f"p{sensor}")
        power, pulse = p.power[sensor] / 1, p.pulse[sensor] / 1
        o.emit(o.reading("power", power, "W", "power", sensor, name),
               lambda sensor=sensor, power=power: (f"power/{s}/{sensor}", power),
               lambda sensor=sensor, power=power: (
                   "power", _tags(f"power/{s}/{sensor}", ns[s]["name"], ns[s][f"p{sensor}"]), power),
               o.unused(s, f"p{sensor}"))
        # Same channel name for both kinds; the counter takes the bracketed one (DESIGN 5).
        o.emit(o.reading("pulse", pulse, "pulse", "count", sensor,
                         f"{name} (pulse)" if name and name != UNUSED else name),
               lambda sensor=sensor, pulse=pulse: (f"pulse/{s}/{sensor}", pulse),
               lambda sensor=sensor, pulse=pulse: (
                   "pulse", _tags(f"pulse/{s}/{sensor}", ns[s]["name"], ns[s][f"p{sensor}"]), pulse),
               o.unused(s, f"p{sensor}"))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _hws(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadHWS()
    if not emonSuite.EmonSerial.ParseHWSPayload(line, p):
        return None
    o = _Out("hws", 0, ns, t, line)
    for sensor in range(emonSuite.HWS_TEMPERATURES):
        value = p.temperature[sensor] / 1
        o.emit(o.reading("temperature", value, "degC", "temperature", sensor,
                         o.setting(0, f"t{sensor}")),
               lambda sensor=sensor, value=value: (f"temperature/HWS/{sensor}", value),
               lambda sensor=sensor, value=value: (
                   "temperature", _tags(f"temperature/HWS/{sensor}", ns[0]["name"],
                                        ns[0][f"t{sensor}"]), value),
               o.unused(0, f"t{sensor}"))
    for sensor in range(emonSuite.HWS_PUMPS):
        value = p.pump[sensor] / 1
        o.emit(o.reading("pump", value, "", "state", sensor, o.setting(0, f"p{sensor}")),
               lambda sensor=sensor, value=value: (f"pump/HWS/{sensor}", value),
               lambda sensor=sensor, value=value: (
                   "pump", _tags(f"pump/HWS/{sensor}", ns[0]["name"], ns[0][f"p{sensor}"]), value),
               o.unused(0, f"p{sensor}"))
    _rssi(o, lambda: ns[0]["name"])
    return o.items


def _wtr(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadWater()
    if not emonSuite.EmonSerial.ParseWaterPayload(line, p):
        return None
    s = p.subnode
    o = _Out("wtr", s, ns, t, line)
    for sensor in range(p.numFlowSensors):
        lpp = o.setting(s, f"f{sensor}_litresPerPulse")
        canonical = p.flowCount[sensor] * lpp if lpp is not None else p.flowCount[sensor]
        o.emit(o.reading("flowCount", canonical, "L" if lpp is not None else "pulse", "volume",
                         sensor, o.setting(s, f"f{sensor}")),
               lambda sensor=sensor: (f"water/flowCount/{s}/{sensor}",
                                      p.flowCount[sensor] * ns[s][f"f{sensor}_litresPerPulse"]),
               lambda sensor=sensor: (
                   "water", _tags(f"water/flowCount/{s}/{sensor}", ns[s]["name"], ns[s][f"f{sensor}"]),
                   p.flowCount[sensor] * ns[s][f"f{sensor}_litresPerPulse"]),
               o.unused(s, f"f{sensor}"))
    for sensor in range(p.numHeightSensors):
        value = p.waterHeight[sensor] / 1
        o.emit(o.reading("height", value, "mm", "level", sensor, o.setting(s, f"h{sensor}")),
               lambda sensor=sensor, value=value: (f"water/height/{s}/{sensor}", value),
               lambda sensor=sensor, value=value: (
                   "tank", _tags(f"water/height/{s}/{sensor}", ns[s]["name"], ns[s][f"h{sensor}"]), value),
               o.unused(s, f"h{sensor}"))
    o.emit(o.reading("supplyV", p.supplyV / 1000, "V", "voltage"),
           lambda: (f"supplyV/water/{s}", p.supplyV / 1000),
           lambda: ("supplyV", _tags(f"supplyV/water/{s}", ns[s]["name"], ns[s]["name"]),
                    p.supplyV / 1000))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _scl(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadScale()
    if not emonSuite.EmonSerial.ParseScalePayload(line, p):
        return None
    s = p.subnode
    o = _Out("scl", s, ns, t, line)
    o.emit(o.reading("scale", p.grams / 1, "g", "mass"),
           lambda: (f"scale/{s}", p.grams / 1),
           lambda: ("scale", _tags(f"scale/{s}", ns[s]["name"], ns[s]["name"]), p.grams / 1))
    o.emit(o.reading("supplyV", p.supplyV / 1000, "V", "voltage"),
           lambda: (f"supplyV/scale/{s}", p.supplyV / 1000),
           lambda: ("supplyV", _tags(f"supplyV/scale/{s}", ns[s]["name"], ns[s]["name"]),
                    p.supplyV / 1000))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _bat(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    """The two old functions differ most here, so each sink gets its own emissions.

    MQTT, per shunt not named Unused: power, pulseIn, pulseOut interleaved, topic
    battery/<kind>/<sub>/<shunt>; then every voltage channel, Unused or not.
    Influx: all powers, then all pulseIns, then all pulseOuts, tag battery/<kind>/<shunt>/<sub>
    (the other way round); then only voltage channels not named Unused.
    Canonical readings ride on the Influx emissions.
    """
    p = emonSuite.PayloadBattery()
    if not emonSuite.EmonSerial.ParseBatteryPayload(line, p):
        return None
    s = p.subnode
    o = _Out("bat", s, ns, t, line)

    for sensor in range(emonSuite.BATTERY_SHUNTS):
        def gate(sensor=sensor):
            return ns[s][f"s{sensor}"] != UNUSED

        def mq(kind, value, sensor=sensor, gate=gate):
            def thunk():
                if not gate():
                    return None
                return (f"battery/{kind}/{s}/{sensor}", value)
            return thunk

        o.emit(None, mq("power", p.power[sensor] / 1))
        o.emit(None, mq("pulseIn", p.pulseIn[sensor] / 1))
        o.emit(None, mq("pulseOut", p.pulseOut[sensor] / 1))

    def influx_shunts(kind: str, measurement: str, suffix: str, attr: str, unit: str,
                      rkind: str) -> None:
        for sensor in range(emonSuite.BATTERY_SHUNTS):
            value = getattr(p, attr)[sensor] / 1
            name = o.setting(s, f"s{sensor}")
            label = name if (not suffix or not name or name == UNUSED) else f"{name} ({kind})"

            def thunk(sensor=sensor, value=value):
                if ns[s][f"s{sensor}"] == UNUSED:
                    return None
                return (measurement, _tags(f"battery/{kind}/{sensor}/{s}", ns[s]["name"],
                                           ns[s][f"s{sensor}"] + suffix), value)
            o.emit(o.reading(kind, value, unit, rkind, sensor, label), None, thunk)

    influx_shunts("power", "power", "", "power", "W", "power")
    influx_shunts("pulseIn", "pulse", "In", "pulseIn", "pulse", "count")
    influx_shunts("pulseOut", "pulse", "Out", "pulseOut", "pulse", "count")

    # Mid-point voltages are measured against half the rail when a vX_reference is set.
    ref = find_v_reference(ns[s]) if isinstance(ns.get(s) if hasattr(ns, "get") else None, Mapping) else -1
    rail = p.voltage[ref] / 100.0 if ref != -1 else 0.0
    voltages = []
    for sensor in range(emonSuite.MAX_VOLTAGES):
        voltage = p.voltage[sensor] / 100.0
        if ref != -1 and sensor != ref:
            voltage = voltage - rail / 2.0
        voltages.append(voltage)

    # The MQTT function looked the reference up only after its shunt loop, and from
    # ns[s] directly, so a missing subnode had already stopped it. Nothing to mirror.
    for sensor in range(emonSuite.MAX_VOLTAGES):
        o.emit(None, lambda sensor=sensor: (f"battery/voltage/{s}/{sensor}", voltages[sensor] / 1),
               unused=o.unused(s, f"v{sensor}"))
    for sensor in range(emonSuite.MAX_VOLTAGES):
        def thunk(sensor=sensor):
            if ns[s][f"v{sensor}"] == UNUSED:
                return None
            return ("voltage", _tags(f"battery/voltage/{sensor}/{s}", ns[s]["name"],
                                     ns[s][f"v{sensor}"]), voltages[sensor] / 1)
        o.emit(o.reading("voltage", voltages[sensor] / 1, "V", "voltage", sensor,
                         o.setting(s, f"v{sensor}")), None, thunk)
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _inv(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadInverter()
    if not emonSuite.EmonSerial.ParseInverterPayload(line, p):
        return None
    s = p.subnode
    o = _Out("inv", s, ns, t, line)
    # (field, mqtt topic stem, measurement, influx name suffix, value, unit, kind)
    rows = [
        ("activePower", "power", "power", "", p.activePower / 1, "W", "power"),
        ("apparentPower", "apparentPower", "power", " - apparent power", p.apparentPower / 1, "VA", "power"),
        ("batteryVoltage", "batteryVoltage", "voltage", "", p.batteryVoltage / 10, "V", "voltage"),
        # 'Dicharge' is the published spelling; it stays.
        ("batteryDischarge", "batteryDicharge", "current", " - Discharge", p.batteryDischarge / 1, "A", "current"),
        ("batteryCharging", "batteryCharging", "current", " - Charge", p.batteryCharging / 1, "A", "current"),
        ("pvInputPower", "pvInputPower", "power", " - PV", p.pvInputPower / 1, "W", "power"),
        ("batteryCapacity", "batteryCapacity", "capacity", "", p.batteryCapacity / 1, "%", "capacity"),
        ("pulse", "pulse", "pulse", "", p.pulse / 1, "pulse", "count"),
    ]
    for field, stem, measurement, suffix, value, unit, kind in rows:
        o.emit(o.reading(field, value, unit, kind),
               lambda stem=stem, value=value: (f"inverter/{stem}/{s}", value),
               lambda stem=stem, measurement=measurement, suffix=suffix, value=value: (
                   measurement, _tags(f"inverter/{stem}/{s}", ns[s]["name"], ns[s]["name"] + suffix), value))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _bee(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadBeehive()
    if not emonSuite.EmonSerial.ParseBeehivePayload(line, p):
        return None
    s = p.subnode
    o = _Out("bee", s, ns, t, line)
    # (field, mqtt topic, measurement, influx sensor tag, influx name suffix, value, unit, kind)
    rows = [
        ("beeInRate", f"beehive/beeInRate/{s}", "beehive", f"beehive/beeInRate/{s}", " - In rate", p.beeInRate, "bees/min", "rate"),
        ("beeOutRate", f"beehive/beeOutRate/{s}", "beehive", f"beehive/beeOutRate/{s}", " - Out rate", p.beeOutRate, "bees/min", "rate"),
        ("beesIn", f"beehive/beesIn/{s}", "beehive", f"beehive/beesIn/{s}", " - In", p.beesIn, "bees", "count"),
        ("beesOut", f"beehive/beesOut/{s}", "beehive", f"beehive/beesOut/{s}", " - Out", p.beesOut, "bees", "count"),
        ("temperatureIn", f"temperature/beehiveIn/{s}", "temperature", f"temperature/beehiveIn/{s}", " - Inside", p.temperatureIn / 100, "degC", "temperature"),
        ("temperatureOut", f"temperature/beehiveOut/{s}", "temperature", f"temperature/beehiveOut/{s}", " - Outside", p.temperatureOut / 100, "degC", "temperature"),
        ("scale", f"beehive/scale/{s}", "scale", f"scale/beehive/{s}", "", p.grams / 1, "g", "mass"),
        ("supplyV", f"supplyV/beehive/{s}", "supplyV", f"supplyV/beehive/{s}", "", p.supplyV / 1000, "V", "voltage"),
    ]
    for field, topic, measurement, sensor, suffix, value, unit, kind in rows:
        o.emit(o.reading(field, value, unit, kind),
               lambda topic=topic, value=value: (topic, value),
               lambda measurement=measurement, sensor=sensor, suffix=suffix, value=value: (
                   measurement, _tags(sensor, ns[s]["name"], ns[s]["name"] + suffix), value))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _air(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadAirQuality()
    if not emonSuite.EmonSerial.ParseAirQualityPayload(line, p):
        return None
    s = p.subnode
    o = _Out("air", s, ns, t, line)
    for field, suffix in (("pm0p3", " - 0.3"), ("pm0p5", " - 0.5"), ("pm1p0", " - 1.0"),
                          ("pm2p5", " - 2.5"), ("pm5p0", " - 5.0"), ("pm10p0", " - 10.0")):
        value = getattr(p, field)
        o.emit(o.reading(field, value, "count", "particles"),
               lambda field=field, value=value: (f"airQuality/{field}/{s}", value),
               lambda field=field, suffix=suffix, value=value: (
                   "air", _tags(f"airQuality/{field}/{s}", ns[s]["name"], ns[s]["name"] + suffix), value))
    _rssi(o, lambda: ns[s]["name"] + " air")
    return o.items


def _leaf(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadLeaf()
    if not emonSuite.EmonSerial.ParseLeafPayload(line, p):
        return None
    s = p.subnode
    o = _Out("leaf", s, ns, t, line)
    # (field, mqtt topic, influx sensor tag, influx name suffix, unit, kind)
    rows = [
        ("odometer", f"leaf/odometer/{s}", f"leaf/odometer/{s}", " - Odometer", "km", "distance"),
        ("range", f"leaf/range/{s}", f"leaf/range/{s}", " - Range", "km", "distance"),
        ("batteryTemperature", f"temperature/leaf/{s}", f"leaf/batteryTemperature/{s}", " - Battery Temperature", "degC", "temperature"),
        ("batterySOH", f"leaf/batterySOH/{s}", f"leaf/batterySOH/{s}", " - Battery SOH", "%", "capacity"),
        ("batteryWH", f"leaf/batteryWH/{s}", f"leaf/batteryWH/{s}", " - Battery WH", "Wh", "energy"),
        ("batteryChargeBars", f"leaf/batteryChargeBars/{s}", f"leaf/batteryChargeBars/{s}", " - Battery charge bars", "bars", "capacity"),
        ("chargeTimeRemaining", f"leaf/chargeTimeRemaining/{s}", f"leaf/chargeTimeRemaining/{s}", " - Charge time remaining", "min", "duration"),
    ]
    for field, topic, sensor, suffix, unit, kind in rows:
        value = getattr(p, field)
        o.emit(o.reading(field, value, unit, kind),
               lambda topic=topic, value=value: (topic, value),
               lambda sensor=sensor, suffix=suffix, value=value: (
                   "leaf", _tags(sensor, ns[s]["name"], ns[s]["name"] + suffix), value))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _gps(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadGPS()
    if not emonSuite.EmonSerial.ParseGPSPayload(line, p):
        return None
    s = p.subnode
    o = _Out("gps", s, ns, t, line)
    o.emit(o.reading("latitude", p.latitude, "deg", "position"),
           lambda: (f"gps/latitude/{s}", p.latitude),
           lambda: ("gps", _tags(f"gps/{s}/latitude", ns[s]["name"], "latitude"), p.latitude))
    o.emit(o.reading("longitude", p.longitude, "deg", "position"),
           lambda: (f"gps/longitude/{s}", p.longitude),
           lambda: ("gps", _tags(f"gps/{s}/longitude", ns[s]["name"], "longitude"), p.longitude))
    o.emit(o.reading("course", p.course, "deg", "bearing"),
           lambda: (f"gps/course/{s}", p.course),
           lambda: ("gps", _tags(f"gps/course/{s}", ns[s]["name"], ns[s]["name"] + "-course"), p.course))
    o.emit(o.reading("speed", p.speed, "kn", "speed"),
           lambda: (f"gps/speed/{s}", p.speed),
           lambda: ("gps", _tags(f"gps/speed/{s}", ns[s]["name"], ns[s]["name"] + "-speed"), p.speed))
    # The atomic position (enchantee_racing DESIGN 3), MQTT only, skipped with no fix:
    # TinyGPS gives 1000.0 for an unknown angle and the node transmits regardless.
    if abs(p.latitude) <= 90.0 and abs(p.longitude) <= 180.0:
        position = {"lat": round(p.latitude, 7), "lon": round(p.longitude, 7)}
        o.emit(o.reading("position", position, "", "position"),
               lambda: (f"gps/position/{s}", json.dumps(
                   {**position, "ts": int(t)}, separators=(",", ":"))))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _pth(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadPressure()
    if not emonSuite.EmonSerial.ParsePressurePayload(line, p):
        return None
    s = p.subnode
    o = _Out("pth", s, ns, t, line)
    o.emit(o.reading("pressure", p.pressure, "hPa", "pressure"),
           lambda: (f"pth/pressure/{s}", p.pressure),
           lambda: ("pressure", _tags(f"pressure/pth/{s}", ns[s]["name"], ns[s]["name"] + " - Pressure"), p.pressure))
    o.emit(o.reading("temperature", p.temperature, "degC", "temperature"),
           lambda: (f"temperature/pth/{s}", p.temperature),
           lambda: ("temperature", _tags(f"temperature/pth/{s}", ns[s]["name"], ns[s]["name"] + " - Temperature"), p.temperature))
    o.emit(o.reading("humidity", p.humidity, "%", "humidity"),
           lambda: (f"pth/humidity/{s}", p.humidity),
           lambda: ("humidity", _tags(f"humidity/pth/{s}", ns[s]["name"], ns[s]["name"] + " - Humidity"), p.humidity))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _bms(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadDalyBMS()
    if not emonSuite.EmonSerial.ParseDalyBMSPayload(line, p):
        return None
    s = p.subnode
    o = _Out("bms", s, ns, t, line)
    # Two MQTT topics lack the slash before the subnode. Kept in the legacy namespace,
    # correct in emon/... (DESIGN 4.2).
    o.emit(o.reading("batteryVoltage", p.batteryVoltage / 10.0, "V", "voltage"),
           lambda: (f"bms/voltage{s}", p.batteryVoltage / 10.0),
           lambda: ("voltage", _tags(f"bms/voltage/{s}", ns[s]["name"], ns[s]["name"]), p.batteryVoltage / 10.0))
    o.emit(o.reading("batterySoC", p.batterySoC / 10.0, "%", "capacity"),
           lambda: (f"bms/batterySoC/{s}", p.batterySoC / 10.0),
           lambda: ("bms", _tags(f"bms/SoC/{s}", ns[s]["name"], ns[s]["name"] + " - SoC"), p.batterySoC / 10.0))
    o.emit(o.reading("power", (p.current * p.batteryVoltage) / 10.0, "W", "power"),
           lambda: (f"bms/power/{s}", p.current * p.batteryVoltage / 10.0),
           lambda: ("power", _tags(f"bms/power/{s}", ns[s]["name"], ns[s]["name"]), (p.current * p.batteryVoltage) / 10.0))
    o.emit(o.reading("resCapacity", p.resCapacity / 1.0, "Ah", "capacity"),
           lambda: (f"bms/resCapacity/{s}", p.resCapacity),
           lambda: ("bms", _tags(f"bms/resCapacity/{s}", ns[s]["name"], ns[s]["name"] + " - Res capacity"), p.resCapacity / 1.0))
    o.emit(o.reading("temperature", p.temperature / 1.0, "degC", "temperature"),
           lambda: (f"temperature/bms/{s}", p.temperature),
           lambda: ("temperature", _tags(f"bms/temperature/{s}", ns[s]["name"], ns[s]["name"]), p.temperature / 1.0))
    o.emit(o.reading("lifetimeCycles", p.lifetimeCycles / 1.0, "cycles", "count"),
           lambda: (f"bms/lifetimeCycles{s}", p.lifetimeCycles),
           lambda: ("bms", _tags(f"bms/lifetimeCycles/{s}", ns[s]["name"], ns[s]["name"] + " - Lifetime cycles"), p.lifetimeCycles / 1.0))
    for cell in range(emonSuite.MAX_BMS_CELLS):
        voltage = p.cellmv[cell] / 1000.0
        o.emit(o.reading("cellVoltage", voltage, "V", "voltage", cell),
               lambda cell=cell, voltage=voltage: (f"bms/cellVoltage/{s}/{cell}", voltage),
               lambda cell=cell, voltage=voltage: (
                   "voltage", _tags(f"bms/cellVoltage/{s}/{cell}", ns[s]["name"], ns[s]["name"] + f" - cell {cell}"),
                   voltage / 1.0))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _svc(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadSevCon()
    if not emonSuite.EmonSerial.ParseSevConPayload(line, p):
        return None
    s = p.subnode
    o = _Out("svc", s, ns, t, line)
    o.emit(o.reading("motorTemperature", p.motorTemperature / 1.0, "degC", "temperature"),
           lambda: (f"sevCon/temperature/motor/{s}", p.motorTemperature),
           lambda: ("temperature", _tags(f"sevCon/temperature/{s}/motor", ns[s]["name"], ns[s]["name"] + "motor"),
                    p.motorTemperature / 1.0))
    o.emit(o.reading("controllerTemperature", p.controllerTemperature / 1.0, "degC", "temperature"),
           lambda: (f"sevCon/temperature/controller/{s}", p.controllerTemperature),
           lambda: ("temperature", _tags(f"sevCon/temperature/{s}/controller", ns[s]["name"], ns[s]["name"] + "controller"),
                    p.controllerTemperature / 1.0))
    # Three MQTT topics lack the slash before the subnode (DESIGN 4.2).
    o.emit(o.reading("capVoltage", p.capVoltage, "V", "voltage"),
           lambda: (f"sevCon/voltage{s}", p.capVoltage),
           lambda: ("voltage", _tags(f"sevCon/voltage/{s}", ns[s]["name"], ns[s]["name"]), p.capVoltage))
    o.emit(o.reading("batteryCurrent", p.batteryCurrent, "A", "current"),
           lambda: (f"sevCon/current{s}", p.batteryCurrent),
           lambda: ("power", _tags(f"sevCon/current/{s}", ns[s]["name"], ns[s]["name"] + " - current"), p.batteryCurrent))
    o.emit(o.reading("rpm", p.rpm / 1.0, "rpm", "speed"),
           lambda: (f"sevCon/rpm{s}", p.rpm),
           lambda: ("sevCon", _tags(f"sevCon/rpm/{s}", ns[s]["name"], ns[s]["name"] + " - RPM"), p.rpm / 1.0))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _mwv(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    p = emonSuite.PayloadAnemometer()
    if not emonSuite.EmonSerial.ParseAnemometerPayload(line, p):
        return None
    s = p.subnode
    o = _Out("mwv", s, ns, t, line)
    o.emit(o.reading("temperature", p.temperature / 1.0, "degC", "temperature"),
           lambda: (f"anemometer/temperature/{s}", p.temperature),
           lambda: ("temperature", _tags(f"anemometer/temperature/{s}", ns[s]["name"], ns[s]["name"] + " - Temperature"),
                    p.temperature / 1.0))
    o.emit(o.reading("windSpeed", p.windSpeed, "kn", "speed"),
           lambda: (f"anemometer/windSpeed/{s}", p.windSpeed),
           lambda: ("anemometer", _tags(f"anemometer/windSpeed/{s}", ns[s]["name"], ns[s]["name"] + " - Wind Speed"), p.windSpeed))
    o.emit(o.reading("windDirection", p.windDirection, "deg", "bearing"),
           lambda: (f"anemometer/windDirection/{s}", p.windDirection),
           lambda: ("anemometer", _tags(f"anemometer/windDirection/{s}", ns[s]["name"], ns[s]["name"] + " - Wind Direction"),
                    p.windDirection))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


def _imu(line: str, ns: Mapping, t: float) -> Optional[List[Emission]]:
    """Influx wrote heading first and MQTT last, so heading is emitted once for each."""
    p = emonSuite.PayloadIMU()
    if not emonSuite.EmonSerial.ParseIMUPayload(line, p):
        return None
    s = p.subnode
    o = _Out("imu", s, ns, t, line)
    o.emit(o.reading("heading", p.heading, "deg", "bearing"), None,
           lambda: ("imu", _tags(f"imu/{s}/heading", ns[s]["name"], ns[s]["name"]), p.heading))
    for field, unit in (("acc", "g"), ("mag", "uT"), ("gyro", "deg/s")):
        values = getattr(p, field)
        for axis in range(3):
            o.emit(o.reading(field, float(values[axis]), unit, field, axis),
                   lambda field=field, axis=axis: (f"imu/{s}/{field}/{axis}", float(getattr(p, field)[axis])),
                   lambda field=field, axis=axis: (
                       "imu", _tags(f"imu/{s}/{field}/{axis}", ns[s]["name"], ns[s]["name"] + f" - {field}[{axis}]"),
                       getattr(p, field)[axis]))
    o.emit(None, lambda: (f"imu/{s}/heading", p.heading))
    _rssi(o, lambda: ns[s]["name"])
    return o.items


DECODERS: Dict[str, Callable[[str, Mapping, float], Optional[List[Emission]]]] = {
    "rain": _rain, "temp": _temp, "disp": _disp, "pulse": _pulse, "hws": _hws,
    "wtr": _wtr, "scl": _scl, "bat": _bat, "inv": _inv, "bee": _bee, "air": _air,
    "leaf": _leaf, "gps": _gps, "pth": _pth, "bms": _bms, "svc": _svc, "mwv": _mwv,
    "imu": _imu,
}
"""Every payload type both old dispatch tables handled, except 'other', which only printed."""


def decode(line: str, node_settings: Mapping, t: Optional[float] = None) -> List[Emission]:
    """The emissions for one line, in order. [] if the payload does not parse.

    node_settings is settings[node_type(line)], as the old dispatch passed it. t defaults
    to now; it stamps the canonical readings and the gps/position payload's ts.
    """
    decoder = DECODERS.get(node_type(line))
    if decoder is None:
        return []
    items = decoder(line, node_settings, _time.time() if t is None else t)
    return items or []


def readings(line: str, node_settings: Mapping, t: Optional[float] = None) -> List[Reading]:
    """Only the canonical readings of a line."""
    return [e.reading for e in decode(line, node_settings, t) if e.reading is not None]
