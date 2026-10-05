# Captures

Provenance for the calibration constants in `emon_MiniC5A_anemometer.ino`.
Two different kinds of file live here.

## Bench captures — input to `calibrate4.py`

Serial sessions from `collectDataForMahonyCalibration()`. Tagged `G`, `A` and `M`
records with the prompts left in.

| file | result |
|---|---|
| `capture.txt` | all four checks PASS. **This produced the current `GyroOffset`, `A_B`, `A_Ainv`, `M_B`, `M_Ainv`.** |

`calibrate4.py` reads `capture.txt` by default:

```
python calibrate4.py
```

An earlier attempt from the same evening is not kept. Its magnetometer sweep never
turned the unit over, so it failed on a 109° coverage gap and a 5.12° dip spread
against the 0.72° this one achieved.

## Sail logs — input to `calibrate_insitu.py`

Ordinary `imu` and `gps` telemetry, no `G`/`A`/`M` records. Used to correct for the
boat's own magnetism, which a bench capture cannot see.

| file | contents |
|---|---|
| `20261003.TXT` | 3 Oct sail. Three full circles under power at 14:17, 14:23 and 14:32, 12/12 heading bins, 4° mean tilt. |

```
python calibrate_insitu.py Captures/20261003.TXT
```

See `../docs/Calibration_instructions.md` for the whole procedure.
