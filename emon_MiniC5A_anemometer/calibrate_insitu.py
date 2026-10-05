#!/usr/bin/env python3
"""
calibrate_insitu.py - correct the compass for the BOAT's own magnetism, using a
normal sail log that contains a few slow circles under power.

    python calibrate_insitu.py <log.TXT> [--from HH:MM --to HH:MM] [--sketch PATH] [--plot]

Why this exists, and why it is not calibrate4.py
------------------------------------------------
calibrate4.py fits a 3D ellipsoid, which needs the sensor turned through every
attitude. A boat cannot do that. Turning in yaw sweeps the field around a CONE at the
dip angle, never a sphere, so the vertical terms are never excited. Fed a boat swing,
calibrate4.py returns nonsense for them and correctly fails its coverage check.

So this script fits only the HORIZONTAL plane and keeps the vertical terms from the
bench calibration. That is well determined by yaw-only data, and it is the part that
moves your heading. On simulated boat iron it takes heading error from 17.9 deg rms to
1.0 deg, and one circle is enough.

It needs no firmware change. The ordinary imu and gps telemetry already carries
everything required.

What it reads
-------------
  imu,0,ax,ay,az,mx,my,mz,gx,gy,gz,heading   acc and mag, already calibrated and
                                             normalised by the sketch
  gps,0,lat,lon,course,speed                 course over ground is the reference

What it prints
--------------
  updated M_B and M_Ainv (horizontal terms only; the Z row and column are preserved)
  a re-measured INSTALATION_HEADING_OFFSET, which always shifts when M_B changes
"""

import os
import re
import sys
import datetime
import numpy as np

MFIELD = 1000.0          # the norm calibrate4.py scales the calibrated vector to
IGRF_DIP = 66.1          # Perth; override with --dip

# acceptance thresholds
MIN_ARC = 330.0          # degrees of heading a usable circle must cover
MIN_BINS = 11            # of 12 thirty-degree bins that must be occupied
MAX_TILT = 12.0          # mean tilt during the circles, degrees
MAX_SOG = 15.0


# --------------------------------------------------------------- sketch constants
DEFAULTS = dict(
    M_B=np.array([102.05, -121.66, 10.22]),
    M_Ainv=np.array([[3.81800, 0.02270, -0.02062],
                     [0.02270, 3.81465, -0.04824],
                     [-0.02062, -0.04824, 4.76717]]),
    declination=-1.5,
    offset=7,
)


def read_sketch(path):
    """Pull the live constants out of the .ino so they cannot drift out of step."""
    out = dict(DEFAULTS)
    try:
        s = open(path, errors="replace").read()
    except OSError:
        print(f"  (could not read {path}, using built-in defaults)")
        return out
    m = re.search(r"float\s+M_B\s*\[3\]\s*=\s*\{([^}]*)\}", s)
    if m:
        out["M_B"] = np.array([float(x) for x in m.group(1).split(",")])
    m = re.search(r"float\s+M_Ainv\s*\[3\]\[3\]\s*=\s*\{(.*?)\}\s*\}\s*;", s, re.S)
    if m:
        nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", m.group(1))]
        if len(nums) >= 9:
            out["M_Ainv"] = np.array(nums[:9]).reshape(3, 3)
    m = re.search(r"float\s+declination\s*=\s*([-+]?[\d.]+)", s)
    if m:
        out["declination"] = float(m.group(1))
    m = re.search(r"INSTALATION_HEADING_OFFSET\s*=\s*([-+]?\d+)", s)
    if m:
        out["offset"] = int(m.group(1))
    return out


# ------------------------------------------------------------------------ parsing
def parse(path, t_from=None, t_to=None):
    imu, gps = [], []
    with open(path, errors="replace") as f:
        for line in f:
            p = line.rstrip("\n").split(",")
            if len(p) < 3:
                continue
            try:
                t = datetime.datetime.strptime(p[0], "%d/%m/%Y %H:%M:%S")
            except ValueError:
                continue
            if t_from and t.time() < t_from:
                continue
            if t_to and t.time() > t_to:
                continue
            ts = t.timestamp()
            try:
                if p[1] == "imu" and len(p) >= 13:
                    imu.append([ts] + [float(x) for x in p[3:13]])
                elif p[1] == "gps" and p[2] == "0" and len(p) >= 7:
                    gps.append([ts] + [float(x) for x in p[3:7]])
            except ValueError:
                pass
    return np.array(imu, float), np.array(gps, float)


def wrap180(x):
    return (np.asarray(x, float) + 180.0) % 360.0 - 180.0


