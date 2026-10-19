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

**Phase 0 done. Phase 1 not started.** Nothing outside `docs/emon_live_ui/` and the
pointer in the root `CLAUDE.md` has changed on this branch.

## Machines

### Windows laptop (where this started)

- Repo at `C:\Users\StephenFewings\OneDrive - terra15 technologies\Documents\Home\emon\emon_Suite`,
  inside OneDrive. The sibling `..\emon-node-red` is the Node-RED repository.
- No `node`, no `python` on PATH: use the `py` launcher (`py -3`). Claude Code's
  PowerShell tool intermittently failed to spawn here; the Bash tool worked.
- Good for: `emon_feed`, `emon_live`, the UI engine and page files, docs.
- Not good for: the decoder and its regression test, which need the C++ extension built.

### shannstainable Pi (where this finishes)

- Production checkout `/share/emon_Suite`; development worktree
  `/share/emon_Suite-live` (create it per DESIGN 9.1 on first use, and record it here).
- Node-RED user directory `/share/emon-node-red`, on branch `nodeRed`.
- Compose for the site runs from `provisioning/shannstainable/` in the **production**
  checkout. A dev emon_live container should mount the worktree instead and publish a
  port that is free (5000, 1880, 1883, 3000, 8002, 8086, 9000 and 9443 are taken).
- Recorded serial logs for regression fixtures are in `/share/Input/`.
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
  Wrote DESIGN, PLAN, HANDOVER, INVENTORY; copied `proposal.html`. Not yet pushed.
