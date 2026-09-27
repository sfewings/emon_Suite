# emon_Suite

The monitoring and control suite that runs on the boat's Raspberry Pi, `enchantee`.
This file covers the machine every subproject shares. The subprojects carry their own:

- `python/enchantee_racing/CLAUDE.md` the race support app
- `python/event_recorder/CLAUDE.md` the recorder and its WordPress publishing

## This checkout IS the deployment

There is no build-and-ship step for most of the stack. The Docker containers bind-mount
directories out of this working tree and run them live, so editing a file here changes
what is running now. That is deliberate (a laptop on a jetty has to be able to fix
things), and it means the working tree is production.

Two consequences:

- Prefer `git stash` or a branch over editing to "try something", and restart the
  affected container rather than assuming a change took effect.
- The Pi's backup story is this working tree plus whatever has been pushed. Push.

## Container filesystems are NOT isolated from the host

**Every running container has a read-write bind mount out of this host.** Two of them
mount `/share` at the *identical path*:

| container | host | in container |
|---|---|---|
| `node_red` | `/share` | `/share` |
| `emon_logtojson` | `/share` | `/share` |
| `enchantee_racing` | `/share/emon_Suite/python/enchantee_racing` | `/app` |
| `event_recorder` | `/share/emon_Suite/provisioning/enchantee/{config,data}` | `/config`, `/data` |
| `emon_log`, `emon_gpsd` | `/share/Input` | `/share/Input` |
| `emon_serial` | `/share/Output` | `/share/Output` |

`docker inspect <name> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} rw={{.RW}}{{println}}{{end}}'`
is the authoritative list. Run it before writing to any container path.

The identical-path mounts are the trap. Inside `node_red`, `/share/emon_Suite` is not a
container copy of anything. It is this repository, and a write or a delete there lands on
the host as root. On 27-Sep-2026 a `docker exec node_red sh -c "rm -rf /share/emon_Suite"`,
run as cleanup for a directory the session wrongly believed it had created inside the
container, deleted the whole checkout. Tracked files came back from git; five untracked
ones, including a recorded track fixture, did not.

So:

- **Container scratch work goes in `/tmp` inside the container, never under `/share`.**
  `docker cp` the input in, write the output to `/tmp`, `docker cp` it back out.
- **Never run a recursive delete against a container path.** If something under `/tmp`
  in a container needs clearing, name the files.
- `docker exec` runs as root and escapes host-level path protection entirely, so it is
  not covered by anything that guards the Bash tool. It is deliberately not on the
  permission allowlist in `.claude/settings.local.json`; leave it off.

## Using a container as a runtime

There is no `node` on the Pi. `node_red` has one (v20), and reaching for it is reasonable,
but only ever on container-local paths:

```bash
docker cp script.js node_red:/tmp/script.js
docker cp input.js  node_red:/tmp/input.js     # have the script read /tmp/input.js
docker exec node_red node /tmp/script.js
```

Python 3 is on the host. `jq` is not.
