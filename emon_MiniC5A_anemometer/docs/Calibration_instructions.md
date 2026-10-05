# Calibrating the emon_MiniC5A_anemometer compass

Four things need calibrating. They are independent and each has its own procedure.

| What | Where | How often | Script |
|---|---|---|---|
| 1. Gyro offsets | bench | when the sensor is replaced | `calibrate4.py` |
| 2. Accelerometer | bench | when the sensor is replaced | `calibrate4.py` |
| 3. Magnetometer, sensor | bench | when the sensor is replaced | `calibrate4.py` |
| 4. Magnetometer, boat | afloat | after anything metal moves aboard | `calibrate_insitu.py` |
| 5. Heading offset | afloat | **every time 3 or 4 changes** | either script |
| 6. Anemometer offset | afloat | rarely | analysis of a sail log |

Steps 1–3 are one bench session. Step 4 is five minutes of motoring. Do them in
order: a bad accelerometer corrupts everything downstream.

---

## 1–3. Bench calibration

Corrects the **sensor**. Cannot see the boat's magnetism.

### Configure the sketch

In `setup()`, uncomment:

```cpp
collectDataForMahonyCalibration();
```

Flash, and open the serial monitor at **9600 baud**.

### Collect

Send `4` to run all three phases.

**Phase 1, gyro.** Put the unit on a solid surface. Do not touch it. Press a key.

**Phase 2, accelerometer.** Twelve orientations, prompted one at a time. Hold each
one still — it waits until the unit stops moving before sampling.

- 0–5 are the six faces: +Z up, −Z up, +X up, −X up, +Y up, −Y up
- 6–11 are tilted ~45°, four component-side-up and two component-side-down

**Order does not matter, and neither do exact angles.** The claimed orientation is
never used. The prompts exist only to get good coverage. What matters:

- all six faces must appear, or that axis is unconstrained
- no two positions the same
- get through all twelve without a long break — the zero-g offset drifts with
  temperature and the fit assumes it is constant

**Phase 3, magnetometer.** Turn the unit slowly through all three axes for 60 s.
Include turning it fully over, or the Z terms stay unconstrained.

Keep the bench clear of steel, magnets, speakers and laptops, and do not move the unit
to a different spot between positions — the field varies across a room.

### Process

Save the whole serial session to `Captures/capture.txt`, then:

```
python calibrate4.py
```

It reads `Captures/capture.txt` by default; pass a path for anything else.

### Check before pasting

Every section must say PASS. The one that matters is the **dip cross-check**: the
angle between gravity and the field must read the same at every orientation.

- spread under 1.0° → good
- it names the worst orientation if one is off
- it will not hand over constants that fail

### Update the sketch

Paste the printed `GyroOffset`, `A_B`, `A_Ainv`, `M_B`, `M_Ainv` blocks. Re-comment
`collectDataForMahonyCalibration()`. Flash.

---

## 4. In-situ calibration

Corrects the **boat's** magnetism, which the bench never saw. Needs no firmware change.

### Why it is a separate script

`calibrate4.py` fits a 3D ellipsoid and needs every attitude. A boat cannot do that:
turning in yaw sweeps the field around a cone, never a sphere, so the vertical terms
are never excited. Fed boat data it returns nonsense for them and correctly fails.

`calibrate_insitu.py` fits only the horizontal plane and keeps the vertical terms from
the bench. That is well determined by yaw-only data and is the part that moves heading.

### On the boat

At the start of any sail, **motor two slow circles**:

- under power, **3+ knots**, flat water
- steady rate of turn, roughly 60–90 s per circle
- clear of moored steel boats, jetties, bridges
- nothing ferrous moved on deck during them

That is it. One circle is enough; two is insurance.

### Process

```
python calibrate_insitu.py <log.TXT>
```

Add `--from 13:00 --to 13:10` to restrict to the circles, `--plot` to see them.
It reads the live constants straight out of the `.ino`, so they cannot drift out of step.

### Check before pasting

- circles found, and **11 of 12** heading bins covered
- mean tilt under 12°
- circularity should drop sharply, e.g. 25% → 2%
- **it prints nothing to paste unless the error against GPS course actually improved**

### Update the sketch

Paste the new `M_B` and `M_Ainv`. Only the horizontal terms change; the Z row and
column carry over from the bench. Then set `INSTALATION_HEADING_OFFSET` to the value
it prints — see below. Flash.

---

## 5. Heading offset

`INSTALATION_HEADING_OFFSET` is how far the sensor board's X axis is rotated from the
boat's centreline. It is subtracted from the computed heading.

**It must be re-measured whenever `M_B` changes.** Changing the magnetometer
calibration shifts the heading by a heading-dependent amount, so the old constant will
be wrong. `calibrate_insitu.py` prints the new value alongside the new `M_B`; update
the two together.

This is a real trap: 12 was correct on 16 Aug, then the bench recalibration made the
right value 7. Nothing was wrong with either measurement.

---

## 6. Anemometer offset

`ANEMOMETER_HEADING_OFFSET` is how far the vane's zero is rotated from the centreline.
It shifts apparent and true wind without touching the boat-relative reading on
subnode 0. Currently 0, and confirmed correct.

Symptom that it is wrong: a **tack-to-tack split** in true wind direction — the same
breeze reading differently on port and starboard.

**Measure that split inside 5-minute windows, never pooled over a whole sail.** Pooling
turns a wind shift into a fake split. On 23 Aug the breeze veered 60° and the pooled
figure read +5.5° when the real one was zero.

Before blaming the vane, check the compass. A heading error also flips sense with tack.
On 16 Aug a 7.1° split came entirely from the compass; fixing `M_B` took it to 0.05°.

---

## What good looks like

From the 23 Aug sail, after the bench recalibration:

| | 16 Aug, old | 23 Aug, new |
|---|---|---|
| compass error peak-to-peak | 30.7° | 8.8° |
| dip swing with heading | 3.63° | 1.84° |
| dip scatter | 3.87° | 2.15° |

Heading is now good to roughly ±4°.

---

## Collecting a log that is actually usable

The 23 Aug sail could not pin down the deviation curve, because:

- only **28 of 36** ten-degree heading bins were sailed, nothing at 0–29° or 90–119°
- one bin held **32%** of the data
- mean speed 3.2 kt, which makes GPS course noisy
- only 7% under power, so the leeway-free subset was too small to cross-check

**Two slow circles under power at the start fixes all of this at once.** Ten minutes
buys full 360° coverage, leeway-free, in one place — worth more than two hours of
reaching.

---

## Troubleshooting

**"FAIL: only N usable orientations"** — the unit moved while sampling. Rest it
against something rather than holding it.

**"coverage: POOR, −X never reached full scale"** — a face was skipped or done twice.

**"ONE BAD ORIENTATION"** — something magnetic was near the unit for that position, or
it moved. The script names which one.

**"worst direction gap 109° toward −Z"** — the phase 3 sweep never turned the unit
over.

**"fit is a hyperbola"** — the circle was not completed.

**"NO IMPROVEMENT"** — usually no circles in the log, so the fit ran on ordinary
sailing, where leeway masquerades as compass error.

**Dip mean off IGRF by 1–2°** — normal, and largely harmless. It costs nothing while
level and under 1° at the heel you sail. Local field anomalies of a degree or two are
routine, so part of it may not be an instrument error at all. Do not tune to it.
