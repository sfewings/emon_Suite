"""Validate marks, courses and lines. Build order step 2.

Skeleton only.

Note on the layout: CLAUDE.md lists this module as "load and validate", and also
says engine/ must contain no I/O. Both hold if the reading of the file belongs to
app.py and this module validates the already-parsed JSON. Keep it that way, so
course validation stays unit-testable without a filesystem.

What it must enforce:

- Marks are keyed by string id. `number` is a display string and is not unique:
  fourteen numbers are shared by two marks each, and 37 (Deepwater Spit and
  Squadron) and 38 (Bond and Dee Rd) collide inside PFSYC's own courses. Every
  lookup keys on id (CLAUDE.md, DESIGN 6).
- Legs are an ordered list that allows repeats. Club Buoy 32A appears up to four
  times in one course. Course position is a leg index, never a mark identity.
- Every leg targets exactly one mark, except the last, which targets the
  start/finish line. There are no gates and no leg has two marks: Bricklanding
  33A+33B, Smith+Lucky Bay 35A+35B and Mosman 14+13 are pairs of ordinary marks
  that always appear consecutively, one leg each (DESIGN 6). Validation should
  reject a leg carrying more than one mark rather than quietly accept it.
- Rounding lint: the register's rounding column agrees with the PFSYC course
  sheets on all twenty marks, so a leg whose rounding disagrees with its mark's
  registered rounding is almost certainly a transcription error. Flag it
  (DESIGN 6).
- Distance reconciliation: summing leg distances from marks.json must reproduce
  each course sheet's printed distance_nm within about 2 per cent. A course that
  does not reconcile has a leg in the wrong order, a missing leg, or the wrong
  mark. This runs over every course (DESIGN 7).
- `shortened_at` is solved by the same arithmetic against the printed shortened
  distance (DESIGN 11.6).
- Aliases carry the name variants, because the course sheets, the chart and the
  register all name the same mark differently.
"""
