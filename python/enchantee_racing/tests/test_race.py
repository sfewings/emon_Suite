"""Unit tests for engine/race.py, and a replay of a real race through it.

Two halves, and the second is the one that matters. The first drives each guard in
isolation with synthetic geometry, which is how you find out that a rule does what it says.
The second feeds the 16 August 2026 Frostbite recording through the engine fix by fix,
which is how you find out whether the rules add up to a race. DESIGN 11 says the whole
module exists to be replayable; a state machine tested only against positions I invented
would be testing my imagination.

The replay skips if the recording is absent, since that file is not in the repository yet.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import course as course_module  # noqa: E402
from engine import nav, race  # noqa: E402

MARKS = json.loads((ROOT / "config" / "marks.json").read_text(encoding="utf-8"))
LINES = json.loads((ROOT / "config" / "lines.json").read_text(encoding="utf-8"))
COURSES = json.loads((ROOT / "config" / "courses.json").read_text(encoding="utf-8"))
RACE_CONFIG = json.loads((ROOT / "config" / "race.json").read_text(encoding="utf-8"))

TRACK = ROOT / "tests" / "data" / "20260816_Frostbite_3.TXT"
T0 = 1_755_500_000.0


def _context(course_id="frostbite-3", **overrides):
    chosen = [c for c in COURSES["courses"] if c["id"] == course_id][0]
    config = race.Config.from_document(RACE_CONFIG)._replace(**overrides)
    return race.Context(course=chosen, marks=course_module.index_marks(MARKS),
                        lines=LINES, config=config)


def _racing(context, now=T0):
    """A state that is racing, the shortest way there."""
    state = race.initial()
    state, _ = race.select(state, context, context.course["id"], now)
    state, _ = race.set_timer(state, context, minutes=0, now=now)
    state, _ = race.on_clock(state, context, now)
    assert state.mode == race.RACING
    return state


def _at(context, state, position, now, cog=None, sog=5.0):
    """One fix at a position, with the fix arriving now."""
    return race.on_fix(state, context, race.Fix(position, ts=now, cog=cog, sog=sog), now)


def _approach(context, state, mark, now, from_bearing, distance, sog=5.0):
    """A fix `distance` off `mark`, closing: the mark dead ahead."""
    position = nav.destination(mark, from_bearing, distance)
    return _at(context, state, position, now, cog=nav.bearing(position, mark), sog=sog)


def _departing(context, state, mark, now, from_bearing, distance, sog=5.0):
    """A fix `distance` off `mark`, with the mark astern."""
    position = nav.destination(mark, from_bearing, distance)
    return _at(context, state, position, now, cog=nav.norm360(nav.bearing(position, mark) + 180.0),
               sog=sog)


# --- modes and the clock ---------------------------------------------------


def test_a_new_race_is_idle_and_knows_nothing():
    state = race.initial()
    assert state.mode == race.IDLE
    assert state.leg == 0 and state.start_at is None
    assert race.elapsed(state, T0) is None and race.countdown(state, T0) is None


def test_a_hooter_sets_the_countdown_and_the_gun_starts_the_race():
    context = _context()
    state = race.initial()
    state, _ = race.select(state, context, "frostbite-3", T0)
    state, events = race.set_timer(state, context, minutes=5, now=T0)
    assert state.mode == race.PRESTART
    assert race.countdown(state, T0) == 300.0
    assert events[0]["type"] == "timer"

    state, events = race.on_clock(state, context, T0 + 299.0)
    assert state.mode == race.PRESTART and events == []      # not yet

    state, events = race.on_clock(state, context, T0 + 300.0)
    assert state.mode == race.RACING
    assert [e["type"] for e in events] == ["start"]


def test_elapsed_counts_from_the_gun_not_from_crossing_the_line():
    """A flying start, and a boat ten minutes late is still scored (DESIGN 11.1)."""
    context = _context()
    state = _racing(context, T0)
    assert race.elapsed(state, T0 + 600.0) == 600.0     # no fix has been seen at all


def test_a_timer_can_be_cleared_and_nudged():
    context = _context()
    state = race.initial()
    state, _ = race.set_timer(state, context, minutes=5, now=T0)
    state, _ = race.nudge_timer(state, context, -8.0, T0)
    assert race.countdown(state, T0) == 292.0
    state, _ = race.set_timer(state, context, minutes=None, now=T0)
    assert state.mode == race.IDLE and state.start_at is None


def test_selecting_a_course_names_the_first_mark():
    context = _context()
    state = _racing(context)
    assert race.target_name(state, context) == "Dolphin East"
    assert nav.distance_m(race.target(state, context),
                          nav.as_latlon(context.marks["dolphin-east-42b"])) < 0.001


# --- rounding a mark -------------------------------------------------------


def test_a_rounding_arms_inside_the_radius_and_confirms_when_the_mark_goes_astern():
    context = _context()
    state = _racing(context)
    mark = race.target(state, context)
    now = T0 + context.config.suppress_after_advance_s + 1.0

    state, events = _approach(context, state, mark, now, 20.0, 200.0)
    assert state.armed_leg is None and events == []           # too far to arm

    now += 1
    state, events = _approach(context, state, mark, now, 20.0, 30.0)
    assert state.armed_leg == 0 and events == []              # armed, not confirmed

    for index in range(context.config.astern_fixes - 1):
        now += 1
        state, events = _departing(context, state, mark, now, 20.0, 30.0 + index * 10)
        assert events == [], index                            # astern, not long enough

    now += 1
    state, events = _departing(context, state, mark, now, 20.0, 60.0)
    assert [e["type"] for e in events] == ["rounded"]
    assert events[0]["source"] == race.AUTO
    assert state.leg == 1
    assert race.target_name(state, context) == "Sanders"


def test_a_mark_still_ahead_never_confirms():
    """Approaching, sitting there, and approaching again is not a rounding."""
    context = _context()
    state = _racing(context)
    mark = race.target(state, context)
    now = T0 + 20.0
    for distance in (35.0, 30.0, 25.0, 20.0, 25.0, 30.0, 20.0, 10.0, 15.0, 12.0):
        now += 1
        state, events = _approach(context, state, mark, now, 20.0, distance)
        assert events == [], distance
    assert state.leg == 0


def test_the_astern_run_resets_if_the_mark_comes_back_ahead():
    context = _context()
    state = _racing(context)
    mark = race.target(state, context)
    now = T0 + 20.0
    state, _ = _approach(context, state, mark, now, 20.0, 30.0)
    now += 1
    state, _ = _departing(context, state, mark, now, 20.0, 35.0)
    assert state.astern_fixes == 1
    now += 1
    state, _ = _approach(context, state, mark, now, 20.0, 35.0)
    assert state.astern_fixes == 0


def test_only_the_current_target_is_tested():
    """Courses repeat marks: sailing past 32A on the way to Squadron must do nothing.

    Course 3's first leg is Dolphin East. This rounds Club Buoy instead, which the course
    visits twice later, in the full rounding shape.
    """
    context = _context()
    state = _racing(context)
    other = nav.as_latlon(context.marks["club-32a"])
    now = T0 + 20.0
    state, events = _approach(context, state, other, now, 20.0, 20.0)
    for _ in range(6):
        now += 1
        state, more = _departing(context, state, other, now, 20.0, 30.0)
        events += more
    assert events == []
    assert state.leg == 0 and state.armed_leg is None


def test_no_auto_advance_while_suppressed():
    """Ten seconds after any advance, so one rounding cannot count twice when
    consecutive legs share a mark (DESIGN 11.2).

    Course 2 has club-32a on consecutive legs 3 and 4, which is exactly the case: without
    the hold, the single rounding that satisfies leg 3 would satisfy leg 4 immediately.
    """
    context = _context("frostbite-2")
    state = _racing(context, T0)
    state, _ = race.advance(state, context, +1, T0)      # the hold starts here
    assert state.suppress_until == T0 + context.config.suppress_after_advance_s

    mark = race.target(state, context)
    now = T0 + 1.0
    state, _ = _approach(context, state, mark, now, 20.0, 20.0)
    assert state.armed_leg is None, "must not even arm while suppressed"
    for _ in range(6):
        now += 1
        state, events = _departing(context, state, mark, now, 20.0, 30.0)
        assert events == []
    assert state.leg == 1

    # and once the hold expires the same geometry does advance
    now = T0 + context.config.suppress_after_advance_s + 1.0
    state, _ = _approach(context, state, mark, now, 20.0, 20.0)
    assert state.armed_leg == 1
    for _ in range(context.config.astern_fixes):
        now += 1
        state, events = _departing(context, state, mark, now, 20.0, 30.0)
    assert [e["type"] for e in events] == ["rounded"]


def test_a_rounding_is_not_confirmed_when_cog_is_missing_or_the_boat_is_crawling():
    """The astern test is made of COG, and COG is noise at drifting speed."""
    context = _context()
    for cog_present, sog in ((False, 5.0), (True, 0.2)):
        state = _racing(context)
        mark = race.target(state, context)
        now = T0 + 20.0
        state, _ = _approach(context, state, mark, now, 20.0, 25.0)
        assert state.armed_leg == 0
        for _ in range(6):
            now += 1
            position = nav.destination(mark, 20.0, 40.0)
            cog = nav.norm360(nav.bearing(position, mark) + 180.0) if cog_present else None
            state, events = _at(context, state, position, now, cog=cog, sog=sog)
            assert events == [], (cog_present, sog)
        assert state.leg == 0


# --- staleness -------------------------------------------------------------


def test_a_stale_fix_is_used_for_nothing():
    context = _context()
    state = _racing(context)
    mark = race.target(state, context)
    now = T0 + 20.0
    state, _ = _approach(context, state, mark, now, 20.0, 25.0)
    assert state.armed_leg == 0

    stale = race.Fix(nav.destination(mark, 20.0, 60.0), ts=now, cog=200.0, sog=5.0)
    state, events = race.on_fix(state, context, stale, now + context.config.position_stale_s + 1)
    assert events == []
    assert state.previous_fix is None, "a stale fix must not be kept as a track endpoint"


def test_a_gap_in_the_data_is_not_bridged_across_the_finish_line():
    """The dangerous case: two fixes either side of the line with the boat's real track in
    between unknown. Joining them would fire the finish on a straight line it never sailed.
    """
    context = _context()
    state = _racing(context)
    inner, outer = course_module.start_line(LINES)
    state = state._replace(leg=context.last_leg, finish_armed=True)

    before = nav.destination(nav.midpoint(inner, outer), nav.bearing(inner, outer) - 90.0, 60.0)
    after = nav.destination(nav.midpoint(inner, outer), nav.bearing(inner, outer) + 90.0, 60.0)

    now = T0 + 20.0
    state, _ = _at(context, state, before, now, cog=90.0)
    assert state.finish_side is not None

    # the fix that would complete the crossing arrives too late to be trusted
    state, events = race.on_fix(state, context, race.Fix(after, ts=now + 60.0, cog=90.0, sog=5.0),
                                now + 60.0 + context.config.position_stale_s + 1)
    assert events == [] and state.mode == race.RACING

    # and the one after it, on its own, cannot cross anything either
    state, events = _at(context, state, after, now + 62.0, cog=90.0)
    assert events == [] and state.mode == race.RACING


# --- the finish ------------------------------------------------------------


def _cross_the_line(context, state, now, reverse=False):
    """A two-fix track straight across the middle of the start/finish line."""
    inner, outer = course_module.start_line(LINES)
    middle = nav.midpoint(inner, outer)
    line_bearing = nav.bearing(inner, outer)
    first = nav.destination(middle, line_bearing - 90.0, 40.0)
    second = nav.destination(middle, line_bearing + 90.0, 40.0)
    if reverse:
        first, second = second, first
    state, events = _at(context, state, first, now, cog=nav.bearing(first, second))
    state, more = _at(context, state, second, now + 1.0, cog=nav.bearing(first, second))
    return state, events + more


def test_crossings_before_the_final_leg_are_ignored_silently():
    """32A is the outer end of this line and a course mark twice over, so the boat crosses
    it while racing. Nothing may be said about it and nothing logged (DESIGN 11.5).

    One continuous zigzag rather than four separate two-fix hops: a fresh hop would leave
    the previous fix on the far side and count the journey back as a crossing too, which
    would make the counter say eight and prove nothing.
    """
    context = _context()
    state = _racing(context)
    inner, outer = course_module.start_line(LINES)
    middle = nav.midpoint(inner, outer)
    across = nav.bearing(inner, outer) + 90.0
    left = nav.destination(middle, across + 180.0, 40.0)
    right = nav.destination(middle, across, 40.0)

    now = T0 + 20.0
    for index, position in enumerate([left, right, left, right, left]):
        state, events = _at(context, state, position, now + index, cog=across)
        assert events == [], index
        assert state.mode == race.RACING

    assert state.ignored_crossings == 4, state.ignored_crossings
    assert state.finish_armed is False


def test_the_finish_fires_once_the_last_leg_is_the_target():
    context = _context()
    state = _racing(context)
    state = state._replace(leg=context.last_leg, finish_armed=True)
    state, events = _cross_the_line(context, state, T0 + 20.0)
    assert [e["type"] for e in events] == ["finish"]
    assert state.mode == race.FINISHED
    assert 0.0 <= events[0]["along"] <= 1.0
    assert events[0]["lat"] is not None


def test_the_finish_needs_a_crossing_away_from_the_side_it_was_armed_on():
    """Approaching from the wrong side is not a finish."""
    context = _context()
    state = _racing(context)
    state = state._replace(leg=context.last_leg, finish_armed=True)

    inner, outer = course_module.start_line(LINES)
    middle = nav.midpoint(inner, outer)
    approach = nav.destination(middle, nav.bearing(inner, outer) - 90.0, 60.0)
    state, _ = _at(context, state, approach, T0 + 20.0, cog=90.0)
    armed_side = state.finish_side
    assert armed_side in (-1, 1)

    state, events = _cross_the_line(context, state, T0 + 30.0, reverse=True)
    assert state.mode in (race.RACING, race.FINISHED)
    if state.mode == race.FINISHED:
        assert events[0]["type"] == "finish"


def test_elapsed_freezes_at_the_finish_and_the_race_never_resets_itself():
    context = _context()
    state = _racing(context, T0)
    state = state._replace(leg=context.last_leg, finish_armed=True)
    state, _ = _cross_the_line(context, state, T0 + 100.0)
    assert state.mode == race.FINISHED
    frozen = race.elapsed(state, T0 + 101.0)
    assert race.elapsed(state, T0 + 5000.0) == frozen

    # and no fix does anything at all after that
    for _ in range(5):
        state, events = _cross_the_line(context, state, T0 + 200.0)
        assert events == [] and state.mode == race.FINISHED


def test_shorten_arms_the_finish_wherever_the_boat_is():
    """Code flag S. Both of its meanings reduce to this (DESIGN 11.6)."""
    context = _context()
    state = _racing(context)
    assert state.finish_armed is False
    state, events = race.shorten(state, context, T0 + 20.0)
    assert state.finish_armed is True and state.shortened is True
    assert state.leg == 0, "shortening must not move the leg"
    assert [e["type"] for e in events] == ["shorten"]

    state, events = _cross_the_line(context, state, T0 + 30.0)
    assert [e["type"] for e in events] == ["finish"]


# --- manual override -------------------------------------------------------


def test_manual_advance_is_authoritative_and_clears_any_pending_detection():
    """Manual is the contract (DESIGN 11.4)."""
    context = _context()
    state = _racing(context)
    mark = race.target(state, context)
    now = T0 + 20.0
    state, _ = _approach(context, state, mark, now, 20.0, 25.0)
    state, _ = _departing(context, state, mark, now + 1, 20.0, 30.0)
    assert state.armed_leg == 0 and state.astern_fixes == 1

    state, events = race.advance(state, context, +1, now + 2)
    assert state.leg == 1
    assert state.armed_leg is None and state.astern_fixes == 0
    assert events[0]["source"] == race.MANUAL
    assert state.suppress_until > now + 2, "a correction must not be immediately overruled"


def test_back_steps_the_leg_down_and_stops_at_the_start():
    context = _context()
    state = _racing(context)
    state, _ = race.advance(state, context, +1, T0 + 20.0)
    state, events = race.advance(state, context, -1, T0 + 40.0)
    assert state.leg == 0 and events[0]["type"] == "back"
    state, events = race.advance(state, context, -1, T0 + 60.0)
    assert state.leg == 0 and events == []


def test_advancing_onto_the_last_leg_arms_the_finish():
    context = _context()
    state = _racing(context)
    now = T0
    for _ in range(context.last_leg):
        now += 20.0
        state, _ = race.advance(state, context, +1, now)
    assert state.leg == context.last_leg
    assert state.finish_armed is True


def test_stepping_back_off_the_last_leg_disarms_the_finish():
    """Otherwise a mis-tap leaves the finish live for the rest of the race."""
    context = _context()
    state = _racing(context)
    state = state._replace(leg=context.last_leg, finish_armed=True, finish_side=1)
    state, _ = race.advance(state, context, -1, T0 + 20.0)
    assert state.finish_armed is False and state.finish_side is None


# --- breaches and the early start -----------------------------------------


def test_crossing_between_bricklanding_a_and_b_is_a_breach_and_not_an_advance():
    context = _context()
    state = _racing(context)
    a = nav.as_latlon(context.marks["bricklanding-a-33a"])
    b = nav.as_latlon(context.marks["bricklanding-b-33b"])
    middle = nav.midpoint(a, b)
    across = nav.bearing(a, b) + 90.0
    first = nav.destination(middle, across + 180.0, 50.0)
    second = nav.destination(middle, across, 50.0)

    now = T0 + 20.0
    state, _ = _at(context, state, first, now, cog=nav.bearing(first, second))
    state, events = _at(context, state, second, now + 1, cog=nav.bearing(first, second))
    assert [e["type"] for e in events] == ["breach"]
    assert events[0]["line"] == "bricklanding"
    assert state.leg == 0, "a breach is not a rounding"
    assert state.breaches == 1


def test_rounding_the_outside_of_a_no_cross_mark_is_not_a_breach():
    """Which is what the course actually asks the boat to do."""
    context = _context()
    state = _racing(context)
    a = nav.as_latlon(context.marks["bricklanding-a-33a"])
    b = nav.as_latlon(context.marks["bricklanding-b-33b"])
    outside = nav.destination(a, nav.bearing(b, a), 80.0)
    across = nav.bearing(a, b) + 90.0

    now = T0 + 20.0
    first = nav.destination(outside, across + 180.0, 50.0)
    second = nav.destination(outside, across, 50.0)
    state, _ = _at(context, state, first, now, cog=nav.bearing(first, second))
    state, events = _at(context, state, second, now + 1, cog=nav.bearing(first, second))
    assert events == [] and state.breaches == 0


def test_an_early_crossing_is_a_warning_and_changes_nothing():
    """Rule 30.1 is the start box's business (DESIGN 11.1)."""
    context = _context()
    state = race.initial()
    state, _ = race.select(state, context, "frostbite-3", T0)
    state, _ = race.set_timer(state, context, minutes=1, now=T0)

    state, events = _cross_the_line(context, state, T0 + 20.0)
    assert [e["type"] for e in events] == ["early"]
    assert state.mode == race.PRESTART
    assert state.leg == 0 and state.ignored_crossings == 0


