# Running event_recorder on a development machine

For testing Phase 6 (the post editor) on Windows, or anywhere with Docker, against a
replayed sail instead of the boat. Nothing here touches the Pi or enchantee.org.

| Piece | Where it comes from |
|---|---|
| Recorder | `event_recorder_dev` container: the production image's Python 3.11 and package pins, with this checkout bind-mounted over the code |
| Broker | the racing app's replay broker, `enchantee_replay_mqtt`, on 1883 |
| Event triggers | the boat's own, `provisioning/enchantee/config/events/`, mounted read-only |
| Service config | `dev/config/event_recorder_config.yml`: host broker, no WordPress credentials |
| Data | `dev/data/` (git-ignored): the database, plots and uploads |
| A sail | `replay.py` publishing a recorded day into the broker |

Commands below are from `python/event_recorder/` in Git Bash unless they say otherwise.

## Start

```bash
docker compose -f ../enchantee_racing/tests/replay/docker-compose.yml up -d   # broker
docker compose -f dev/docker-compose.yml up -d --build                        # recorder
```

Open <http://localhost:5000>. `docker logs -f event_recorder_dev` shows what it is doing.

## Put a sail through it

From `python/enchantee_racing/`, with the venv that has paho and the built pyemonlib:

```bash
../venv/Scripts/python.exe tests/replay/replay.py tests/data/20260913_Frostbite_1.TXT --speed 60
```

About three minutes. It starts at the mooring, so it fires both of the boat's triggers:
`track_recording` and `anchor_track_recording` start within a few seconds of each other,
and the anchor one stops by itself when the boat is back. `track_recording` waits for 60 s
of stationary GPS that never comes once the replay ends, and stays active until the
recorder restarts, when recovery marks it stopped.

Recordings are stamped with the time they were made, not the log's time, so a 60x replay
is a three-minute recording dated today. Use `--speed 4` or lower when the recording's
times or the wind summary are what is being tested.

## Publish to a local blog

When publishing is what is being tested. A WordPress on <http://localhost:8080>
(wp-admin: admin / admin), on Perth time and with enchantee.org's categories:

```bash
docker compose -f dev/docker-compose.yml --profile wordpress up -d
sh dev/wordpress-setup.sh
```

The script installs the blog, makes an application password, writes it to `dev/.env`
(git-ignored) and recreates the recorder so it picks it up. It is safe to run again.
After that, a recording processed and published from <http://localhost:5000> appears on
the local blog. Without the profile, `dev/.env` is not used and the publisher is off.

To change a post as if in wp-admin, or see what is there:

```bash
cd dev
MSYS_NO_PATHCONV=1 docker compose run --rm -T wpcli wp post list --post_type=post
MSYS_NO_PATHCONV=1 docker compose run --rm -T wpcli wp post update 21 --post_title="Edited"
```

## Preview a post

Process a recording from the dashboard, then open
<http://localhost:5000/preview?id=5> (any recording id). The links at the top switch
between the recording's draft and the two layouts, Track Log (today's post) and Ship's
Log (FR-25). The dashed line is the more-break: the enchantee.org home page shows only
what is above it.

## The event page

<http://localhost:5000/log/> is the page the crew will use from the racing app. With no
`?id=` it opens what FR-28 chooses: the anchor recording if one is running, otherwise
the latest unpublished outing. Open it in two browser windows to see two devices
editing at once. The back link to the racing app only appears at `/race/log/`, which
needs the nginx route this rig does not have yet.

## Run the tests

```bash
MSYS_NO_PATHCONV=1 docker exec -e TZ=UTC -w /app event_recorder_dev \
    python -m pytest event_recorder/tests/test_foreign_keys.py \
                     event_recorder/tests/test_ios12_floor.py \
                     event_recorder/tests/test_recording_service.py \
                     event_recorder/tests/test_publish.py \
                     event_recorder/tests/test_status_split.py \
                     event_recorder/tests/test_post_renderer.py \
                     event_recorder/tests/test_editor_choice.py \
                     event_recorder/tests/test_event_page.py \
                     event_recorder/tests/test_chart_map.py \
                     event_recorder/tests/test_gps_position.py
```

- **`MSYS_NO_PATHCONV=1`** stops Git Bash turning `/app` into a Windows path.
- **`TZ=UTC`**, the image's default. The container itself runs as Australia/Perth, like
  the boat, but `test_gps_position.py` builds its fixture in local time and fails by
  exactly eight hours under any other zone. The fault is in the fixture, not the
  recorder.
- The other files in `tests/` are scripts that need a broker or WordPress, and one calls
  `sys.exit` at import, so they cannot be collected by a pytest run of the directory.

## Editing while it runs

Python changes need `docker restart event_recorder_dev`. `web_ui/` is served from disk
per request, so a browser reload is enough.

## Start again from nothing

```bash
docker compose -f dev/docker-compose.yml down
rm dev/data/recordings.db*      # the database only; plots/ and uploads/ are beside it
```

## Stop

```bash
docker compose -f dev/docker-compose.yml --profile wordpress down   # keeps the blog
docker compose -f dev/docker-compose.yml --profile wordpress down -v  # deletes it too
docker compose -f ../enchantee_racing/tests/replay/docker-compose.yml down
```
