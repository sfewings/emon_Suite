"""Mode and leg state machine: idle -> prestart -> racing -> finished.

Pure functions over an immutable state. No I/O, no clock of its own, no store access:
every function takes the state, the fix and the time, and returns a new state and the
events that happened. That is what lets a recorded race be fed through it and the
transitions asserted, which is the whole reason this logic lives here rather than in
Node-RED function nodes (DESIGN 2, 11).

The shape of it:

    state = initial()
    state, events = select(state, context, "frostbite-3", now)
    state, events = set_timer(state, context, minutes=5, now=now)   # a hooter
    state, events = on_clock(state, context, now)                   # prestart -> racing
    state, events = on_fix(state, context, fix, now)                # every GPS fix
    state, events = advance(state, context, +1, now, fix)           # the Next button

on_fix is the only complicated one, and everything it does is guarded. In order: it
refuses to act on a stale fix, it looks for breaches of the two no-cross lines, it tests
the finish line if the finish is armed, and it tests the current target for a rounding if
auto-advance is not suppressed. Nothing else looks at position.

What is deliberately absent:

- Nothing here decides the race is over on time. The time limit is displayed and never
  enforced: whether a boat is DNF is the race committee's call (DESIGN 11.7).
- Nothing here acts on the motor. A turning SevCon is shown, and is a reason for the crew
  to distrust an advance, not a reason for the engine to suppress one (DESIGN 11.8).
- Nothing here resets itself. The crew resets when they are ready (DESIGN 11.5).
- Nothing here adjudicates a recall. An early crossing is a warning and nothing more.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, NamedTuple, Optional, Sequence

from . import course as course_module
from . import nav

IDLE = "idle"
PRESTART = "prestart"
RACING = "racing"
FINISHED = "finished"

AUTO = "auto"
MANUAL = "manual"


class Config(NamedTuple):
    """Detection parameters. config/race.json holds the values and explains each one."""

    arming_radius_m: float = 40.0
    astern_fixes: int = 3
    suppress_after_advance_s: float = 10.0
    position_stale_s: float = 5.0
    min_sog_for_cog_kt: float = 0.7
    early_start_warning_s: float = 60.0

    @classmethod
    def from_document(cls, document: Optional[Mapping[str, Any]]) -> "Config":
        """Take the keys we know from config/race.json, ignore its notes and anything new."""
        document = document or {}
        return cls(**{name: document[name] for name in cls._fields if name in document})


class Context(NamedTuple):
    """Everything static about the race: the course, the marks, the lines, the tuning.

    Built once when a course is selected. Holding it apart from the state keeps the state
    small enough to compare in a test and to log in an event.
    """

    course: Mapping[str, Any]
    marks: Mapping[str, Any]
    lines: Mapping[str, Any]
    config: Config = Config()

    @property
    def legs(self) -> Sequence[Mapping[str, Any]]:
        return self.course["legs"]

    @property
    def last_leg(self) -> int:
        return len(self.legs) - 1


class Fix(NamedTuple):
    """One GPS fix, as the store hands it over."""

    position: nav.LatLon
    ts: float
    cog: Optional[float] = None
    sog: Optional[float] = None


class State(NamedTuple):
    """The whole of the race state. Immutable: every transition returns a new one."""

    mode: str = IDLE
    course_id: Optional[str] = None
    leg: int = 0

    start_at: Optional[float] = None
    """T-0, the gun. Elapsed counts from here whether or not the boat crossed the line,
    because that is how the club scores it and a boat may start ten minutes late and still
    be scored (DESIGN 11.1)."""

    finished_at: Optional[float] = None

    armed_leg: Optional[int] = None
    """Which leg the proximity arming belongs to, so an arming cannot survive an advance."""

    astern_fixes: int = 0
    suppress_until: float = 0.0

    finish_armed: bool = False
    finish_side: Optional[int] = None
    shortened: bool = False

    previous_fix: Optional[nav.LatLon] = None
    """The last usable fix, for the crossing tests. Cleared when position goes stale, so a
    gap in the data cannot be joined into a straight line across the finish."""

    ignored_crossings: int = 0
    """Crossings of the start/finish line before the finish was armed. A debug counter and
    nothing else: they are ignored silently, with no notice and no event (DESIGN 11.5)."""

    breaches: int = 0


def initial() -> State:
    return State()


# --- reading the state -----------------------------------------------------


def elapsed(state: State, now: float) -> Optional[float]:
    """Seconds since the gun, frozen at the finish. None until the gun has gone.

    None rather than a negative number before the start. Elapsed race time and the
    countdown are two different readings on the screen, and handing the front end a
    negative elapsed invites it to render the countdown twice, once as "-0:26" in the
    place the crew looks for how long they have been racing.

    Never blanked by sensor staleness: this comes off the clock, and it stays right when
    the GPS does not (DESIGN 9.5).
    """
    if state.start_at is None:
        return None
    if state.finished_at is not None:
        return state.finished_at - state.start_at
    if now < state.start_at:
        return None
    return now - state.start_at


def countdown(state: State, now: float) -> Optional[float]:
    """Seconds until the gun, negative once it has gone. None if no timer is set."""
    if state.start_at is None:
        return None
    return state.start_at - now


def target(state: State, context: Context):
    """Where the boat is steering, or None once finished."""
    if state.mode == FINISHED or state.leg > context.last_leg:
        return None
    return course_module.leg_target(context.legs[state.leg], context.marks, context.lines)


def target_name(state: State, context: Context) -> Optional[str]:
    if state.mode == FINISHED or state.leg > context.last_leg:
        return None
    return course_module.leg_name(context.legs[state.leg], context.marks)


def is_stale(state: State, context: Context, fix: Fix, now: float) -> bool:
    """Past the cutoff the fix is not used for anything at all (DESIGN 9.5)."""
    return (now - fix.ts) > context.config.position_stale_s


# The thresholds themselves live in course.py now, with the function that uses them.
BEAT_MAX = course_module.BEAT_MAX
CLOSE_HAUL_MAX = BEAT_MAX      # the old name, as in course.py
RUN_MIN = course_module.RUN_MIN


def leg_type(twd: Optional[float], bearing_to_mark: Optional[float]) -> Optional[str]:
    """beat, reach or run for the leg ahead, from norm180(twd - bearing) (DESIGN 3).

    Free, since both numbers are already on the screen, and useful before a rounding
    rather than after it: it is what tells the crew which sail to have ready.

    The arithmetic moved to course.py, which the detail page needs for a course nobody is
    sailing. Kept here as a name because it is part of what this module offers, and
    delegating is cheaper than two copies of a threshold drifting apart.
    """
    return course_module.leg_type(twd, bearing_to_mark)


def navigation(state: State, context: Context, fix: Optional[Fix],
               twd: Optional[float] = None) -> Optional[dict]:
    """Distance and bearing to the current target, or None if it cannot be known.

    None covers every reason the numbers must blank rather than mislead: no course, no
    fix, a fix past the 5 s cutoff, or a finished race. The page shows dashes for all of
    them, because a stale bearing looks exactly like a live one (DESIGN 9.5).

    Distance is metres and the bearing is degrees true. Switching to nautical miles above
    500 m, and formatting, is the front end's business (DESIGN 9.4).
    """
    if fix is None or state.mode == FINISHED:
        return None
    mark = target(state, context)
    if mark is None:
        return None
    bearing = nav.bearing(fix.position, mark)
    payload = {
        "distance_m": nav.distance_m(fix.position, mark),
        "bearing": bearing,
        # Signed, port negative, the same convention as TWA and AWA on the HUD. Shown
        # beside the true bearing rather than instead of it, so the helm reads the delta
        # without arithmetic (DESIGN 9.3).
        "relative": None if fix.cog is None else nav.relative_bearing(bearing, fix.cog),
        "leg_type": leg_type(twd, bearing),
        "next_name": None,
        "next_bearing": None,
        "transit": None,
        "next_leg_type": None,
    }

    # The leg after this one: what it is called, how hard the turn onto it will be, and
    # whether it is a beat, a reach or a run. All three are wanted before the rounding
    # rather than after it, which is the whole point: the transit angle says whether the
    # kite comes down at the mark, the leg type says what goes up instead, and the name is
    # what the trimmer needs to hear next (DESIGN 9.2).
    if state.leg < context.last_leg:
        after = context.legs[state.leg + 1]
        beyond = course_module.leg_target(after, context.marks, context.lines)
        onward = nav.bearing(mark, beyond)
        payload["next_name"] = course_module.leg_name(after, context.marks)
        payload["next_bearing"] = onward
        # Signed to port or starboard, per DESIGN 9.2, and measured from the direction the
        # boat is actually closing on the mark rather than from the leg as drawn. A boat
        # two tacks out is not approaching along the rhumb line, and the turn it will make
        # is the one from where it comes in.
        payload["transit"] = nav.norm180(onward - bearing)
        payload["next_leg_type"] = leg_type(twd, onward)
    return payload


def line_approach(state: State, context: Context, fix: Optional[Fix]) -> Optional[dict]:
    """Distance to the start line and time to reach it, for the pre-start (DESIGN 10).

    Time to line is the number that wins starts: distance to the line divided by the speed
    made good towards it. All the inputs are already here.

    The aim point is the nearest point on the line rather than its middle, because that is
    where a boat actually crosses, and both the distance and the bearing are measured to
    the same point so the two numbers agree with each other.
    """
    if fix is None or state.mode not in (IDLE, PRESTART):
        return None
    inner, outer = course_module.start_line(context.lines)
    projection = nav.project(inner, outer, fix.position)
    along = min(1.0, max(0.0, projection.t))
    aim = nav.destination(inner, nav.bearing(inner, outer),
                          along * nav.distance_m(inner, outer))

    distance = nav.distance_m(fix.position, aim)
    bearing = nav.bearing(fix.position, aim)
    seconds = None
    if fix.cog is not None and fix.sog is not None and fix.sog > 0.0:
        # Speed made good towards the line, not speed through the water: a boat reaching
        # along the line at six knots is not approaching it at all.
        made_good = fix.sog * math.cos(math.radians(nav.norm180(bearing - fix.cog)))
        if made_good > 0.05:
            seconds = distance / (made_good * nav.METRES_PER_NM / 3600.0)
    return {
        "distance_m": distance,
        "bearing": bearing,
        "seconds": seconds,
        "over": nav.side(inner, outer, fix.position) == state.finish_side
        if state.finish_side else None,
    }


# --- commands, all from the crew -------------------------------------------


def select(state: State, context: Context, course_id: str, now: float):
    """Choose a course. Resets the leg, keeps any timer already set, and goes to prestart.

    Prestart even with no timer set, which is what DESIGN 9.6 describes: idle is the course
    selection screen and prestart is the countdown screen. Once a course is chosen the crew
    is in the pre-start, milling about waiting for a hooter, and the countdown simply reads
    dashes until they tap one.

    It also has to be this way round. The hooter buttons live on the prestart screen, so
    leaving the mode at idle after a selection means the only way to reach the buttons that
    start a race is to have already started one.
    """
    new = state._replace(course_id=course_id, leg=0, armed_leg=None, astern_fixes=0,
                         finish_armed=False, finish_side=None, shortened=False,
                         ignored_crossings=0, breaches=0, finished_at=None,
                         mode=PRESTART)
    return new, [_event("select", new, context, now)]


def set_timer(state: State, context: Context, minutes: Optional[float], now: float):
    """Start the countdown from a hooter, or clear it.

    minutes is how long until the gun: 10, 5 or 1 from the three buttons. None puts the
    race back to idle, which is how a mis-tap is undone.
    """
    if minutes is None:
        new = state._replace(mode=IDLE, start_at=None)
        return new, [_event("timer", new, context, now)]
    new = state._replace(mode=PRESTART, start_at=now + minutes * 60.0, finished_at=None)
    return new, [_event("timer", new, context, now)]


def nudge_timer(state: State, context: Context, seconds: float, now: float):
    """Shift T-0. Someone always taps late (DESIGN 10)."""
    if state.start_at is None:
        return state, []
    new = state._replace(start_at=state.start_at + seconds)
    return new, [_event("timer", new, context, now)]


def advance(state: State, context: Context, direction: int, now: float,
            fix: Optional[Fix] = None):
    """Move the leg by hand. Authoritative and immediate (DESIGN 11.4).

    Manual is the contract: this overrides any pending auto-advance state, and suppresses
    auto-advance afterwards for the same hold an automatic advance gets, so the engine
    cannot immediately undo a correction the crew just made.

    Forward off the last leg finishes the race. The last leg is the finish line, so there
    is nowhere further to advance to, and a crew who has crossed the line and not had the
    engine notice needs a way to say so: this is that way, and it is the reason the button
    reads Finish rather than Next mark on that leg (DESIGN 9.6).

    Back off the first leg does nothing here. The screen treats it as a way to the course
    list, which is a view change and not a race command, so the race carries on.
    """
    if state.mode not in (RACING, PRESTART):
        return state, []

    if direction >= 0 and state.leg >= context.last_leg:
        if state.mode != RACING:
            return state, []
        finished = state._replace(mode=FINISHED, finished_at=now)
        return finished, [_event("finish", finished, context, now, fix=fix, source=MANUAL)]

    leg = max(0, min(context.last_leg, state.leg + (1 if direction >= 0 else -1)))
    if leg == state.leg:
        return state, []
    new = _at_leg(state, context, leg, now)
    return new, [_event("rounded" if direction >= 0 else "back", new, context, now,
                        fix=fix, source=MANUAL)]


def shorten(state: State, context: Context, now: float):
    """Code flag S: the next pass through the line ends the race (DESIGN 11.6).

    Both meanings of the flag reduce to this. Arming immediately regardless of leg index
    is the whole point, so it does not touch the leg.
    """
    if state.mode != RACING:
        return state, []
    new = state._replace(shortened=True, finish_armed=True, finish_side=None)
    return new, [_event("shorten", new, context, now)]


def reset(state: State, context: Context, now: float):
    """Back to idle, keeping nothing. Only ever called by the crew."""
    return initial()._replace(course_id=state.course_id), [_event("reset", state, context, now)]


# --- the clock -------------------------------------------------------------


def on_clock(state: State, context: Context, now: float):
    """prestart becomes racing at T-0, on the clock and nothing else.

    Crossing the line is not a required transition: PFSYC races are flying starts, and a
    boat still in the box at the gun is racing whether it likes it or not (DESIGN 11.1).
    """
    if state.mode != PRESTART or state.start_at is None or now < state.start_at:
        return state, []
    new = state._replace(mode=RACING, leg=0, armed_leg=None, astern_fixes=0,
                         suppress_until=0.0, finish_armed=context.last_leg == 0)
    return new, [_event("start", new, context, now)]


# --- every fix -------------------------------------------------------------


def on_fix(state: State, context: Context, fix: Fix, now: float):
    """Evaluate one GPS fix. The only function here that looks at position.

    Order matters: staleness first, because a stale fix must reach none of the rest; then
    breaches, which are informational and never change the leg; then the finish, because a
    finish ends the race and nothing after it should run; then the rounding.
    """
    events = []

    if is_stale(state, context, fix, now):
        # Drop the previous fix as well as ignoring this one. Bridging a gap in the data
        # would draw a straight line between two positions the boat did not sail between,
        # and that line could cross the finish.
        return state._replace(previous_fix=None), events

    if state.mode not in (PRESTART, RACING):
        return state._replace(previous_fix=fix.position), events

    previous = state.previous_fix
    state = state._replace(previous_fix=fix.position)

    if state.mode == PRESTART:
        if previous is None:
            return state, events
        return _check_early_start(state, context, previous, fix, now)

    # Which side of the finish line the boat is on, if the finish is armed and the side is
    # not yet known. Independent of having a previous fix, because arming happens on a leg
    # advance and the next fix after it has to be enough to establish a side.
    state = _note_finish_side(state, context, fix)

    # The crossing tests need two fixes to draw a track segment between. The rounding test
    # does not: it is about where the boat is and which way it is pointing, so it runs on
    # the first fix of a race as well as every one after it.
    if previous is not None:
        state, breach_events = _check_breaches(state, context, previous, fix, now)
        events += breach_events

        state, finish_events = _check_finish(state, context, previous, fix, now)
        events += finish_events
        if state.mode == FINISHED:
            return state, events

    state, rounding_events = _check_rounding(state, context, fix, now)
    return state, events + rounding_events


def _check_early_start(state: State, context: Context, previous, fix: Fix, now: float):
    """Rule 30.1 is the start box's business, not ours (DESIGN 11.1).

    Flagged as a warning inside the last minute and never acted on: no state change, no
    leg change, no attempt to work out whether a recall would follow.
    """
    remaining = countdown(state, now)
    if remaining is None or not (0 <= remaining <= context.config.early_start_warning_s):
        return state, []
    inner, outer = course_module.start_line(context.lines)
    if nav.crossing(inner, outer, previous, fix.position) is None:
        return state, []
    return state, [_event("early", state, context, now, fix=fix)]


def _check_breaches(state: State, context: Context, previous, fix: Fix, now: float):
    """Crossing between Bricklanding A and B, or Smith and Lucky Bay, while racing.

    A rule breach to log and show briefly, never a leg advance and never a nag: the crew
    knows, and the penalty is theirs to take (DESIGN 11.3). Direction is irrelevant, but
    the [0, 1] parameter test is not: rounding the outside of either mark is what the
    course asks for.
    """
    events = []
    for line in context.lines.get("no_cross_lines", []):
        try:
            a, b = (nav.as_latlon(context.marks[m]) for m in line["marks"])
        except KeyError:
            continue
        if nav.crossing(a, b, previous, fix.position) is None:
            continue
        state = state._replace(breaches=state.breaches + 1)
        events.append(_event("breach", state, context, now, fix=fix, line=line["id"]))
    return state, events


def _check_finish(state: State, context: Context, previous, fix: Fix, now: float):
    """The highest-risk logic in the project (DESIGN 11.5).

    Club Buoy 32A is the outer end of this line and a mid-course mark in almost every
    course, so a boat crosses the finish line repeatedly while racing. Every crossing
    before the finish is armed is ignored silently and counted for debugging only.
    """
    inner, outer = course_module.start_line(context.lines)

    if not state.finish_armed:
        if nav.crossing(inner, outer, previous, fix.position) is not None:
            state = state._replace(ignored_crossings=state.ignored_crossings + 1)
        return state, []

    if state.finish_side is None:
        return state, []            # no side established yet, so no sign change to detect

    crossing = nav.crossing(inner, outer, previous, fix.position)
    if crossing is None or crossing.from_side != state.finish_side:
        return state, []

    finished = state._replace(mode=FINISHED, finished_at=now)
    return finished, [_event("finish", finished, context, now, fix=fix,
                             at=crossing.at, along=crossing.t)]


def _note_finish_side(state: State, context: Context, fix: Fix) -> State:
    """Record which side of the finish line the boat is on, once, after arming.

    side() answers 0 both for a boat sitting exactly on the line and for a position that is
    not finite, and 0 is not a side: nothing is a sign change away from it, so keep waiting
    for a fix that gives a real answer rather than storing the 0.
    """
    if not state.finish_armed or state.finish_side is not None:
        return state
    inner, outer = course_module.start_line(context.lines)
    here = nav.side(inner, outer, fix.position)
    return state._replace(finish_side=here) if here else state


def _check_rounding(state: State, context: Context, fix: Fix, now: float):
    """Auto-advance, with every guard DESIGN 11.2 asks for.

    Only the current target is ever tested. Courses repeat marks, and a proximity test
    against all of them fires when the boat sails past 32A on the way to Squadron.
    """
    if now < state.suppress_until:
        return state, []
    if state.leg >= context.last_leg:
        return state, []            # the last leg is the finish, and that is a crossing

    leg = context.legs[state.leg]
    mark = course_module.leg_target(leg, context.marks, context.lines)
    distance = nav.distance_m(fix.position, mark)

    if state.armed_leg != state.leg:
        if distance > context.config.arming_radius_m:
            return state, []
        return state._replace(armed_leg=state.leg, astern_fixes=0), []

    # Confirmed by the mark passing astern, not by the distance growing. A boat milling
    # about near a mark in light air produces runs of increasing distance that look
    # exactly like a departure; a mark that has gone behind you has been rounded.
    if fix.cog is None:
        return state, []
    if fix.sog is not None and fix.sog < context.config.min_sog_for_cog_kt:
        # COG is noise at this speed, and the astern test is made of COG. Decline rather
        # than guess: a missed advance costs one tap (DESIGN 11.4).
        return state._replace(astern_fixes=0), []

    relative = nav.relative_bearing(nav.bearing(fix.position, mark), fix.cog)
    if abs(relative) <= 90.0:
        return state._replace(astern_fixes=0), []

    astern = state.astern_fixes + 1
    if astern < context.config.astern_fixes:
        return state._replace(astern_fixes=astern), []

    rounded = _at_leg(state, context, state.leg + 1, now)
    return rounded, [_event("rounded", rounded, context, now, fix=fix, source=AUTO)]


# --- helpers ---------------------------------------------------------------


def _at_leg(state: State, context: Context, leg: int, now: float) -> State:
    """Move to a leg, clearing the detection state that belonged to the old one.

    Arming a leg then advancing must not leave the arming behind, or the next leg starts
    half detected. The suppression hold applies to manual advances too, so the engine
    cannot immediately overrule a correction the crew just made.
    """
    finish_armed = state.shortened or leg >= context.last_leg
    return state._replace(
        leg=leg,
        armed_leg=None,
        astern_fixes=0,
        suppress_until=now + context.config.suppress_after_advance_s,
        finish_armed=finish_armed,
        finish_side=state.finish_side if finish_armed == state.finish_armed else None,
    )


def _event(kind: str, state: State, context: Context, now: float,
           fix: Optional[Fix] = None, source: str = AUTO, **extra) -> dict:
    """One race/event payload, for event_recorder to log (DESIGN 11.9).

    source matters more than it looks: a season of races where auto-advance fired and was
    not overridden is the evidence needed to tune the arming radius, and a cluster of
    manual overrides at one mark points straight at a bad coordinate.
    """
    event = {
        "type": kind,
        "course": state.course_id,
        "leg": state.leg,
        "leg_name": target_name(state, context),
        "ts": now,
        "lat": fix.position.lat if fix else None,
        "lon": fix.position.lon if fix else None,
        "source": source,
    }
    event.update(extra)
    return event
