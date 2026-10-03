#!/usr/bin/env python3
"""
calibrate4.py - process a calibration capture from emon_MiniC5A_anemometer.ino
and emit paste-ready GyroOffset, A_B, A_Ainv, M_B and M_Ainv blocks.

    python calibrate4.py [capture.txt] [--dip 66.1] [--plot]

Capture the whole serial session from collectDataForMahonyCalibration() to a text file.
With no filename it reads Captures/capture.txt next to this script, so the usual
workflow is to paste the session into that file and just run the script.

Phases may be captured separately and concatenated, and any phase that is missing is
simply skipped. Everything that is not a G, A or M record is ignored, so the sketch's
banners, prompts and ordinary telemetry can be left in place.

Requires numpy only. matplotlib is used solely by --plot. Unlike calibrate3.py this
does NOT need scipy: the only scipy call was sqrtm() of a symmetric positive-definite
matrix, which is exact via an eigendecomposition (see sqrtm_sym below).

Why this replaces calibrate3.py
-------------------------------
calibrate3.py fitted whatever it was given. The accelerometer sweep it was fed had
been recorded while the sensor was being waved around, so it fitted gravity plus hand
movement and produced a 25% axis-scale spread on a part that should be within 3%.
Nothing in the output said so. Every fit here is therefore gated on an explicit
acceptance test, and the script tells you to re-collect rather than handing you
numbers that look plausible and are not.
"""

import os
import sys
import numpy as np

# Read from here when no filename is given. Anchored to this script rather than the
# working directory, so it does not matter where you run it from (calibrate3.py used a
# path relative to the repo root and only worked from there).
DEFAULT_CAPTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "Captures", "capture.txt")

MFIELD = 1000.0        # calibrated vectors are scaled to this norm, as the sketch expects
ACC_LSB_PER_G = 16384.0    # MPU6050 at +-2g
MAG_LSB_PER_GAUSS = 390.0  # HMC5883L with CONFIG_B = 0xA0

# acceptance thresholds
#
# On peak-to-peak: the sketch decides the unit has stopped moving by watching pp over a
# 25-sample window against CAL_STILL_PP (400), but the pp it reports in each record is
# over the 200-sample averaging window. A longer window always sees more of the noise
# distribution - about 5.6 sigma at n=200 versus 4.0 sigma at n=25 - so reusing 400 here
# would be stricter than the gate the firmware itself applied, and would throw out
# perfectly still captures. 400 at 4.0 sigma is sigma=100, which is 560 at 5.6 sigma,
# hence the warn level below. Measured on real captures a still position sits at 310-430
# pp (sigma 55-77, matching the MPU6050 noise spec) and a hand-held one at 800-1100.
ACC_PP_WARN = 600          # above this the position is used but flagged
ACC_PP_REJECT = 1500       # above this it is dropped: that is movement, not noise

GYRO_LSB_PER_DPS = 131.0   # MPU6050 at +-250 deg/s
GYRO_MAX_SEM_DPS = 0.05    # wanted uncertainty of the offset itself
GYRO_PP_REJECT = 3000      # beyond this the noise model breaks and the mean can be biased
ACC_MAX_SCALE_ERR = 0.05   # implied LSB/g must be within 5% of nominal
ACC_MAX_RESIDUAL = 0.01    # 1% rms on |calibrated|
MAG_MAX_RESIDUAL = 0.03    # 3% rms on |calibrated|
DIP_MAX_SD = 1.0           # degrees; the real acceptance test for the pair


