"""Flask routes, static and template serving. Port 5002, behind nginx at /race/.

Skeleton only. Build order (DESIGN 13) reaches this at step 3, porting the HUD and
serving it at /race/hud for a side-by-side comparison against /nodered/hud.

Routes to implement (DESIGN 4):

    GET  /                      race screen
    GET  /hud                   instrument HUD
    GET  /api/state             HUD fields plus race state in one payload
    POST /api/select            {course: "sun4-3"}
    POST /api/timer             {hooter: 10 | 5 | 1 | null}
    POST /api/advance           {dir: +1 | -1}
    POST /api/reset
    PUT  /api/config/{marks|courses|lines}

One GET per 500 ms carries both HUD and race state so every device converges
within half a second.

Constraints that are properties of the deployment, not preferences (CLAUDE.md):

- The app is reached as http://enchantee.local/race/, http://10.42.0.1/race/ and
  http://<current-ip>/race/, and must also work on its own port. Never hardcode a
  host, and emit relative asset URLs, not root-relative ones, or the nginx prefix
  breaks them.
- Plain HTTP, no TLS. No secure-context APIs.
- No internet. Nothing is fetched at runtime; every dependency is vendored.

This module owns all file access. It reads config/ from disk and hands plain data
to engine/, which never touches the filesystem.
"""
