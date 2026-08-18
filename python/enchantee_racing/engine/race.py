"""Mode and leg state machine: idle -> prestart -> racing -> finished.

Skeleton only. Build order step 6, driven by replayed tracks before it is driven
by the boat.

Pure functions over (state, position, timestamp, course). No I/O, no clock of its
own, no store access. The whole point is that a recorded track can be fed through
it and the transitions asserted (DESIGN 11).

Rules this must implement, all from DESIGN 11:

Start (11.1)
    Elapsed race time counts from T-0, the gun, not from the boat crossing the
    line: PFSYC races are flying starts and a boat may be ten minutes late and
    still be scored. prestart becomes racing on the clock. An early crossing in
    the minute before the gun is a warning only, never a state change.

Rounding a single mark (11.2)
    Only the current target is tested, never all marks. Arm within 40 m, confirm
    on three consecutive fixes of increasing distance. Do not evaluate when the
    position is stale past the 5 s cutoff or when the mode is not racing. After
    any advance, manual or automatic, suppress auto-advance for 10 s so a
    rounding is not counted twice when consecutive legs share a mark. The 40 m is
    config, not a constant, and gets tuned from replayed tracks.

Gates (11.3)
    One leg, two marks, target the midpoint. Completion is a line crossing
    between the two marks with the projection parameter inside [0, 1], not
    proximity: the gates are 110 m to 206 m wide and the boat passes through the
    middle. Record the side the boat is on when the gate becomes the target and
    look for a sign change away from it, which self-configures the direction.
    Crossing a no_cross_while_racing line that is not the target is a rule
    breach: log it, show a brief non-blocking notice, do not advance, do not nag.

Manual override (11.4)
    Manual advance is authoritative and immediate, overriding any pending
    auto-advance state. When in doubt about a detection rule, choose the version
    that fails to advance: a missed advance costs one tap, a false advance points
    the helm at the wrong buoy.

Finish (11.5) -- the highest-risk logic in the project
    Club Buoy 32A is the outer end of the start/finish line and a mid-course mark
    in most courses, so boats cross the finish line repeatedly while racing.
    Detection is disarmed until the final leg completes and every earlier
    crossing is ignored silently. Once armed, a finish is a sign change away from
    the recorded side with the parameter inside [0, 1] of the 117 m segment.
    Freeze elapsed, switch to finished, publish. Never auto-reset.

Shortened course (11.6)
    A Shorten control arms finish detection immediately regardless of leg index.
    Both meanings of code flag S reduce to that.

Time limits (11.7)
    Held per series in config. Displayed only inside the final thirty minutes. The
    limit passing does not change state; DNF is the race committee's call.

Motor (11.8)
    Show the indicator and treat a turning SevCon as a reason to distrust an
    auto-advance, but do not suppress advance automatically.

Events (11.9)
    Publish every transition with source "auto" or "manual". A season of correct
    auto-advances is the evidence needed to tighten the 40 m threshold, and a
    cluster of manual overrides at one mark points straight at a bad coordinate.
"""