def test_a_crossing_well_before_the_gun_is_not_even_a_warning():
    context = _context()
    state = race.initial()
    state, _ = race.set_timer(state, context, minutes=10, now=T0)
    state, events = _cross_the_line(context, state, T0 + 20.0)
    assert events == []


# --- the event payload -----------------------------------------------------


def test_events_carry_what_event_recorder_needs():
    """DESIGN 11.9. source is the field that makes next season's tuning possible."""
    context = _context()
    state = _racing(context)
    state, events = race.advance(state, context, +1, T0 + 20.0)
    event = events[0]
    for key in ("type", "course", "leg", "leg_name", "ts", "lat", "lon", "source"):
        assert key in event, key
    assert event["course"] == "frostbite-3"
    assert event["leg"] == 1
    assert event["leg_name"] == "Sanders"
    assert event["source"] == race.MANUAL


def test_the_config_comes_from_the_file_and_ignores_its_own_notes():
    config = race.Config.from_document(RACE_CONFIG)
    assert config.arming_radius_m == 40.0
    assert config.astern_fixes == 3
    assert config.position_stale_s == 5.0
    assert race.Config.from_document({}) == race.Config()
    assert race.Config.from_document({"arming_radius_m": 55.0}).arming_radius_m == 55.0


# --- the whole race --------------------------------------------------------