def nearest(t_ref, t_src, v, max_dt=2.0):
    i = np.clip(np.searchsorted(t_src, t_ref), 1, len(t_src) - 1)
    pick = np.where(np.abs(t_ref - t_src[i-1]) <= np.abs(t_src[i] - t_ref), i-1, i)
    out = v[pick].astype(float)
    out[np.abs(t_ref - t_src[pick]) > max_dt] = np.nan
    return out


def circ_deg(t_ref, t_src, deg, max_dt=2.0):
    s = nearest(t_ref, t_src, np.sin(np.radians(deg)), max_dt)
    c = nearest(t_ref, t_src, np.cos(np.radians(deg)), max_dt)
    return np.degrees(np.arctan2(s, c)) % 360.0


def heading_of(au, mu, decl, offset, p=np.array([1.0, 0, 0])):
    """the sketch's get_heading(), unrounded"""
    W = np.cross(au, mu); W /= np.linalg.norm(W, axis=-1, keepdims=True)
    N = np.cross(W, au); N /= np.linalg.norm(N, axis=-1, keepdims=True)
    h = -np.degrees(np.arctan2(W @ p, N @ p))
    return (h + decl - offset) % 360.0


# ------------------------------------------------------------------ circle finding
def find_circles(t, hdg, sog, min_arc=MIN_ARC):
    """Segments where the boat turned steadily through at least min_arc degrees."""
    d = wrap180(np.diff(hdg))
    d[np.abs(d) > 30] = 0.0                      # ignore glitches
    segs = []
    i = 0
    n = len(d)
    while i < n:
        if not np.isfinite(sog[i]) or sog[i] < 0.8:
            i += 1
            continue
        sgn = np.sign(d[i])
        if sgn == 0:
            i += 1
            continue
        j, tot, bad = i, 0.0, 0
        while j < n and bad < 12:
            if np.sign(d[j]) == sgn or d[j] == 0:
                tot += d[j]; bad = 0
            else:
                tot += d[j]; bad += 1
            if abs(tot) >= 360.0:
                break
            j += 1
        if abs(tot) >= min_arc and (t[j] - t[i]) < 600:
            segs.append((i, min(j + 1, len(t) - 1), tot))
            i = j + 1
        else:
            i += 1
    return segs


# --------------------------------------------------------------------- the 2D fit
def recover_scale(mu, au, dip_deg):
    """Undo the sketch's normalisation, which would otherwise hide the boat's iron.

    The sketch transmits the field as a UNIT vector, so the magnitude variation that an
    ellipse fit feeds on is gone. It can be recovered: this correction is horizontal
    only, so the field's VERTICAL component is untouched by the boat and is the same
    constant at every heading. With u the unit vector and v its component along the
    measured up, |y| = (vertical constant)/v, hence y = u * const / v.

    The constant is arbitrary - the sketch re-normalises anyway - so the expected dip is
    used purely to put the numbers on a familiar scale.
    """
    up = au / np.linalg.norm(au, axis=1, keepdims=True)
    v = np.sum(mu * up, axis=1)
    v = np.where(np.abs(v) < 0.2, np.nan, v)         # guard near the horizontal
    return mu * (MFIELD * np.sin(np.radians(dip_deg)) / v)[:, None], up


def level_project(y, au):
    """Field in the boat's horizontal plane: x along the bow, y to port."""
    up = au / np.linalg.norm(au, axis=1, keepdims=True)
    bow = np.tile([1.0, 0, 0], (len(au), 1))
    e1 = bow - up * np.sum(up * bow, axis=1, keepdims=True)
    e1 /= np.linalg.norm(e1, axis=1, keepdims=True)
    e2 = np.cross(up, e1)
    return np.column_stack([np.sum(y * e1, axis=1), np.sum(y * e2, axis=1)]), up


