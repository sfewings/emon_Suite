# Flags

Eight hand-written SVGs, about 4 kB in total: four naval numeral flags for the division and
four numeral pendants for the course number. Courses are signalled from the start box by
one of each, so the selection cards show both and the crew matches what is flying rather
than reading text (DESIGN 8).

Named as `courses.json` refers to them: `{"division": "naval-3", "numeral": "pendant-2"}`.

## Checked against the club's own plate

The eight were drawn from the International Code of Signals as best I knew it, and five of
them were wrong. They have now been checked against **page 27 of the Fixtures & Courses
2026-2027 PDF** in `docs/reference/`, which is a plate captioned "NAVAL NUMERAL FLAGS" and
"NUMERAL PENDANTS" showing all ten of each. That page is the authority: it is the club's
own document, it shows the designs rather than naming them, and it is on disk.

To check one, render that page and put it beside the SVG:

```
python - <<'PY'
import pymupdf
doc = pymupdf.open("docs/reference/Sailing Fixtures & Courses 2026 - 2027.pdf")
doc[26].get_pixmap(dpi=600, clip=pymupdf.Rect(80, 55, 330, 172)).save("naval.png")
doc[26].get_pixmap(dpi=600, clip=pymupdf.Rect(465, 50, 640, 330)).save("pendants.png")
PY
```

What the plate shows, and what is now drawn:

| File          | Design                                     | Was                          |
| ------------- | ------------------------------------------ | ---------------------------- |
| `naval-1`     | red / yellow / red horizontal thirds       | red and white vertical halves |
| `naval-2`     | yellow / red / yellow horizontal thirds    | white / blue / white          |
| `naval-3`     | blue / red / blue horizontal thirds        | yellow / blue / yellow        |
| `naval-4`     | red field, white saltire                   | a red and white checkerboard  |
| `pendant-1`   | white, red disc near the hoist             | correct already               |
| `pendant-2`   | blue, white disc near the hoist            | correct already               |
| `pendant-3`   | red / white / blue **vertical** thirds     | the same three horizontal     |
| `pendant-4`   | red, white Nordic cross                    | correct already               |

The three bands on the naval flags measure 21 / 19 / 18 per cent of the height on the
plate, which is equal thirds within the accuracy of a scan, so equal thirds is what is
drawn. Naval 5 to 0 and pendants 5 to 0 exist on the plate but are not drawn here, because
no series in `courses.json` flies them.

Two deliberate departures from the plate:

- **Pendant 3 is drawn as equal thirds**, where the plate measures roughly 31 / 27 / 42.
  A tapering pendant makes the fly end look longer than it is, and the specification is
  three equal stripes; the plate's own drawing is the odd one out.
- **The palette is kept**: blue `#14509b`, red `#c8102e`, yellow `#ffd200`, white
  `#ffffff`. The plate samples as `#0c4978`, `#c50844` and `#fde30a`, which are the
  print reproduction rather than the specified colours, and are close enough that nothing
  matched at a distance would be misled either way.

## What is still not verified

The **shape** of the pendant taper, and the exact size and position of the discs and the
cross, are eyeballed from the plate rather than measured. They are recognisable, which is
the whole job, but nobody has held a ruler to them.

`tests/test_race_screen.py` pins each design, so a later edit that changes an arrangement
fails rather than quietly shipping. If a flag is ever found wrong again, change the SVG and
the test together, and record it in the table above.
