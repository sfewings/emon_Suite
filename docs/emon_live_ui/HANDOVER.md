# emon live UI redesign: handover

Written so that a fresh Claude Code session, on any machine, can pick this work up after
one read. It records **state**: where the work is, what is open, what only runs where.
It does not repeat the design (`DESIGN.md`) or the task list (`PLAN.md`).

Work on this branch is intermittent, possibly months between sessions, and moves from the
Windows laptop where it started to the shannstainable Raspberry Pi where it finishes.
Assume the previous session's context is gone. Everything that matters is in these four
files and the git history.

## Start of every session

1. Confirm where you are. On a Pi, **never** work in `/share/emon_Suite` itself, which is
   production; use the worktree (DESIGN 9.1).
   ```bash
   git -C /share/emon_Suite-live branch --show-current   # expect emon_live_ui
   git -C /share/emon_Suite-live pull
   ```
2. Read, in order: the root `CLAUDE.md` (container mounts, the 27-Sep-2026 deletion),
   this file, `PLAN.md`, then the `DESIGN.md` sections the next task cites.
3. Merge `master` into the branch if it has moved, so the branch never drifts far:
   `git merge origin/master`. Resolve, run the tests, commit.
4. Pick the first unticked task in `PLAN.md`. Each is sized for one session.

## End of every session

1. Tick the task in `PLAN.md`.
2. Add a dated line to the session log below: what was done, on which machine, anything
   left half-done, and anything learned that the design did not foresee.
3. If a decision changed, edit `DESIGN.md` and say so in the log. Do not leave a
   decision only in a commit message.
4. Commit with the docs in the same commit as the work, then **push**. An unpushed
   commit on a laptop is invisible to the Pi.

## Where it is up to

**Phase 1 code done (1a to 1d); 1e, deploying, is next and needs the Pi.** Nothing is
deployed. Nothing outside `python/pyEmon/` and these docs has changed on this branch, so
merging it would change no running container until images are rebuilt.

What exists, all in `python/pyEmon/`:

| File | What |
|---|---|
| `pyemonlib/emon_feed.py` | Reading, envelope, parse, Catalogue, Store, the shared maths. Stdlib only. |
| `pyemonlib/emon_decoder.py` | `decode(line, settings) -> [Emission]` for all 18 payload types |
| `pyemonlib/sink_mqtt.py`, `sink_influx.py` | the two sinks |
| `pyemonlib/emon_mqtt.py`, `emon_influx.py` | now shims over the above, same interfaces |
| `tests/legacy/` | the old two modules verbatim: the regression oracle. Never edit. |
| `tests/test_emon_feed.py` | 40 tests, need only pytest |
| `tests/test_decoder_regression.py` | old vs new for every site config; skipped without the extension |
| `tests/data/` | `emonlog_sample.txt` fixture and the script that makes it |

Behaviour changes a deploy will bring, both switchable per container:

- `emon/...` envelopes (retained) and `emon/config` are published. `EMON_ENVELOPES=0` off.
- Legacy MQTT topics of channels named Unused are no longer published (owner's decision).
  `EMON_SKIP_UNUSED=0` restores them. Influx unchanged.

## Machines

### Windows laptop (where this started)

- Repo at `C:\Users\StephenFewings\OneDrive - terra15 technologies\Documents\Home\emon\emon_Suite`,
  inside OneDrive. The sibling `..\emon-node-red` is the Node-RED repository.
- No `node`, no `python` on PATH: use the `py` launcher (`py -3`). Claude Code's
  PowerShell tool intermittently failed to spawn here; the Bash tool worked.
- Good for everything except deploying. The decoder regression test runs here too: the
  `pyEmon/dist` folder has a cp314 win_amd64 wheel matching this laptop's Python 3.14.
- Test setup used on 19 Oct 2026 (a throwaway venv outside the repo):
  ```bash
  py -3 -m venv <scratch>/venv
  <scratch>/venv/Scripts/python -m pip install pytest paho-mqtt influxdb-client pyyaml numpy pytz       python/pyEmon/dist/pyemonlib-0.1.0-cp314-cp314-win_amd64.whl
  cd python/pyEmon && <scratch>/venv/Scripts/python -m pytest -q tests
  ```
  Run pytest from `python/pyEmon`, not from inside `pyemonlib`; `tests/conftest.py` uses
  the source and borrows the compiled extension from the installed wheel. Expect 78 passed.

### shannstainable Pi (where this finishes)

- Production checkout `/share/emon_Suite`; development worktree
  `/share/emon_Suite-live` (create it per DESIGN 9.1 on first use, and record it here).
- Node-RED user directory `/share/emon-node-red`, on branch `nodeRed`.
- Compose for the site runs from `provisioning/shannstainable/` in the **production**
  checkout. A dev emon_live container should mount the worktree instead and publish a
  port that is free (5000, 1880, 1883, 3000, 8002, 8086, 9000 and 9443 are taken).
- Recorded serial logs for regression fixtures are in `/share/Input/`. The owner will
  supply a shannstainable sample; see PLAN 1c.
- Tests: install the Pi's arm wheel and the same packages into a venv, then as above.
- Test publishers against a separate mosquitto, never the live one (DESIGN 9.2).

### enchantee Pi (the boat)

- Only for phase 3 checks and deploys. Its own conventions are in the root `CLAUDE.md`
  and `python/enchantee_racing/CLAUDE.md`. The iPad mini 3 (iOS 12) is the browser floor.

## Open questions

- Whether the "export" estimate in Node-RED (inverter 2 output minus average night-time
  import) is worth carrying into `derived.yml` or should be replaced with something
  simpler. Decide in PLAN 2b with a day of numbers side by side.
- Whether month and year rainfall should come from an Influx query in emon_live or stay
  with Node-RED's text files. PLAN 2b.
- Whether a `daily_max` operator is needed for battery mid-point voltages, or whether
  that stays in Node-RED. PLAN 2b.

## Session log

- **2026-10-19, Windows laptop.** Design agreed (proposal revision 3, decisions D1 to D6
  confirmed by the owner). Branch `emon_live_ui` created from `master` at `5fc8975`.
  Wrote DESIGN, PLAN, HANDOVER, INVENTORY; copied `proposal.html`.
- **2026-10-19, Windows laptop, later the same day.** Phase 1a to 1d built and tested.
  Learned while building, now in DESIGN 4.1, 4.2 and 5: the two old publishers differ in
  layout, scaling, order and failure point far more than expected, hence the Emission
  design; the topic layout became `emon/<node>/<sub>/<field>[/<idx>]` because one node
  publishes several quantities of a kind; RSSI names carry the node type because
  shannstainable has a `Kitchen` display and a `Kitchen` air sensor. Owner decided: no
  legacy MQTT for channels named Unused; synthetic house data until they supply a log.
  Regression: 20,674 MQTT publishes and 9,318 Influx points identical across 12 configs.
  Branch not yet pushed.
