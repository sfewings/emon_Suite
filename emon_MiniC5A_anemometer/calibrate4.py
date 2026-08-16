#!/usr/bin/env python3
"""
calibrate4.py - process a calibration capture from emon_MiniC5A_anemometer.ino
and emit paste-ready GyroOffset, A_B, A_Ainv, M_B and M_Ainv blocks.

    python calibrate4.py <capture.txt> [--dip 66.1] [--plot]

Capture the whole serial session from collectDataForMahonyCalibration() to a text
file and pass it in here. Phases may be captured separately and concatenated; any
phase that is missing is simply skipped.

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

import sys
import numpy as np

MFIELD = 1000.0        # calibrated vectors are scaled to this norm, as the sketch expects
ACC_LSB_PER_G = 16384.0    # MPU6050 at +-2g
MAG_LSB_PER_GAUSS = 390.0  # HMC5883L with CONFIG_B = 0xA0

# acceptance thresholds
ACC_MAX_PP = 400           # per-axis peak-to-peak allowed while "still" (matches the sketch)
ACC_MAX_SCALE_ERR = 0.05   # implied LSB/g must be within 5% of nominal
ACC_MAX_RESIDUAL = 0.01    # 1% rms on |calibrated|
MAG_MAX_RESIDUAL = 0.03    # 3% rms on |calibrated|
DIP_MAX_SD = 1.0           # degrees; the real acceptance test for the pair


# --------------------------------------------------------------------------- parsing
def parse(path):
    gyro, acc, mag = None, [], []
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
                    gyro = dict(mean=np.array([float(x) for x in p[1:4]]),
                                pp=np.array([float(x) for x in p[4:7]]),
                                n=int(p[7]) if len(p) > 7 else 0)
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


def coverage(pts, b):
    """How well do the points surround the bias? Returns worst-direction gap in degrees."""
    u = np.asarray(pts, dtype=float) - b
    n = np.linalg.norm(u, axis=1, keepdims=True)
    n[n == 0] = 1.0
    u = u / n
    # for each of the 6 axis directions, the closest sample
    worst = 0.0
    for d in np.vstack([np.eye(3), -np.eye(3)]):
        ang = np.degrees(np.arccos(np.clip(u @ d, -1, 1))).min()
        worst = max(worst, ang)
    return worst


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
    print(f"  samples averaged : {gyro['n']}")
    print(f"  mean (raw LSB)   : {np.round(gyro['mean'], 1)}")
    print(f"  peak-to-peak     : {np.round(gyro['pp'], 0)}")
    print(f"  implied bias     : {np.round(gyro['mean'] / 131.0, 2)} deg/s")
    if np.any(gyro["pp"] > 300):
        print("  FAIL: too much spread - the unit was disturbed. Re-run phase 1.")
        ok = False
    else:
        print("  PASS: unit was still")
    print()
    print("  paste into the sketch (get_gyro SUBTRACTS these):")
    print(f"float GyroOffset[3] = {{{gyro['mean'][0]:.1f}f, "
          f"{gyro['mean'][1]:.1f}f, {gyro['mean'][2]:.1f}f}};")
    return gyro["mean"], ok


def do_accel(acc):
    hr("ACCELEROMETER")
    if len(acc) == 0:
        print("  no A records in the capture - phase 2 not run")
        return None, None, None, True
    pos, raw, magraw, pp = acc[:, 0], acc[:, 1:4], acc[:, 4:7], acc[:, 7:10]
    print(f"  orientations captured : {len(raw)}")

    keep = np.all(pp <= ACC_MAX_PP, axis=1)
    if not np.all(keep):
        bad = np.where(~keep)[0]
        print(f"  rejecting {len(bad)} orientation(s) with peak-to-peak > {ACC_MAX_PP}:")
        for i in bad[:5]:
            print(f"    position {int(pos[i])}: pp = {pp[i].astype(int)}")
        if len(bad) > 5:
            print(f"    ... and {len(bad)-5} more (worst pp seen: {int(pp[bad].max())})")
    raw, magraw = raw[keep], magraw[keep]
    if len(raw) < 9:
        print(f"  FAIL: only {len(raw)} usable orientations, need at least 9 for an "
              f"ellipsoid fit (12 recommended). Re-run phase 2.")
        return None, None, None, False

    gap = coverage(raw, raw.mean(axis=0))
    print(f"  worst axis-direction gap: {gap:.0f} deg "
          f"({'ok' if gap < 40 else 'POOR - some faces were missed'})")

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
        print(f"\n  {name}:")
        print(f"    residual on |cal|   : {100*res:.2f} %   "
              f"({'ok' if res < ACC_MAX_RESIDUAL else 'HIGH'})")
        print(f"    implied LSB/g       : {np.round(lsb, 0)}  (nominal {ACC_LSB_PER_G:.0f})")
        print(f"    worst scale error   : {100*scale_err:.1f} %   "
              f"({'ok' if scale_err < ACC_MAX_SCALE_ERR else 'IMPLAUSIBLE for an MPU6050'})")
        print(f"    axis-scale spread   : {100*spread:.1f} %")

    if not results:
        return None, None, None, False

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
        return best["b"], best["Ainv"], magraw, False

    r = results[chosen]
    print(f"\n  USING: {chosen} ({why})")
    print()
    emit_c_array("A", r["b"], r["Ainv"])
    return r["b"], r["Ainv"], magraw, True


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
    gap = coverage(pts, b)
    field = np.linalg.norm(pts - b, axis=1).mean()
    ev = np.linalg.eigvalsh((Ainv + Ainv.T) / 2)

    print(f"  hard-iron offset    : {np.round(b, 1)} LSB")
    print(f"  field magnitude     : {field:.0f} LSB = {field/MAG_LSB_PER_GAUSS:.3f} Gauss")
    print(f"  residual on |cal|   : {100*res:.2f} %  "
          f"({'ok' if res < MAG_MAX_RESIDUAL else 'HIGH'})")
    print(f"  worst direction gap : {gap:.0f} deg "
          f"({'ok' if gap < 50 else 'POOR - the sweep missed part of the sphere'})")
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
        print("  implies roughly "
              f"{2.5*sd:.1f} deg of heading error still present")
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
    if len(files) != 1:
        print(__doc__)
        return 2
    path = files[0]

    try:
        version, gyro, acc, mag = parse(path)
    except OSError as e:
        print(f"cannot read {path}: {e.strerror}")
        return 2
    print(f"capture : {path}")
    print(f"format  : {'v' + version if version else 'no #EMON_CAL header (old capture?)'}")
    print(f"records : gyro={'1' if gyro else '0'}  acc={len(acc)}  mag={len(mag)}")
    if gyro is None and len(acc) == 0 and len(mag) == 0:
        print("\nNothing recognised. This script reads captures from "
              "collectDataForMahonyCalibration() v4;\nfor the old 6-column CSV use calibrate3.py.")
        return 2

    _, gok = do_gyro(gyro)
    acc_b, acc_A, acc_mag, aok = do_accel(acc)
    mag_b, mag_A, mok = do_mag(mag, acc_mag)
    acc_raw = acc[:, 1:4] if len(acc) else None
    if acc_raw is not None and acc_mag is not None and len(acc_mag) != len(acc_raw):
        # phase 2 rows were rejected; re-derive the matching accelerometer rows
        keep = np.all(acc[:, 7:10] <= ACC_MAX_PP, axis=1)
        acc_raw = acc[keep, 1:4]
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
