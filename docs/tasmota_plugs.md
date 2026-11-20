# Tasmota power plugs (Athom Plug V2)

Monitoring only. Each plug is a `pulse` subnode in emon_config; the `emon_tasmota`
container (`python/emonTasmotaToMQTT.py`) turns the plug's Tasmota telemetry into a
`pulse3` line, which then goes everywhere any other node's line goes: the raw daily log
in `/share/Input` (through `EmonLog` and `emon_log`), Influx (through `emon_influx`),
the legacy MQTT topics and the `emon/...` envelopes emon_live reads.

```
plug --tele/<topic>/SENSOR--> mosquitto --> emon_tasmota --process_line--> EmonLog, power/<sub>/0, pulse/<sub>/0,
                                                                           rssi/<name>, emon/pulse/<sub>/...
```

## The line

```
pulse3,<sub>,<W>,0,0,0,0,0,<Wh>,0,0,0,0,0,0[:<dBm>]
```

Channel 0 is the plug: `Power` in whole watts, and `ENERGY.Total` (kWh) as a Wh count,
like every other pulse counter (pulse counters are Wh). Channels 1 to 5 are zero and
named Unused. The RSSI is the plug's WiFi `Signal` from its last STATE message, left off
if that is more than five minutes old.

`ENERGY.Total` is cumulative and survives a reboot, but Tasmota writes it to flash only
now and then, so after a power cut it can step back a little. It is logged as reported;
anything that differences the counter should, as for the other pulse counters, treat a
step back as a reset.

## Adding a plug

1. **On the plug** (its web page, Configuration, or the Console):
   - Configure MQTT: Host = the Pi's address, Port 1883, no user or password (the
     shannstainable broker allows anonymous clients).
   - Topic = a short unique name, e.g. `plug_fridge`. Leave Full Topic at its default
     `%prefix%/%topic%/`; the bridge listens on `tele/+/SENSOR`.
   - Console: `TelePeriod 10` (seconds; Tasmota's minimum).
   - Check it is publishing: the Console shows `MQT: tele/plug_fridge/SENSOR = {...ENERGY...}`
     every 10 s.

2. **In emon_config** (`provisioning/shannstainable/emon_config/`, a new dated
   `YYYYMMDD-hhmm.yml` copied from the current one, or through the settings page on :5000),
   add a pulse subnode with the plug's Topic in `tasmota`. Use a subnode number no other
   pulse node uses; 0 is the power board.

   ```yaml
   pulse:
     1:
       name: Fridge plug
       tasmota: plug_fridge
       p0: Fridge
       p0_wPerPulse: 1
       p1: Unused
       p2: Unused
       p3: Unused
       p4: Unused
       p5: Unused
   ```

   The bridges re-read the settings within a minute; no restart. Until the subnode
   exists, `docker logs emon_tasmota` shows the plug's Topic once as ignored.

3. **Check it.** `docker logs --tail 5 emon_tasmota` shows a `pulse3,<sub>,...` line every
   10 s; `grep "pulse3,<sub>," /share/Input/$(date +%Y%m%d).TXT` shows them in the raw log.

4. **emon_live and Grafana.** The feeds are `<name> / <p0>` (W) and `<name> / <p0> (pulse)`
   (Wh), e.g. `Fridge plug / Fridge`. They appear on the All feeds page at once. For a
   tile and a today total, add the plug to `provisioning/shannstainable/emon-ui/`
   (`derived.yml`: an `influx:` entry `pulse pulse/<sub>/0` and a counter; the page: the
   feeds), then `docker restart emon_live`. In Influx the plug is measurement `power`,
   sensor `power/<sub>/0`, and `pulse`, sensor `pulse/<sub>/0`; tags `sensorGroup` and
   `sensorName` are the `name` and `p0`.

## What is different from other pulse subnodes

A pulse subnode with a `tasmota` key writes no Influx points for its Unused channels
(`emon_decoder._pulse`; owner's decision, 20 Nov 2026), so a plug is three points a
message (power, energy, RSSI), not thirteen. Every other pulse subnode is unchanged.

## Troubleshooting

- Nothing in `docker logs emon_tasmota`: the plug is not reaching the broker. Its LWT
  (`tele/<topic>/LWT`, Online/Offline) is logged by the bridge when it changes.
- `... is not a 'tasmota' pulse subnode in emon_config; ignored`: the Topic on the plug
  and the `tasmota:` value differ, or the settings file in use is not the one edited.
- `... SENSOR has no ENERGY Power and Total; ignored`: the plug's template is not a power
  monitoring one (Athom's Tasmota build is; check Configuration, Module).

## Building and deploying

The image is `sfewings32/emon_tasmota_to_mqtt`, built from `python/TasmotaToMQTT.Dockerfile`
by `python/build.sh -c tasmota_to_mqtt`. It installs the pyemonlib wheel from
`python/pyEmon/dist`, so a decoder change needs the wheel rebuilt first (DESIGN 9.3).
At shannstainable, from the production checkout:

```bash
cd /share/emon_Suite/provisioning/shannstainable
docker compose up -d --no-deps emon_tasmota_to_mqtt
```
