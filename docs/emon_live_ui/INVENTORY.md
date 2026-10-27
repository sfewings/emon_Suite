# emon live UI redesign: inventory of the existing system

Facts gathered on 19 October 2026 from the `emon-node-red` repository and emon_Suite,
recorded here because the Node-RED flows are in a different repository and a later
session should not have to re-derive them. Where this says "today", it means that date.

Node-RED branches in `emon-node-red` (remote `origin`):

| Branch | Site |
|---|---|
| `nodeRed` | shannstainable (default branch) |
| `Enchantee` | enchantee |
| `harvey-farm` | harvey-farm (last commit `0f08c20`) |

On a Pi, Node-RED's user directory is `/share/emon-node-red`, bind-mounted at `/data`.

---

## 1. Topics subscribed by shannstainable's Instant Data flow

`power/0/#`, `pulse/0/#`, `power/0/4`, `temperature/disp/0`, `temperature/disp/3`,
`temperature/rain/#`, `temperature/HWS/2`, `temperature/temp/0/1`, `pump/HWS/#`,
`water/flowCount/0/0`, `water/flowCount/1/0`, `water/flowCount/1/1`, `water/height/0/0`,
`rain`, `scale/0`, `battery/voltage/0/#`, `battery/pulseIn/4/+`, `battery/pulseOut/4/+`,
`battery/pulseIn/5/+`, `battery/pulseOut/5/+`, `battery/power/4/+`, `battery/power/5/+`,
`inverter/batteryCapacity/0`, `inverter/pvInputPower/#`, `leaf/#`.

## 2. What shannstainable's Instant Data flow computes, and where it goes

"Target" is the home under this design: `derived.yml` (emon_live, PLAN 2b), `Node-RED`
(stays, publishes envelopes, DESIGN D5), or `page` (just display).