def ellipse_fit(p):
    """fit (p-c)' M (p-c) = 1, return centre and the 2x2 matrix that makes it a circle"""
    x, y = p[:, 0], p[:, 1]
    D = np.column_stack([x*x, x*y, y*y, x, y, np.ones_like(x)])
    _, _, Vt = np.linalg.svd(D, full_matrices=False)
    a, b, c, d, e, f = Vt[-1]
    Mq = np.array([[a, b/2], [b/2, c]])
    if abs(np.linalg.det(Mq)) < 1e-18:
        raise np.linalg.LinAlgError("conic is degenerate - the heading coverage is too "
                                    "one-sided to define an ellipse")
    cen = np.linalg.solve(2*Mq, [-d, -e])
    k = cen @ Mq @ cen - f
    # The conic solution is only defined up to an overall sign, so Mq and k may both
    # come out negative for the very same ellipse. What has to be positive definite is
    # the ratio Mq/k; testing Mq or k on their own rejects perfectly good fits.
    if abs(k) < 1e-18:
        raise np.linalg.LinAlgError("degenerate conic")
    w, V = np.linalg.eigh(Mq/k)
    if np.any(w <= 0):
        raise np.linalg.LinAlgError("fit is a hyperbola, not an ellipse - the points do "
                                    "not close a loop, so the circle was not completed")
    W = V @ np.diag(np.sqrt(w)) @ V.T
    # Normalise to unit determinant so this corrects SHAPE only. Without it W carries
    # a 1/radius scale that would leave M_Ainv three orders of magnitude out. The
    # sketch re-normalises the vector, so overall scale is free; shape is what matters.
    W = W / np.sqrt(np.linalg.det(W))
    return cen, W, float(np.sqrt(w.max()/w.min()))