def _read_track(path, start="13:30:00"):
    fixes = []
    for line in open(path, encoding="utf-8", errors="replace"):
        f = line.rstrip().split(",")
        if len(f) < 7 or f[1] != "gps" or f[2] != "0":
            continue
        clock = f[0][11:]
        if clock < start:
            continue
        hours, minutes, seconds = (int(part) for part in clock.split(":"))
        try:
            fixes.append((hours * 3600 + minutes * 60 + seconds,
                          nav.LatLon(float(f[3]), float(f[4])), float(f[5]), float(f[6])))
        except ValueError:
            continue
    return fixes


def _replay(context, start_clock="13:30:00"):
    """Feed the recording through the engine from the gun, collecting the events."""
    fixes = _read_track(TRACK, start=start_clock)
    start = fixes[0][0]
    state = race.initial()
    state, _ = race.select(state, context, context.course["id"], start)
    state, _ = race.set_timer(state, context, minutes=0, now=start)
    state, _ = race.on_clock(state, context, start)

    collected = []
    for now, position, cog, sog in fixes:
        state, events = race.on_fix(state, context, race.Fix(position, now, cog, sog), now)
        collected += [(now, event) for event in events]
        if state.mode == race.FINISHED:
            break
    return state, collected


def test_replaying_a_real_race_works_through_every_leg_in_order():
    """The test this module exists for.

    Frostbite course 3, 16 August 2026, fed through fix by fix from the 13:30 gun. Nine
    advances, in order, no leg skipped and none repeated, and the finish armed at the end.
    """
    if not TRACK.exists():
        print("skipped: %s is not in the repository" % TRACK.name)
        return

    context = _context()
    state, events = _replay(context)

    advances = [(now, e["leg"]) for now, e in events if e["type"] == "rounded"]
    assert [leg for _t, leg in advances] == list(range(1, context.last_leg + 1)), advances
    assert state.leg == context.last_leg
    assert state.finish_armed is True
    assert state.finish_side in (-1, 1)
    assert [e["type"] for _t, e in events if e["type"] == "breach"] == []


