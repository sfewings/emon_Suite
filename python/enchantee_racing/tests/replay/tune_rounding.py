"""Tune the rounding detection rules against a recorded race. No broker needed.

DESIGN 11.2 says the arming radius is "a starting value, not a fixed constant. Put it in
config and tune it from replayed tracks." This is that tool. It also answers the question
behind it, which is whether the confirmation rule works at all.

    python tests/replay/tune_rounding.py tests/data/20260816_Frostbite_3.TXT frostbite-3

Three things come out of it:

1. Whether the transcribed course matches the one the boat sailed, by walking the legs in
   printed order and checking each target is approached after the one before it. This is
   the strongest check config/courses.json can get: the printed distance validates the
   arithmetic, but only a track validates the order.
2. What the closest approach to each mark actually is, which is the lower bound on the
   arming radius.
3. Where each candidate confirmation rule would fire relative to the real rounding, which
   is the only way to choose between them.

Findings from the 16 August 2026 Frostbite recording are in DESIGN 11.2. The short
version: 40 m misses three of ten roundings, and the three-increasing-fixes rule fires
during a boat milling about in light air.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
sys.path.insert(0, str(PROJECT))

from engine import course, nav  # noqa: E402

DEPARTED_M = 250.0
"""Far enough from a target that the boat is plainly on the next leg, used only to end
one leg's search window and start the next. Not a detection parameter."""


def read_track(path):
    """The gps/0 fixes: (clock, position, cog, sog). Positions and course as recorded."""
    track = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            f = line.rstrip().split(",")
            if len(f) < 7 or f[1] != "gps" or f[2] != "0":
                continue
            try:
                track.append((f[0][11:], nav.LatLon(float(f[3]), float(f[4])),
                              float(f[5]), float(f[6])))
            except ValueError:
                continue
    return track


def load(config_dir):
    marks = json.loads((config_dir / "marks.json").read_text(encoding="utf-8"))
    lines = json.loads((config_dir / "lines.json").read_text(encoding="utf-8"))
    courses = json.loads((config_dir / "courses.json").read_text(encoding="utf-8"))
    return course.index_marks(marks), lines, courses


def walk_legs(track, targets, start_clock):
    """Closest approach to each target in order, each searched after the last one."""
    at = 0
    while at < len(track) and track[at][0] < start_clock:
        at += 1
    out = []
    for target in targets:
        best = best_at = None
        for j in range(at, len(track)):
            d = nav.distance_m(track[j][1], target)
            if best is None or d < best:
                best, best_at = d, j
            elif d > best + DEPARTED_M:
                break
        if best_at is None:
            break
        out.append((best, best_at))
        at = best_at + 1
    return out


def confirm(window, target, radius, rule, margin):
    """Index within `window` where `rule` would confirm a rounding, or None.

    increasing  three consecutive fixes of increasing distance (DESIGN 11.2 as written)
    departed    distance now exceeds the closest since arming by `margin`
    astern      the mark lies abaft the beam for three consecutive fixes
    """
    armed = None
    closest = None
    run = 0
    for k, (_clock, position, cog, _sog) in enumerate(window):
        d = nav.distance_m(position, target)
        if armed is None:
            if d > radius:
                continue
            armed, closest = k, d
            continue
        previous, closest = d, min(closest, d)

        if rule == "increasing":
            run = run + 1 if k and d > nav.distance_m(window[k - 1][1], target) else 0
            if run >= 3:
                return k
        elif rule == "departed":
            if d > closest + margin:
                return k
        elif rule == "astern":
            relative = nav.relative_bearing(nav.bearing(position, target), cog)
            run = run + 1 if abs(relative) > 90.0 else 0
            if run >= 3:
                return k
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file")
    parser.add_argument("course_id")
    parser.add_argument("--start", default="13:30:00", help="race start on the log's clock")
    parser.add_argument("--radius", type=float, default=80.0)
    parser.add_argument("--config", default=str(PROJECT / "config"))
    args = parser.parse_args(argv)

    marks, lines, courses = load(Path(args.config))
    matching = [c for c in courses["courses"] if c["id"] == args.course_id]
    if not matching:
        raise SystemExit("no course %r in courses.json" % args.course_id)
    chosen = matching[0]
    targets = [course.leg_target(leg, marks, lines) for leg in chosen["legs"]]
    names = [course.leg_name(leg, marks) for leg in chosen["legs"]]

    track = read_track(args.file)
    print("%d fixes, %s to %s" % (len(track), track[0][0], track[-1][0]))

    rounded = walk_legs(track, targets, args.start)
    if len(rounded) < len(targets):
        print("only %d of %d legs found: the course or the track is not what we think"
              % (len(rounded), len(targets)))
        return 1

    print("\n=== does the boat sail the course we transcribed? ===")
    print("%-4s %-14s %9s %10s" % ("leg", "target", "closest", "at"))
    for i, (best, best_at) in enumerate(rounded):
        print("%-4d %-14s %8.0f m %10s" % (i, names[i], best, track[best_at][0]))
    clocks = [track[a][0] for _b, a in rounded]
    print("legs approached in printed order: %s" % all(clocks[i] <= clocks[i + 1]
                                                       for i in range(len(clocks) - 1)))
    closest = sorted(b for b, _a in rounded)
    print("closest approach: min %.0f m, median %.0f m, max %.0f m"
          % (closest[0], closest[len(closest) // 2], closest[-1]))

    print("\n=== arming radius: how many roundings would be seen at all? ===")
    for radius in (40.0, 60.0, 80.0, 100.0):
        missed = [names[i] for i, (b, _a) in enumerate(rounded) if b > radius]
        print("%5.0f m  %2d of %d armed%s" % (radius, len(rounded) - len(missed), len(rounded),
                                              "   missed: " + ", ".join(missed) if missed else ""))

    print("\n=== confirmation rules, at radius %.0f m ===" % args.radius)
    print("%-18s %-8s %s" % ("rule", "early", "per leg, fixes from the true rounding"))
    for rule, margin in [("increasing", None), ("departed", 30.0), ("astern", None)]:
        early = 0
        detail = []
        at = 0
        for i, (_best, best_at) in enumerate(rounded):
            window = track[at:min(best_at + 60, len(track))]
            fired = confirm(window, targets[i], args.radius, rule, margin)
            here = best_at - at
            if fired is None:
                detail.append("%s:none" % names[i][:8])
            elif fired < here:
                early += 1
                detail.append("%s:EARLY %d" % (names[i][:8], here - fired))
            else:
                detail.append("%s:+%d" % (names[i][:8], fired - here))
            at = best_at + 1
        label = rule if margin is None else "%s %.0f m" % (rule, margin)
        print("%-18s %-8d %s" % (label, early, ", ".join(detail)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