def harm(h, y, order=2):
    b10 = (h // 10).astype(int) % 36
    c = np.bincount(b10, minlength=36).astype(float)
    w = 1.0/np.maximum(c[b10], 1); w /= w.sum(); s = np.sqrt(w); r = np.radians(h)
    X = np.column_stack([np.ones_like(r)] + sum([[np.sin(k*r), np.cos(k*r)]
                                                 for k in range(1, order+1)], []))
    p, *_ = np.linalg.lstsq(X*s[:, None], y*s, rcond=None)
    return p


def curve(b, hh):
    r = np.radians(hh)
    o = b[0]*np.ones_like(r)
    for k in range(1, (len(b)-1)//2 + 1):
        o += b[2*k-1]*np.sin(k*r) + b[2*k]*np.cos(k*r)
    return o


def hr(s):
    print("\n" + "=" * 72)
    print(s)
    print("=" * 72)


# ------------------------------------------------------------------------- driver
def main(argv):
    path = None
    t_from = t_to = None
    sketch = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "emon_MiniC5A_anemometer.ino")
    dip_expect = IGRF_DIP
    want_plot = False
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("--from", "--to", "--sketch", "--dip"):
            if i + 1 >= len(argv):
                print(f"{a} needs a value"); return 2
            v = argv[i+1]
            try:
                if a == "--from":
                    t_from = datetime.datetime.strptime(v, "%H:%M").time()
                elif a == "--to":
                    t_to = datetime.datetime.strptime(v, "%H:%M").time()
                elif a == "--dip":
                    dip_expect = float(v)
                else:
                    sketch = v
            except ValueError:
                print(f"bad value for {a}: {v!r}"); return 2
            i += 2
            continue
        if a == "--plot":
            want_plot = True
        elif a.startswith("--"):
            print(f"unknown option {a}"); return 2
        elif path is None:
            path = a
        else:
            print("expected one log file"); return 2
        i += 1
    if path is None:
        print(__doc__); return 2

    cfg = read_sketch(sketch)
    M_B, M_Ainv = cfg["M_B"], cfg["M_Ainv"]
    decl, offset = cfg["declination"], cfg["offset"]
    print(f"log    : {path}")
    print(f"sketch : {sketch}")
    print(f"         M_B {np.round(M_B,2)}  declination {decl}  offset {offset}")

    try:
        imu, gps = parse(path, t_from, t_to)
    except OSError as e:
        print(f"cannot read {path}: {e.strerror}"); return 2
    if len(imu) < 100 or len(gps) < 50:
        print(f"\nnot enough data: {len(imu)} imu and {len(gps)} gps records")
        return 2

    t = imu[:, 0]
    acc, mag = imu[:, 1:4], imu[:, 4:7]
    na, nm = np.linalg.norm(acc, axis=1), np.linalg.norm(mag, axis=1)
    clean = (np.abs(na - 1) < 0.01) & (np.abs(nm - 1) < 0.01)
    au = acc / np.maximum(na, 1e-9)[:, None]
    mu = mag / np.maximum(nm, 1e-9)[:, None]
    cog = circ_deg(t, gps[:, 0], gps[:, 3])
    sog = nearest(t, gps[:, 0], gps[:, 4])
    hdg = heading_of(au, mu, decl, offset)
    print(f"         {len(imu)} imu records, {clean.sum()} intact, "
          f"{datetime.datetime.fromtimestamp(t[0]):%H:%M} to "
          f"{datetime.datetime.fromtimestamp(t[-1]):%H:%M}")

    # ---------------------------------------------------------------- find circles
    hr("1. CIRCLES")
    segs = find_circles(t, hdg, sog)
    if segs:
        for a_, b_, tot in segs:
            print(f"   {datetime.datetime.fromtimestamp(t[a_]):%H:%M:%S} "
                  f"to {datetime.datetime.fromtimestamp(t[b_]):%H:%M:%S}  "
                  f"{abs(tot):.0f} deg {'port' if tot < 0 else 'stbd'}, "
                  f"{b_-a_} samples, {np.nanmean(sog[a_:b_]):.1f} kt")
        sel = np.zeros(len(t), bool)
        for a_, b_, _ in segs:
            sel[a_:b_] = True
        sel &= clean
        src = f"{len(segs)} circle(s)"
    else:
        print("   none found.")
        print("   Falling back to the whole log. That works only if you happened to")
        print("   sail all round the compass, and it is contaminated by leeway.")
        sel = clean & np.isfinite(sog) & (sog > 1.0) & (sog < MAX_SOG)
        src = "whole log (no circles)"

    bins = np.unique((hdg[sel] // 30).astype(int) % 12)
    tilt = np.degrees(np.arccos(np.clip(au[sel, 2], -1, 1)))
    print(f"\n   using {sel.sum()} samples from {src}")
    print(f"   heading coverage {len(bins)}/12 thirty-degree bins")
    print(f"   mean tilt {tilt.mean():.1f} deg "
          f"(the horizontal fit assumes the boat is near upright)")
    ok_cover = len(bins) >= MIN_BINS
    ok_tilt = tilt.mean() <= MAX_TILT
    if not ok_cover:
        print(f"   FAIL: need at least {MIN_BINS}/12 bins. Motor a full slow circle.")
    if not ok_tilt:
        print(f"   WARNING: mean tilt over {MAX_TILT} deg, the fit will be degraded.")
    if sel.sum() < 100:
        print("   FAIL: too few samples."); return 1
    if not ok_cover:
        return 1

    # --------------------------------------------------------------------- the fit
    hr("2. HORIZONTAL FIT")
    y, _ = recover_scale(mu, au, dip_expect)
    good = sel & np.all(np.isfinite(y), axis=1)
    if good.sum() < 100:
        print("   FAIL: too few samples after recovering the magnitude."); return 1
    h2, up = level_project(y[good], au[good])
    try:
        cen, W, ecc = ellipse_fit(h2)
    except np.linalg.LinAlgError as e:
        print(f"   FAIL: {e}"); return 1
    rad = np.linalg.norm((h2 - cen) @ W.T, axis=1)
    before = np.linalg.norm(h2, axis=1)
    print(f"   residual hard iron  {np.round(cen,1)} of {MFIELD:.0f} "
          f"= {np.linalg.norm(cen)/MFIELD*100:.1f} % of full field")
    print(f"   residual soft iron  axis ratio {ecc:.3f} "
          f"({'negligible' if ecc < 1.02 else 'significant'})")
    print(f"   circularity         {100*before.std()/before.mean():.2f} % before, "
          f"{100*rad.std()/rad.mean():.2f} % after")

    # express the 2D correction in the body frame (valid while near upright)
    c3 = np.array([cen[0], cen[1], 0.0])
    S = np.eye(3)
    S[:2, :2] = W
    M_B_new = M_B + np.linalg.inv(M_Ainv) @ c3
    M_Ainv_new = S @ M_Ainv

    def corrected(mu_, au_):
        yy, _ = recover_scale(mu_, au_, dip_expect)
        bad = ~np.all(np.isfinite(yy), axis=1)
        yy = np.where(bad[:, None], mu_ * MFIELD, yy)
        v = (yy - c3) @ S.T
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    mu_c = corrected(mu, au)
    hdg_c = heading_of(au, mu_c, decl, offset)

    # --------------------------------------------------------------- heading offset
    hr("3. HEADING OFFSET")
    base = sel & np.isfinite(cog) & (sog > 1.0) & (sog < MAX_SOG)
    for nm_, h_ in (("before", hdg), ("after ", hdg_c)):
        e = wrap180(cog[base] - h_[base])
        e = e[np.abs(e) < 60]
        hh_ = h_[base][np.abs(wrap180(cog[base] - h_[base])) < 60]
        b = harm(hh_, e)
        print(f"   {nm_}: compass reads {-b[0]:+.2f} deg high  "
              f"1-cycle {np.hypot(b[1],b[2]):.2f}  2-cycle {np.hypot(b[3],b[4]):.2f}")
        if nm_ == "after ":
            new_off = offset - b[0]
    print(f"\n   -> INSTALATION_HEADING_OFFSET = {round(new_off)}   (currently {offset})")
    print("      This always moves when M_B moves; the two must be updated together.")

    # ---------------------------------------------------------------- verification
    hr("4. DID IT HELP?")
    dip_b = np.degrees(np.arcsin(np.clip(np.sum(au*mu, axis=1), -1, 1)))
    dip_a = np.degrees(np.arcsin(np.clip(np.sum(au*mu_c, axis=1), -1, 1)))
    hh = np.arange(0, 360, 1.0)
    rows = []
    for nm_, h_, dp in (("before", hdg, dip_b), ("after", hdg_c, dip_a)):
        e = wrap180(cog[base] - h_[base])
        m = np.abs(e) < 60
        b = harm(h_[base][m], e[m])
        cv = curve(b, hh)
        rows.append((nm_, cv.max()-cv.min(), np.hypot(b[1], b[2]), np.hypot(b[3], b[4]),
                     dp[clean].std(), dp[clean].mean()))
    print(f"   {'':7s} {'p-p':>7s} {'1-cyc':>7s} {'2-cyc':>7s} {'dip sd':>8s} {'dip mean':>9s}")
    for r in rows:
        print(f"   {r[0]:7s} {r[1]:7.1f} {r[2]:7.2f} {r[3]:7.2f} {r[4]:8.2f} {r[5]:9.2f}")
    print(f"   expected dip for your location: {dip_expect}")
    improved = rows[1][1] < rows[0][1]
    print(f"\n   {'IMPROVED' if improved else 'NO IMPROVEMENT'}")

    if not improved:
        hr("5. NOTHING TO PASTE")
        print("   The correction did not reduce the error against GPS course, so it is")
        print("   not an improvement and the constants are deliberately withheld.")
        if not segs:
            print("\n   Most likely cause: there were no circles in this log, so the fit")
            print("   ran on ordinary sailing. That is contaminated by leeway, which")
            print("   looks like a compass error but is not one, and the heading")
            print("   coverage is whatever the course happened to give.")
            print("\n   Motor two slow circles at 3+ kt and run this again.")
        else:
            print("\n   The circles were found but did not help. Check that nothing")
            print("   magnetic moved during them, and that they were clear of moored")
            print("   steel boats, jetties and bridges.")
        return 1

    hr("5. PASTE INTO emon_MiniC5A_anemometer.ino")
    print(f"float M_B [3] = {{{M_B_new[0]:.2f}, {M_B_new[1]:.2f}, {M_B_new[2]:.2f}}};")
    print()
    print("float M_Ainv[3][3] = {")
    for r in range(3):
        end = "};" if r == 2 else ","
        print(f"{{ {M_Ainv_new[r,0]:.5f}, {M_Ainv_new[r,1]:.5f}, "
              f"{M_Ainv_new[r,2]:.5f} }}{end}")
    print()
    print(f"const int INSTALATION_HEADING_OFFSET = {round(new_off)};")
    print("\n   The Z row and column come from your bench calibration and are left as")
    print("   they were. A boat cannot measure them: turning in yaw never tips the")
    print("   sensor, so the vertical terms are not excited by this data.")

    if want_plot:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("\n(--plot needs matplotlib)")
            return 0 if improved else 1
        fig, ax = plt.subplots(1, 2, figsize=(11, 5))
        ax[0].scatter(h2[:, 0], h2[:, 1], s=4, label="as logged")
        q = (h2 - cen) @ W.T
        ax[0].scatter(q[:, 0], q[:, 1], s=4, label="corrected")
        ax[0].axhline(0, lw=.5, color="k"); ax[0].axvline(0, lw=.5, color="k")
        ax[0].set_aspect("equal"); ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)
        ax[0].set_title("field in the horizontal plane")
        for nm_, h_ in (("before", hdg), ("after", hdg_c)):
            e = wrap180(cog[base] - h_[base]); m = np.abs(e) < 60
            ax[1].plot(hh, -curve(harm(h_[base][m], e[m]), hh), label=nm_)
        ax[1].axhline(0, lw=.5, color="k"); ax[1].grid(alpha=.3)
        ax[1].set_xlabel("heading"); ax[1].set_ylabel("compass error, deg high")
        ax[1].legend(fontsize=8); ax[1].set_title("deviation vs GPS course")
        plt.tight_layout(); plt.show()
    return 0 if improved else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