# --------------------------------------------------------------------------- parsing
def parse(path):
    gyro, acc, mag = None, [], []
    ngyro = 0
    version = None
    with open(path, "r", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                if line.startswith("#EMON_CAL"):
                    parts = line.split(",")
                    if len(parts) > 1:
                        version = parts[1].strip()
                continue
            p = [x.strip() for x in line.split(",")]
            try:
                if p[0] == "G" and len(p) >= 7:
                    # A capture can hold several gyro runs if the phase was repeated.
                    # The last one wins, on the grounds that it is the most recent
                    # attempt, but the count is reported so that is visible.
                    ngyro += 1
                    gyro = dict(mean=np.array([float(x) for x in p[1:4]]),
                                pp=np.array([float(x) for x in p[4:7]]),
                                n=int(p[7]) if len(p) > 7 else 0,
                                runs=ngyro)
                elif p[0] == "A" and len(p) >= 11:
                    acc.append([int(p[1])] + [float(x) for x in p[2:11]])
                elif p[0] == "M" and len(p) >= 4:
                    mag.append([float(x) for x in p[1:4]])
            except ValueError:
                continue
    return version, gyro, np.array(acc, dtype=float), np.array(mag, dtype=float)


# ----------------------------------------------------------------------- ellipsoid
def sqrtm_sym(M):
    """Matrix square root of a symmetric matrix, via eigendecomposition."""
    w, V = np.linalg.eigh(M)
    return V @ np.diag(np.sqrt(np.abs(w))) @ V.T


def ellipsoid_fit(pts, F=MFIELD):
    """Least-squares ellipsoid fit. Returns (bias, Ainv) mapping raw -> norm F.

    Li & Griffiths (2004), with the h/f swap correction noted on the Teslabs page.
    Same algorithm calibrate3.py used, reimplemented without scipy.
    """
    s = np.asarray(pts, dtype=float).T
    D = np.array([s[0]**2, s[1]**2, s[2]**2,
                  2*s[1]*s[2], 2*s[0]*s[2], 2*s[0]*s[1],
                  2*s[0], 2*s[1], 2*s[2], np.ones_like(s[0])])
    S = D @ D.T
    S11, S12, S21, S22 = S[:6, :6], S[:6, 6:], S[6:, :6], S[6:, 6:]
    C = np.array([[-1, 1, 1, 0, 0, 0],
                  [1, -1, 1, 0, 0, 0],
                  [1, 1, -1, 0, 0, 0],
                  [0, 0, 0, -4, 0, 0],
                  [0, 0, 0, 0, -4, 0],
                  [0, 0, 0, 0, 0, -4]], dtype=float)
    E = np.linalg.inv(C) @ (S11 - S12 @ np.linalg.inv(S22) @ S21)
    w, V = np.linalg.eig(E)
    v1 = np.real(V[:, int(np.argmax(np.real(w)))])
    if v1[0] < 0:
        v1 = -v1
    v2 = (-np.linalg.inv(S22) @ S21) @ v1
    M = np.array([[v1[0], v1[5], v1[4]],
                  [v1[5], v1[1], v1[3]],
                  [v1[4], v1[3], v1[2]]])
    n = v2[:3].reshape(3, 1)
    d = v2[3]
    M1 = np.linalg.inv(M)
    b = (-M1 @ n).ravel()
    denom = (n.T @ M1 @ n)[0, 0] - d
    Ainv = np.real(F / np.sqrt(denom) * sqrtm_sym(M))
    return b, Ainv


def sphere_fit(pts, F=MFIELD):
    """Reduced model: bias + per-axis scale only (6 parameters, no cross terms).

    Needs far fewer points than the full ellipsoid and cannot invent cross-axis
    coupling, so it is the safer answer when the point set is thin.
    """
    p = np.asarray(pts, dtype=float)
    # solve sum_i u_i*(x_i^2) + v_i*x_i + c = 0  with u_i = k_i^2
    Amat = np.column_stack([p**2, p, np.ones(len(p))])
    _, _, Vt = np.linalg.svd(Amat, full_matrices=False)
    sol = Vt[-1]
    u, v, c = sol[:3], sol[3:6], sol[6]
    if np.any(u == 0):
        raise np.linalg.LinAlgError("degenerate sphere fit")
    if u[0] < 0:
        u, v, c = -u, -v, -c
    b = -v / (2 * u)
    k2 = u / (np.sum(u * b * b) - c)
    if np.any(k2 <= 0):
        raise np.linalg.LinAlgError("degenerate sphere fit")
    return b, np.diag(F * np.sqrt(k2))


def apply_cal(raw, b, Ainv):
    return (np.asarray(raw, dtype=float) - b) @ np.asarray(Ainv).T


def residual(raw, b, Ainv, F=MFIELD):
    r = np.linalg.norm(apply_cal(raw, b, Ainv), axis=1)
    return float(np.sqrt(np.mean((r / F - 1.0) ** 2)))


AXIS_NAMES = ("+X", "+Y", "+Z", "-X", "-Y", "-Z")

# A tilted position puts 1/sqrt(3) = 0.58 of gravity on each axis, so an axis that only
# ever reaches 0.58 was never squarely up or down and its scale is poorly determined.
# A proper face reaches 1.0, so anything below this means a face is missing.
FACE_REACH_MIN = 0.80


def axis_reach(pts, b):
    """How far along each axis did the samples actually get, as a fraction of radius?

    The angular-gap measure below is too generous here: six tilted positions sit within
    ~25 deg of every axis, so a skipped face hides behind them. What actually matters is
    whether each axis was driven to its full +1 g and -1 g, which this measures directly.
    Returns a list of (name, reach) worst-first.
    """
    u = np.asarray(pts, dtype=float) - b
    n = np.linalg.norm(u, axis=1, keepdims=True)
    n[n == 0] = 1.0
    u = u / n
    reach = list(u.max(axis=0)) + list(-u.min(axis=0))   # +X+Y+Z then -X-Y-Z
    return sorted(zip(AXIS_NAMES, reach), key=lambda t: t[1])


def coverage(pts, b):
    """How well do the points surround the bias?

    For each of the six axis directions, find the closest sample. The worst of those
    six is the biggest hole in the coverage. Returns (degrees, which direction), so a
    face that was missed or duplicated can be named rather than just flagged.
    """
    u = np.asarray(pts, dtype=float) - b
    n = np.linalg.norm(u, axis=1, keepdims=True)
    n[n == 0] = 1.0
    u = u / n
    gaps = [float(np.degrees(np.arccos(np.clip(u @ d, -1, 1))).min())
            for d in np.vstack([np.eye(3), -np.eye(3)])]
    i = int(np.argmax(gaps))
    return gaps[i], AXIS_NAMES[i]


# ------------------------------------------------------------------------- report
def emit_c_array(name, b, Ainv):
    print(f"float {name}_B [3] = {{{b[0]:.2f}, {b[1]:.2f}, {b[2]:.2f}}};")
    print()
    print(f"float {name}_Ainv[3][3] = {{")
    for r in range(3):
        end = "};" if r == 2 else ","
        print(f"{{ {Ainv[r,0]:.5f}, {Ainv[r,1]:.5f}, {Ainv[r,2]:.5f} }}{end}")


def hr(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def do_gyro(gyro):
    hr("GYRO OFFSETS")
    if gyro is None:
        print("  no G record in the capture - phase 1 not run")
        return None, True
    ok = True
    if gyro.get("runs", 1) > 1:
        print(f"  NOTE: {gyro['runs']} gyro runs in this capture, using the last one")
    print(f"  samples averaged : {gyro['n']}")
    print(f"  mean (raw LSB)   : {np.round(gyro['mean'], 1)}")
    print(f"  peak-to-peak     : {np.round(gyro['pp'], 0)}")
    print(f"  implied bias     : {np.round(gyro['mean'] / 131.0, 2)} deg/s")

    # What matters for an OFFSET is not the spread of the samples but the uncertainty of
    # their mean, and averaging n samples shrinks that by sqrt(n). At n=500 the expected
    # peak-to-peak of Gaussian noise is about 6.18 sigma, so back out sigma and divide by
    # sqrt(n). Judging the raw peak-to-peak instead rejects captures whose mean is in fact
    # good to a hundredth of a degree per second.
    n = max(int(gyro["n"]) or 1, 1)
    sigma = gyro["pp"] / 6.18
    sem = sigma / np.sqrt(n)
    print(f"  implied noise    : sigma {np.round(sigma, 0)} LSB")
    print(f"  uncertainty of the mean: {np.round(sem, 1)} LSB = "
          f"{np.round(sem / GYRO_LSB_PER_DPS, 3)} deg/s")
    if np.any(gyro["pp"] > GYRO_PP_REJECT):
        print(f"  FAIL: peak-to-peak over {GYRO_PP_REJECT} is movement, not noise, and a "
              f"sustained\n        rotation biases the mean. Re-run phase 1.")
        ok = False
    elif np.any(sem / GYRO_LSB_PER_DPS > GYRO_MAX_SEM_DPS):
        print(f"  FAIL: the mean is only good to {np.max(sem/GYRO_LSB_PER_DPS):.3f} deg/s, "
              f"worse than the {GYRO_MAX_SEM_DPS} deg/s wanted. Re-run phase 1.")
        ok = False
    else:
        print(f"  PASS: mean is good to better than {GYRO_MAX_SEM_DPS} deg/s")
    print("  (a slow steady rotation would bias the mean without widening the spread,")
    print("   so this cannot prove the unit was still - just put it down and leave it)")
    print()
    print("  paste into the sketch (get_gyro SUBTRACTS these):")
    print(f"float GyroOffset[3] = {{{gyro['mean'][0]:.1f}f, "
          f"{gyro['mean'][1]:.1f}f, {gyro['mean'][2]:.1f}f}};")
    return gyro["mean"], ok


def do_accel(acc):
    hr("ACCELEROMETER")
    if len(acc) == 0:
        print("  no A records in the capture - phase 2 not run")
        return None, None, None, None, True
    pos, raw, magraw, pp = acc[:, 0], acc[:, 1:4], acc[:, 4:7], acc[:, 7:10]
    print(f"  orientations captured : {len(raw)}")

    worst_pp = pp.max(axis=1)
    keep = worst_pp <= ACC_PP_REJECT
    if not np.all(keep):
        bad = np.where(~keep)[0]
        print(f"  rejecting {len(bad)} orientation(s) that were moving, "
              f"peak-to-peak > {ACC_PP_REJECT}:")
        for i in bad[:5]:
            print(f"    position {int(pos[i])}: pp = {pp[i].astype(int)}")
        if len(bad) > 5:
            print(f"    ... and {len(bad)-5} more (worst {int(worst_pp[bad].max())})")
    shaky = np.where(keep & (worst_pp > ACC_PP_WARN))[0]
    if len(shaky):
        print(f"  {len(shaky)} orientation(s) noisier than {ACC_PP_WARN} pp but kept "
              f"(hand-held rather than resting?):")
        for i in shaky:
            print(f"    position {int(pos[i])}: pp = {pp[i].astype(int)}")
        print("    the average is still mostly gravity; the dip check below is the "
              "real test")
    raw, magraw = raw[keep], magraw[keep]
    if len(raw) < 9:
        print(f"  FAIL: only {len(raw)} usable orientations, need at least 9 for an "
              f"ellipsoid fit (12 recommended). Re-run phase 2.")
        return None, None, None, None, False

    results = {}
    for name, fn in (("full ellipsoid", ellipsoid_fit), ("bias+scale only", sphere_fit)):
        try:
            b, Ainv = fn(raw)
        except np.linalg.LinAlgError as e:
            print(f"  {name}: fit failed ({e})")
            continue
        res = residual(raw, b, Ainv)
        ev = np.linalg.eigvalsh((Ainv + Ainv.T) / 2)
        lsb = MFIELD / ev[::-1]
        spread = (ev.max() - ev.min()) / ev.mean()
        scale_err = np.max(np.abs(lsb / ACC_LSB_PER_G - 1.0))
        results[name] = dict(b=b, Ainv=Ainv, res=res, lsb=lsb,
                             spread=spread, scale_err=scale_err)

    if not results:
        return None, None, None, None, False

    # Coverage is measured about the FITTED centre, not the mean of the points. The mean
    # is pulled toward whichever direction was over-sampled, which is exactly the case
    # this check exists to catch, and it masks the hole it is skewed by.
    centre = results.get("bias+scale only", results["full ellipsoid"])["b"]
    reach = axis_reach(raw, centre)
    print("  axis reach (1.00 = that face was sampled squarely): " +
          "  ".join(f"{n} {v:.2f}" for n, v in reach))
    missing = [n for n, v in reach if v < FACE_REACH_MIN]
    face_ok = not missing
    if face_ok:
        print("  coverage: ok, all six faces present")
    else:
        print(f"  coverage: POOR - {', '.join(missing)} never reached full scale, so "
              f"{'those faces were' if len(missing) > 1 else 'that face was'}\n"
              f"            skipped or duplicated. The scale on "
              f"{'those axes is' if len(missing) > 1 else 'that axis is'} not properly\n"
              f"            constrained. Re-run phase 2 with all six faces.")

    for name in ("full ellipsoid", "bias+scale only"):
        if name not in results:
            continue
        r = results[name]
        print(f"\n  {name}:")
        print(f"    residual on |cal|   : {100*r['res']:.2f} %   "
              f"({'ok' if r['res'] < ACC_MAX_RESIDUAL else 'HIGH'})")
        print(f"    implied LSB/g       : {np.round(r['lsb'], 0)}  "
              f"(nominal {ACC_LSB_PER_G:.0f})")
        print(f"    worst scale error   : {100*r['scale_err']:.1f} %   "
              f"({'ok' if r['scale_err'] < ACC_MAX_SCALE_ERR else 'IMPLAUSIBLE for an MPU6050'})")
        print(f"    axis-scale spread   : {100*r['spread']:.1f} %")

    full = results.get("full ellipsoid")
    if full and full["res"] < ACC_MAX_RESIDUAL and full["scale_err"] < ACC_MAX_SCALE_ERR:
        chosen, why = "full ellipsoid", "passes both gates"
    elif "bias+scale only" in results and \
            results["bias+scale only"]["scale_err"] < ACC_MAX_SCALE_ERR:
        chosen, why = "bias+scale only", \
            "the full ellipsoid failed its sanity gate, falling back to the reduced model"
    else:
        print("\n  FAIL: neither model produced a physically sensible accelerometer "
              "calibration.\n        The data is dominated by movement or the coverage "
              "is too poor. Re-run phase 2.")
        best = full or results["bias+scale only"]
        return best["b"], best["Ainv"], raw, magraw, False

    r = results[chosen]
    print(f"\n  USING: {chosen} ({why})")
    if not face_ok:
        # The fit can look healthy and still be wrong here: the residual only says the
        # points lie on the fitted surface, not that the surface is pinned down.
        print("  but the coverage above FAILED, so an axis scale rests on tilted "
              "positions alone.")
    print()
    emit_c_array("A", r["b"], r["Ainv"])
    return r["b"], r["Ainv"], raw, magraw, face_ok


def do_mag(mag, acc_mag):
    hr("MAGNETOMETER")
    pts = mag if len(mag) else acc_mag
    if pts is None or len(pts) == 0:
        print("  no M records in the capture - phase 3 not run")
        return None, None, True
    if not len(mag):
        print("  no sweep data; falling back to the static readings from phase 2")
    print(f"  samples: {len(pts)}")
    try:
        b, Ainv = ellipsoid_fit(pts)
    except np.linalg.LinAlgError as e:
        print(f"  FAIL: fit failed ({e})")
        return None, None, False
    res = residual(pts, b, Ainv)
    gap, axis = coverage(pts, b)
    field = np.linalg.norm(pts - b, axis=1).mean()
    ev = np.linalg.eigvalsh((Ainv + Ainv.T) / 2)

    print(f"  hard-iron offset    : {np.round(b, 1)} LSB")
    print(f"  field magnitude     : {field:.0f} LSB = {field/MAG_LSB_PER_GAUSS:.3f} Gauss")
    print(f"  residual on |cal|   : {100*res:.2f} %  "
          f"({'ok' if res < MAG_MAX_RESIDUAL else 'HIGH'})")
    if gap < 50:
        print(f"  worst direction gap : {gap:.0f} deg toward {axis} (ok)")
    else:
        print(f"  worst direction gap : {gap:.0f} deg toward {axis} - POOR")
        print(f"       the field never lay along the sensor's {axis} axis, so the sweep")
        print(f"       did not turn the unit through every attitude. The {axis[1]} bias is")
        print(f"       then the least constrained parameter, and that is exactly what")
        print(f"       shifts the mean dip angle away from the expected inclination.")
        print(f"       Re-run phase 3 and include turning the unit fully over.")
    print(f"  axis-scale spread   : {100*(ev.max()-ev.min())/ev.mean():.1f} %  "
          f"(the HMC5883L Z axis genuinely differs from X/Y, ~25% is normal)")
    ok = res < MAG_MAX_RESIDUAL and gap < 50
    print(f"  {'PASS' if ok else 'FAIL - re-run phase 3'}")
    print()
    emit_c_array("M", b, Ainv)
    return b, Ainv, ok


def do_dip(acc_b, acc_A, mag_b, mag_A, acc_raw, acc_mag, expected):
    hr("CROSS-CHECK: DIP ANGLE  (the acceptance test that matters)")
    if acc_b is None or mag_b is None or acc_mag is None or len(acc_mag) == 0:
        print("  needs both phase 2 and a magnetometer calibration - skipped")
        return None
    a = apply_cal(acc_raw, acc_b, acc_A)
    m = apply_cal(acc_mag, mag_b, mag_A)
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    m = m / np.linalg.norm(m, axis=1, keepdims=True)
    dip = np.degrees(np.arcsin(np.clip(np.sum(a * m, axis=1), -1, 1)))
    sd = float(np.std(dip))
    print("  The angle between gravity and the field is a property of your location.")
    print("  It must read the same at every orientation. Any spread is calibration error,")
    print("  and it turns into heading error at roughly 2.3 to 2.7 times the spread.")
    print()
    print(f"  measured at {len(dip)} orientations: mean {np.mean(np.abs(dip)):.2f} deg, "
          f"sd {sd:.2f} deg")
    print(f"  per orientation: {np.round(dip, 1)}")
    print(f"  expected inclination for your location: {expected:.1f} deg")
    err = abs(np.mean(np.abs(dip)) - expected)
    ok = sd < DIP_MAX_SD
    print()
    print(f"  spread   {sd:.2f} deg  -> {'PASS' if ok else 'FAIL (want < %.1f)' % DIP_MAX_SD}")
    print(f"  mean off {err:.2f} deg  -> "
          f"{'ok' if err < 2.0 else 'check the expected value with --dip, or a vertical bias remains'}")

    if not ok:
        # A single rogue orientation and a systemic error need different fixes, and both
        # can be present at once. Dropping the worst point and re-measuring separates
        # them, so report each on its own terms rather than picking one story.
        resid = np.abs(dip - np.median(dip))
        worst = int(np.argmax(resid))
        sd_without = float(np.std(np.delete(dip, worst)))
        print()
        if resid[worst] > 3 * max(sd_without, 0.2):
            print(f"  ONE BAD ORIENTATION: #{worst} reads {dip[worst]:.1f} deg, "
                  f"{resid[worst]:.1f} deg off the median")
            print(f"     of the others. Something magnetic was near the unit for that")
            print(f"     position, or it moved while sampling. Keep the bench clear of")
            print(f"     steel, magnets, speakers and laptops, and do not move the unit")
            print(f"     to a different spot between positions - the field varies across")
            print(f"     a room. Dropping it, the spread would be {sd_without:.2f} deg.")
        if sd_without >= DIP_MAX_SD:
            print(f"  RESIDUAL CALIBRATION ERROR: even ignoring the worst orientation the")
            print(f"     spread is {sd_without:.2f} deg, which is real calibration error and")
            print(f"     implies roughly {2.5*sd_without:.1f} deg of heading error.")
        elif resid[worst] <= 3 * max(sd_without, 0.2):
            print(f"  spread is shared across orientations rather than one bad point, so")
            print(f"     this is the calibration itself: roughly {2.5*sd:.1f} deg of heading error.")
    return ok


def plot(acc_raw, acc_b, acc_A, mag, mag_b, mag_A):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(--plot needs matplotlib, skipping)")
        return
    fig = plt.figure(figsize=(11, 5))
    for i, (title, pts, b, A) in enumerate(
            (("accelerometer", acc_raw, acc_b, acc_A), ("magnetometer", mag, mag_b, mag_A))):
        if pts is None or b is None or len(pts) == 0:
            continue
        c = apply_cal(pts, b, A)
        ax = fig.add_subplot(1, 2, i + 1, projection="3d")
        ax.scatter(c[:, 0], c[:, 1], c[:, 2], s=12)
        u, v = np.mgrid[0:2*np.pi:40j, 0:np.pi:20j]
        ax.plot_wireframe(MFIELD*np.cos(u)*np.sin(v), MFIELD*np.sin(u)*np.sin(v),
                          MFIELD*np.cos(v), color="0.8", linewidth=.4)
        ax.set_title(f"{title} after calibration")
        for s in "xyz":
            getattr(ax, f"set_{s}lim")(-1.3*MFIELD, 1.3*MFIELD)
    plt.tight_layout()
    plt.show()


def main(argv):
    expected_dip = 66.1
    want_plot = False
    files = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--dip":
            if i + 1 >= len(argv):
                print("--dip needs a value, e.g. --dip 66.1")
                return 2
            try:
                expected_dip = float(argv[i + 1])
            except ValueError:
                print(f"--dip needs a number, got {argv[i + 1]!r}")
                return 2
            i += 2
            continue
        if a == "--plot":
            want_plot = True
        elif a.startswith("--"):
            print(f"unknown option {a}")
            return 2
        else:
            files.append(a)
        i += 1
    if len(files) > 1:
        print(f"expected one capture file, got {len(files)}")
        return 2
    path = files[0] if files else DEFAULT_CAPTURE
    if not files and not os.path.isfile(path):
        print(__doc__)
        print(f"no capture file given and the default is not there:\n  {path}")
        return 2

    try:
        version, gyro, acc, mag = parse(path)
    except OSError as e:
        print(f"cannot read {path}: {e.strerror}")
        return 2
    print(f"capture : {path}")
    print(f"format  : {'v' + version if version else 'no #EMON_CAL header (old capture?)'}")
    print(f"records : gyro={'1' if gyro else '0'}  acc={len(acc)}  mag={len(mag)}")
    if gyro is None and len(acc) == 0 and len(mag) == 0:
        print("\nNothing recognised. This script reads G, A and M records from "
              "collectDataForMahonyCalibration()\nin the sketch - capture the whole "
              "serial session, prompts and all, and pass that file.")
        print("\nIf this is an old 6-column acc_mag_raw.csv, it predates this format "
              "and the\nroutine that produced it no longer exists. Re-run the "
              "calibration; see\ndocs/Calibration_instructions.md.")
        return 2

    _, gok = do_gyro(gyro)
    acc_b, acc_A, acc_raw, acc_mag, aok = do_accel(acc)
    mag_b, mag_A, mok = do_mag(mag, acc_mag)
    dok = do_dip(acc_b, acc_A, mag_b, mag_A, acc_raw, acc_mag, expected_dip)

    hr("SUMMARY")
    checks = (("gyro", gok), ("accelerometer", aok),
              ("magnetometer", mok), ("dip cross-check", dok))
    for nm, ok in checks:
        print(f"  {nm:18s} {'SKIPPED' if ok is None else ('PASS' if ok else 'FAIL')}")
    failed = [nm for nm, ok in checks if ok is False]
    skipped = [nm for nm, ok in checks if ok is None]
    print()
    if failed:
        print("  Do NOT paste these values until the failures above are fixed.")
    elif skipped:
        print("  Nothing failed, but " + ", ".join(skipped) + " did not run, so the")
        print("  calibration is unverified. The dip cross-check is the one that actually")
        print("  proves the accelerometer and magnetometer agree - run phases 2 and 3.")
    else:
        print("  All good - paste the blocks above into emon_MiniC5A_anemometer.ino")
    allok = not failed and not skipped

    if want_plot:
        plot(acc_raw, acc_b, acc_A, mag if len(mag) else None, mag_b, mag_A)
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
