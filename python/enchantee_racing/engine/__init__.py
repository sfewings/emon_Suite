"""Race engine: pure functions over position, time and course.

No I/O lives in this package. It takes a position, a timestamp and a course and
returns state, which is what makes replay against recorded GPS tracks possible
(CLAUDE.md, DESIGN section 2).
"""