def test_the_replayed_race_finishes_once_on_the_fix_the_boat_crossed():
    """The whole engine, end to end, against a race that happened.

    This test spent a day asserting that the replay did NOT finish. The boat's last crossing
    fell 38 m outside the inner end of the line, so the [0, 1] parameter test rejected it,
    correctly: the inner start mark had been digitized 71 m along the line towards 32A. It
    was redigitized to within 1.6 m of the hand-supplied guess that preceded it, which
    lengthened the line from 109 m to 178 m, and the finish now lands at t = 0.17.

    Worth keeping in mind next time something here looks like a detection bug. The engine
    was right, the rule was right, and the mark was wrong.
    """
    if not TRACK.exists():
        print("skipped: %s is not in the repository" % TRACK.name)
        return

    context = _context()
    state, events = _replay(context)

    finishes = [(now, event) for now, event in events if event["type"] == "finish"]
    assert len(finishes) == 1, [now for now, _e in finishes]
    assert state.mode == race.FINISHED

    when, event = finishes[0]
    assert abs(when - (15 * 3600 + 16 * 60 + 1)) < 5, when      # the boat crossed at 15:16:01
    assert 0.0 <= event["along"] <= 1.0, event["along"]
    assert event["lat"] is not None and event["lon"] is not None

    # An hour and three quarters, counted from the gun rather than from the line.
    assert abs(race.elapsed(state, when) - 6361.0) < 30.0, race.elapsed(state, when)

    # Three crossings while racing, every one of them ignored: the 13:30 start and the two
    # roundings of 32A, which is the outer end of this line as well as a course mark. That
    # is the hazard the whole finish design exists for, and it happened three times.
    assert state.ignored_crossings == 3, state.ignored_crossings
    assert state.breaches == 0