| Function node | Computes | Target |
|---|---|---|
| Calculate Instant power | consuming, producing (sum of three inverters' pvInputPower), importing, exporting (inverter 2 minus average night import), car | `derived.yml` (`sum`, `expr`); the average-import estimate of export is bespoke, keep in Node-RED or simplify |
| Accumulate daily usage | Wh today per pulse channel from pulse counts; solar today adds inverter integrals | `derived.yml` `daily_delta`, `integrate`, `sum` |
| Calculate daily exported (2 s inject) | export Wh by 2 s integration; foregone production (inverter 2 × 1.19 and × 1.11 against inverters 1 and 3) and its value | `derived.yml` `integrate`, `expr` |
| Calculate solar production | per-inverter Wh today by integration | `derived.yml` `integrate` |
| Costs | import and HWS at 0.262 $/kWh; export and foregone at 0.07135 $/kWh (0.07 in the email) | `derived.yml` `expr`; tariffs become site config |
| Current water temperatures | showers remaining = (T − 45) / 0.7 min, "Too cold" under 40 °C | `derived.yml` `expr` |
| Accumulate daily water usage (hot) | litres today; shower detection (flow over 3 min counts as a shower) and shower minutes | litres: `derived.yml`; showers: `Node-RED` |
| Accumulate daily water usage (mains), bore | litres today | `derived.yml` `daily_delta` |
| Calculate Rain water details | tank %, 460 to 2050 mm; days remaining from a rolling 7-day average use (default 90 mm/day) | %: `derived.yml` `expr`; days remaining: `Node-RED` |
| Calculate D,M,Y rainfalls | today, since 9am (0.2 mm per tip), month and year read from `/share/Output/rain/*.txt` and `*.json` files | today and since 9am: `derived.yml` `daily_delta`; month and year: Influx query, or keep Node-RED |
| Get last reading time | dog fed when the scale drops by over 150 g; "Today/Yesterday at hh:mm"; food remaining kg; sends a "has just been fed" email | `Node-RED` |
| Battery Voltage | rail voltage, min and max of the day, worst mid-point voltage per channel, "Healthy" or a list over 1 V. Channel names hard-coded: `Rail, B2-5, unused, unused, unused, B2-4, B2-3, B2-2, B2-1` | names from emon_config (already in `bat: 0:`); max mid-voltage: `derived.yml` (a `daily_max` operator may be needed) |
| Battery Current, Inverters Current | Wh in and out today per bank; out-to-9am | `derived.yml` `daily_delta` with `reset` |
| Battery power (Instant), Inverter power (Instant) | instantaneous in and out split by sign | `derived.yml` `expr` |
| Calculate car details | per car (index 0 Leaf, 1 Outlander): odometer, km today, range, SOH, charge bars, charge time | km today: `derived.yml` `daily_delta`; rest: `page` |
| Check if charging | car charging when pulse channel 4 power ≥ 200 W | `derived.yml` `expr` |

Midnight resets (cron `00 00`), 9am resets for rain and battery out, a 00:01 email, a
00:05 log backup to `/containermedia/pi/HOMEMONITOR/backup/Input/`.

## 3. The daily email, per site

Mechanism, the same on both branches: at midnight, separate "Midnight reset" function
nodes each append an HTML fragment to `/share/DailyEmail/DailyEmail.txt`. At 00:01 the
file is read back, wrapped by "Add from and topic details" (sender, subject, CSS
background, footer links, "system was restarted" warning) and sent by an e-mail node.
SMTP credentials are in each branch's `flows_cred.json`.

| What | shannstainable (`nodeRed`) | harvey-farm |
|---|---|---|
| Sender, subject | "Shannstainable House Monitor", "28 Shann Street daily house monitor status for …" | "Harvey Farm Monitor", "Harvey Farm daily monitor status for …" |
| Background | wheat | DarkSeaGreen |
| Footer links | shannstainable.fewings.org | harvey.fewings.org and harvey.fewings.org/grafana |
| Recipients | three addresses (in the e-mail node) | two addresses |
| Sections | power, hot water, water, rain tank, dog food, rainfall, batteries, cars | power, water, rain tanks, rainfall, batteries. Hot water, dog food and car fragments are built but not wired to the file |
| Labels | Mains, Hot, Bore; one rain tank | Green tank, Top Tank; two tanks |
| Tank calibration | 460 to 2050 mm | green tank to 2340 mm; top tank from 100 mm |
| Battery channel names | nine, as in section 2 | `Rail, Mid-voltage` |
| Tariff rows | import, export, HWS, car, foregone | commented out |
| Log backup | yesterday's file | two days ago |

Defects found in the harvey-farm copy, to fix or to design out:

- The wrapper adds the whole body twice, once with each footer link.
- The footer prints the Grafana username and password in plain text.
- The rainfall link (and the unwired dog food and hot water links) still point to
  shannstainable.fewings.org.

## 4. enchantee's Node-RED pages (`Enchantee` branch)

| Page | Widgets today | Under this design |
|---|---|---|
| Sailing HUD | custom HTML at `/hud`, polling `/hud/data`; per-value age, 15 s stale | already replaced by the race app at `/race/hud`; `/hud` 302s there. Menu link only |
| Dials Display | 5 gauges, value trail, template | `dial`, `trail` |
| Navigation | text, chart, Grafana iframe | `value`, `trail`, `grafana` |
| Weather | 6 texts, chart, template | `value`, `compass`, `trail` |
| Motor | 5 texts, chart, iframe, template | `value`, `dial`, `grafana` |
| Battery | 4 texts, chart, cell-voltage template | `gauge`, `cell-bar`, `trail` |

The race app's HUD port records the topic meanings (race app DESIGN 3). Note
`anemometer/windDirection/0` is AWA (bow-relative), `/1` is apparent wind as a bearing,
`/2` is true wind direction.

## 5. Other known issues seen along the way

- Topics missing the slash before the subnode: `bms/voltage{n}`, `bms/lifetimeCycles{n}`,
  `sevCon/voltage{n}`, `sevCon/current{n}`, `sevCon/rpm{n}`. event_recorder needs a
  separate `bms/+` line to catch the first.
- event_recorder's enchantee config labels the speed plot "Speed (km/h)"; `gps/speed` is
  in knots according to the race app.
- MQTT publishes rain as a raw tip count; Influx stores mm. Node-RED multiplies by 0.2
  itself.
- Node-RED's HWS "Add title and scale" node has a typo, `msg.paylaod`, for the heat pump.
