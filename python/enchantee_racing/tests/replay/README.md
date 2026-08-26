# Replaying a recorded race

Replay is the primary test strategy for this project (CLAUDE.md). Line-crossing code is
exactly the kind that looks obviously correct and is not, and a recorded race is the only
honest way to find out. This directory has what is needed to put a recording on a broker
and drive the app with it.

## The loop

```
docker compose -f tests/replay/docker-compose.yml up -d          # broker on 1883
python app.py --broker localhost                                 # app on 5002
python tests/replay/replay.py tests/data/20260816_Frostbite_3.TXT --speed 60
```

Then open <http://localhost:5002/hud>. At 60x a two and a half hour race takes about two
and a half minutes, so the wind swings and the motor panels come and go while you watch.

Stop the broker with `docker compose -f tests/replay/docker-compose.yml down`.

## On the boat's Pi, beside the provisioned stack

The loop above cannot be run as it stands on `enchantee`: the provisioned stack already
holds 1883 and 5002. Both ports move, and the app comes up in a container alongside the
broker rather than from a shell, so the whole rig is one command.

```
REPLAY_MQTT_PORT=1884 REPLAY_APP_PORT=5003 \
  docker compose -f tests/replay/docker-compose.yml --profile app up -d

../venv/bin/python tests/replay/replay.py tests/data/20260816_Frostbite_3.TXT \
  -p 1884 --speed 60
```

Then open <http://enchantee.local:5003/> from a phone or a tablet, which is the point of
running it this way: the deployed copy on <http://enchantee.local/race/> keeps serving the
real broker throughout and is not disturbed.

Bring it down with the profile named, or the app is left running:

```
docker compose -f tests/replay/docker-compose.yml --profile app down
```

`down` without `--profile app` removes the broker and leaves `racing_replay` up, holding
port 5003. That is how compose profiles work rather than a bug, and it is the one thing
about this worth remembering.

### The three things that catch people out

- **`../venv/bin/python`, not `python3`.** On the Pi neither interpreter has both
  dependencies: the system `python3` has Flask but no paho, and `python/venv` has paho but
  no Flask. `replay.py` and `crosscheck.py` need paho, so they need the venv; the tests
  need Flask, so they run under `python3` (HANDOVER.md).
- **`-p 1884` on the replay.** The compose file wires the app to the broker for you, but
  `replay.py` is not in the compose file and still has to be told. Without it the replay
  publishes into the provisioned broker on 1883, which is not harmless: see the comment at
  the top of `docker-compose.yml` for the four things in that stack which react to it.
- **`--url` on the crosscheck.** It defaults to 5002, which is the deployed app, so
  without it you are checking the wrong instance and comparing a replay against live data.

```
../venv/bin/python tests/replay/replay.py tests/data/20260816_Frostbite_3.TXT \
  -p 1884 -x 120 --stop 13:22
../venv/bin/python tests/replay/crosscheck.py tests/data/20260816_Frostbite_3.TXT \
  --at 13:22 --url http://127.0.0.1:5003/api/state
```

That pair takes about 10 s of wall clock and prints `0 of 9 fields disagree`.

### Editing while it runs

The container bind-mounts this checkout over its `/app`, so the image only supplies Python
and its packages and every line being run is the one in the working tree. `static/` edits
are live on the next reload. `templates/` and `config/` are cached by Flask, so those need:

```
docker restart racing_replay
```

That one has cost an hour more than once: a template edit that appears to have done
nothing, on the screen you are staring at.

### Why the app is behind a profile

Without `--profile app` the compose file is exactly the broker it always was, because most
of the time the app is wanted from a shell with `python app.py`, where Ctrl+C and up-arrow
is the fastest edit-and-rerun loop there is. The profile is for when the app is not the
thing being edited: checking a recording, driving a phone at it, or running beside the
provisioned stack as above.

## Useful arguments