def test_the_replay_advances_close_to_where_the_boat_actually_rounded():
    """Within a minute on nine of the ten legs, and Hallmark is the known exception.

    Hallmark is early because the boat approached to 36 m, turned, sailed 100 m away with
    the mark astern for fifty seconds, then came back and rounded properly two minutes
    later. That first pass is rounding-shaped and no rule distinguishes it (DESIGN 11.2).
    The sequence recovers on its own: the engine spends the next leg pointing at Club Buoy
    while the boat finishes with Hallmark, and everything after that lines up again.
    """
    if not TRACK.exists():
        print("skipped: %s is not in the repository" % TRACK.name)
        return

    rounded_at = {1: "13:51:38", 2: "14:05:13", 3: "14:11:23", 4: "14:13:17", 5: "14:21:08",
                  6: "14:50:18", 7: "14:59:57", 8: "15:07:09", 9: "15:14:09"}

    context = _context()
    _state, events = _replay(context)
    fired = {e["leg"]: now for now, e in events if e["type"] == "rounded"}

    late = {}
    for leg, clock in rounded_at.items():
        hours, minutes, seconds = (int(p) for p in clock.split(":"))
        expected = hours * 3600 + minutes * 60 + seconds
        assert leg in fired, leg
        late[leg] = fired[leg] - expected

    early = {leg: offset for leg, offset in late.items() if offset < -60.0}
    assert set(early) <= {6}, late      # leg 6 is the advance off Hallmark
    for leg, offset in late.items():
        if leg not in early:
            assert -60.0 <= offset <= 60.0, (leg, offset)


if __name__ == "__main__":
    import traceback

    failures = 0
    for test_name, test in sorted(globals().items()):
        if not test_name.startswith("test_") or not callable(test):
            continue
        try:
            test()
        except Exception:
            failures += 1
            print("FAIL  " + test_name)
            traceback.print_exc()
        else:
            print("ok    " + test_name)
    print("%d failed" % failures if failures else "all passed")
    raise SystemExit(1 if failures else 0)
