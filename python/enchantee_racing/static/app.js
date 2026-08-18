/*
  Skeleton only. No build step and no framework: this has to be editable from a
  laptop on a jetty (CLAUDE.md).

  Poll one endpoint every 500 ms for both HUD and race state, so a single page can
  show both and every device converges within half a second (DESIGN 4).

  Non-negotiable details:
    - Build the fetch target from the current path, never from a host:
        const base = location.pathname.replace(/\/+$/, "");
      The Pi answers on enchantee.local, 10.42.0.1 and its current DHCP address,
      behind an nginx /race/ prefix and on its own port (CLAUDE.md).
    - Readings arrive as {v, age}. Dim wind and motor past 15 s. Blank distance and
      bearing to `---` past the 5 s position cutoff rather than dimming them: a
      dimmed number still reads as a number in spray (DESIGN 9.5).
    - Elapsed time and the countdown come from the server clock and are never
      blanked by sensor staleness.
    - Keep the screen awake with a hidden looping muted video, started on the first
      tap and restarted on visibilitychange. The Wake Lock API needs a secure
      context and there is no TLS (DESIGN 9.8).
    - Unlock the AudioContext on the first hooter button tap. Audio is primary;
      vibration works on Android and never on iOS (DESIGN 10).
    - Render only. Leg advance and finish detection are the server's, so two
      devices cannot disagree (DESIGN 2).
*/