| Argument | Effect |
|---|---|
| `--summary` | describe the recording and exit, no broker needed |
| `--speed 60` | 60x, so a minute of race per second |
| `--start 13:25 --stop 13:40` | replay a window, on the log's own clock |
| `--types all` | publish every record type, not just the four the app uses |
| `--progress-seconds 10` | how often to print a position line |

## What is in the Frostbite recording

`tests/data/20260816_Frostbite_3.TXT`, 16 August 2026, 13:02 to 15:38, 55,266 records.
Frostbite Course 3 by its filename, which is the course in `config/courses.json` that
reconciles to 0.0 per cent against its printed distance.

| Record | Rate | Becomes |
|---|---|---|
| `gps/0` | 0.96 Hz | SOG, COG and `gps/position/0` |
| `imu/0` | 0.91 Hz | heading |
| `mwv/0,1,2` | ~0.8 Hz each | apparent bow relative, apparent compass, true |
| `svc/0` | 1.05 Hz | the SevCon panels |
| `bms`, `pth`, `temp1` | low | nothing this app subscribes to, skipped by default |

The SevCon turns from 13:10 to 13:19, which is motoring out to the start, and again from
15:24, which is motoring home. It reads -0.06 rpm for the whole race in between, inside
the 5 rpm deadband, so the motor panels appear at each end of the recording and the wind
panels hold for the two hours between. That is DESIGN 11.8 happening on real data.

## Checking the replay actually landed

```
python tests/replay/replay.py tests/data/20260816_Frostbite_3.TXT -x 120 --stop 13:22
python tests/replay/crosscheck.py tests/data/20260816_Frostbite_3.TXT --at 13:22
```

`crosscheck.py` finds the last record of each kind before the cutoff and asserts the app
is carrying exactly those numbers, the TWA and AWA derivations and the position fix
included. It covers the log file, the C++ `EmonSerial` parse, `emon_mqtt`'s topic
mapping, mosquitto, the subscription, `store.derive` and the served JSON in one command.

It defaults to `/api/state`, which carries position; `--url .../hud/data` checks the HUD
payload alone, which by design does not. Both are served, and `/hud/data` deliberately
keeps the exact shape the Node-RED flow served so the two can be compared field by field.

## Why not emonCSVToMQTT.py

`python/emonCSVToMQTT.py` does this job for the whole emon suite and works. `replay.py`
publishes through the same `emon_mqtt.process_line`, so the topics and payloads are
identical, and differs in three ways that matter for a race:

- **Timing is scheduled against the first record** rather than slept per line.
  Per-line sleeps accumulate the scheduler's error, and across 55,000 records that drift
  is larger than the intervals being reproduced.
- **It prints a progress line every few seconds** instead of one line per record. 55,000
  lines of log drowns the thing being tested.
- **It drains before exiting.** Everything is published at QoS 0, so a process that
  returns straight after its last publish takes the tail with it. This cost an
  afternoon's confusion once: every field on the HUD was close but wrong, which looks
  like a broken calculation and is really data from ten seconds earlier.

Use `emonCSVToMQTT.py` for anything else; use this for a race.

## The pyemonlib build

`replay.py` imports `pyemonlib` from source and its `emonSuite` C++ extension from
`python/pyEmon/build/lib.*-cpython-XY/`, where whoever last built it left it. It is not
installed into this venv. If replay reports it cannot find one for your Python version:

```
cd python/pyEmon && pip install -e .
```

Taking the Python from source and only the compiled part from the build tree is
deliberate: putting the whole build tree on the path would silently use a stale
`emon_mqtt.py` the day someone edits it without rebuilding.

## emon_config.yml

Minimal, and only here because `emon_mqtt` looks up a node name to publish `rssi/<node>`
when a record carries an RSSI suffix, which in this recording is the 1,954 `gps/1`
records. Without it those raise inside `emon_mqtt`, which catches and prints, so this
file exists to keep 1,954 harmless tracebacks off the console. Nothing the app subscribes
to depends on any of it.
