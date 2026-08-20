# Flags

Eight hand-written SVGs, about 4 kB in total: four naval numeral flags for the division and
four numeral pendants for the course number. Courses are signalled from the start box by
one of each, so the selection cards show both and the crew matches what is flying rather
than reading text (DESIGN 8).

Named as `courses.json` refers to them: `{"division": "naval-3", "numeral": "pendant-2"}`.

## These designs are provisional and need checking

They are drawn from the International Code of Signals as best I know it, which is not good
enough for something whose whole job is to be matched against a flag on a halyard. Getting
one wrong sends the crew round the wrong course.

The authority is the Fixtures & Courses 2026-2027 PDF in `docs/reference/`. Its text names
the flags only, as "Naval Numeral Flag 3", but the course sheet pages carry the designs as
images, one set per series, and which flag appears on which sheet identifies it: the Sunday
Div III sheet shows naval 3, Div IV shows naval 4, and so on.

To check one, put the PDF page beside the SVG and compare. What matters, in order:

1. **Colours.** Blue, red, yellow and white here are `#14509b`, `#c8102e`, `#ffd200`,
   `#ffffff`.
2. **The arrangement**, which is what the eye actually matches at a distance.
3. The shape: pendants taper, naval numerals are rectangular. That part is certainly right.

Not urgent, and not something to guess at twice: leave them wrong rather than change them
to a different guess. A card that shows the course number in text as well is legible
either way, which is why the selection UI shows both.
