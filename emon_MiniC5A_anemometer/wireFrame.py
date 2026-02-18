#!/usr/bin/env python3
"""
Real-time 3D plot of 6-value CSV stream from serial (baud 115200).

Each incoming line must be 6 or 7 comma-separated floats in range [-1.0, 1.0]:
  ax,ay,az, mx,my,mz [, heading_degrees]

If a 7th value is present it is interpreted as heading (degrees, 0..360)
and displayed as a small compass on the same figure.

Visualization:
 - A wireframe unit-cube for acceleration (blue)
 - A wireframe unit-cube for magnetometer (red)
 - A vector (arrow) from origin to the accel (blue) and mag (red) readings
 - A small inset compass showing heading as an arrow and text
 - Plot updates in real-time (matplotlib animation)

Usage:
  python3 wireFrame.py --port COM4
Requires: pyserial, matplotlib, numpy
  pip install pyserial matplotlib numpy
"""
import argparse
import sys
import time
import math
from collections import deque

import numpy as np
import serial
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from matplotlib.animation import FuncAnimation

# parse command line
parser = argparse.ArgumentParser(description="Plot accel+mag (6 CSV values) from serial port")
parser.add_argument("--port", "-p", default="COM4", help="serial port (e.g. /dev/ttyUSB0 or COM3)")
parser.add_argument("--baud", "-b", type=int, default=115200, help="baud rate (default 115200)")
parser.add_argument("--history", "-n", type=int, default=200, help="number of recent vectors to keep (for faint trail)")
args = parser.parse_args()

# open serial
try:
    ser = serial.Serial(args.port, args.baud, timeout=0.05)
except Exception as e:
    print("Failed to open serial port:", e, file=sys.stderr)
    sys.exit(1)

# last valid sample
last_ax, last_ay, last_az = 0.0, 0.0, 0.0
last_mx, last_my, last_mz = 0.0, 0.0, 0.0
last_heading = 0.0  # degrees

# history for faint trail
hist_acc = deque(maxlen=args.history)
hist_mag = deque(maxlen=args.history)

# create figure
fig = plt.figure(figsize=(9, 7))
ax3 = fig.add_subplot(111, projection="3d")
ax3.set_xlim3d(-1.1, 1.1)
ax3.set_ylim3d(-1.1, 1.1)
ax3.set_zlim3d(-1.1, 1.1)
ax3.set_xlabel("X")
ax3.set_ylabel("Y")
ax3.set_zlabel("Z")
ax3.set_title("Accel (blue) and Mag (red) - vectors normalized [-1..1]")

# draw unit-cube wireframe function
def cube_wireframe(center=(0, 0, 0), size=1.0):
    cx, cy, cz = center
    s = size / 2.0
    # 8 corners
    corners = np.array([
        [cx - s, cy - s, cz - s],
        [cx + s, cy - s, cz - s],
        [cx + s, cy + s, cz - s],
        [cx - s, cy + s, cz - s],
        [cx - s, cy - s, cz + s],
        [cx + s, cy - s, cz + s],
        [cx + s, cy + s, cz + s],
        [cx - s, cy + s, cz + s],
    ])
    # edges as index pairs
    edges = [
        (0,1),(1,2),(2,3),(3,0),  # bottom
        (4,5),(5,6),(6,7),(7,4),  # top
        (0,4),(1,5),(2,6),(3,7)   # verticals
    ]
    lines = []
    for a,b in edges:
        lines.append((corners[a], corners[b]))
    return lines

# prepare static wireframes (both cubes centered at origin)
cube_acc_lines = cube_wireframe(size=2.0)   # full span -1..1
cube_mag_lines = cube_wireframe(size=2.0)

# plot static wireframes and keep references to the line collections
acc_wire_artists = []
mag_wire_artists = []
for (p1, p2) in cube_acc_lines:
    (l,) = ax3.plot([p1[0], p2[0]], [p1[1], p2[1]], [p1[2], p2[2]], color="blue", linestyle="--", linewidth=0.5, alpha=0.6)
    acc_wire_artists.append(l)
for (p1, p2) in cube_mag_lines:
    (l,) = ax3.plot([p1[0], p2[0]], [p1[1], p2[1]], [p1[2], p2[2]], color="red", linestyle="-", linewidth=0.5, alpha=0.6)
    mag_wire_artists.append(l)

# quiver arrows for current vectors (matplotlib quiver in 3D is awkward; we draw simple line approximation)
acc_vec_line, = ax3.plot([0, last_ax], [0, last_ay], [0, last_az], color="blue", linewidth=2.5)
mag_vec_line, = ax3.plot([0, last_mx], [0, last_my], [0, last_mz], color="red", linewidth=2.5)

# faint trails
acc_trail_scatter = ax3.scatter([], [], [], color="blue", s=6, alpha=0.25)
mag_trail_scatter = ax3.scatter([], [], [], color="red", s=6, alpha=0.25)

# --- Compass inset axes ---
# small square inset in upper-right of figure
comp_ax = fig.add_axes([0.78, 0.78, 0.18, 0.18], polar=False)
comp_ax.set_xlim(-1.2, 1.2)
comp_ax.set_ylim(-1.2, 1.2)
comp_ax.set_aspect('equal')
comp_ax.axis('off')  # hide axes
# draw circle
circle = plt.Circle((0,0), 1.0, fill=False, edgecolor='k', linewidth=1.0, alpha=0.7)
comp_ax.add_patch(circle)
# draw N/E/S/W labels
comp_ax.text(0.0, 1.05, "N", ha='center', va='bottom', fontsize=9)
comp_ax.text(1.05, 0.0, "E", ha='left',   va='center', fontsize=9)
comp_ax.text(0.0, -1.05, "S", ha='center', va='top', fontsize=9)
comp_ax.text(-1.05, 0.0, "W", ha='right',  va='center', fontsize=9)
# initial arrow and heading text
comp_arrow_line, = comp_ax.plot([0, 0], [0, 1.0], color='green', linewidth=2.5, marker='o')  # points to north initially
comp_text = comp_ax.text(0.0, -1.2, "0.0°", ha='center', va='top', fontsize=9)

def try_read_serial():
    """Read available lines from serial and update last_* variables with the most recent valid sample."""
    global last_ax, last_ay, last_az, last_mx, last_my, last_mz, last_heading
    nxt = None
    # read as many full lines as available (non-blocking)
    try:
        while True:
            line = ser.readline()
            if not line:
                break
            try:
                s = line.decode("ascii", errors="ignore").strip()
            except Exception:
                continue
            if not s:
                continue
            parts = s.split(",")
            if len(parts) < 6:
                # ignore malformed lines
                continue
            try:
                # parse first six values
                vals = [float(p) for p in parts[:6]]
            except ValueError:
                continue
            # clamp to [-1,1]
            vals = [max(-1.0, min(1.0, v)) for v in vals]
            heading = None
            if len(parts) >= 7:
                try:
                    heading = float(parts[6])
                    # normalize heading into 0..360
                    heading = (heading % 360.0 + 360.0) % 360.0
                except ValueError:
                    heading = None
            nxt = (vals, heading)
    except Exception:
        nxt = None

    if nxt is not None:
        (vals, heading) = nxt
        axv, ayv, azv, mxv, myv, mzv = vals
        last_ax, last_ay, last_az = axv, ayv, azv
        last_mx, last_my, last_mz = mxv, myv, mzv
        if heading is not None:
            last_heading = heading
        # push to history
        hist_acc.append((axv, ayv, azv))
        hist_mag.append((mxv, myv, mzv))

def update(frame):
    # poll serial for newest sample(s)
    try_read_serial()

    # update accel vector line
    acc_vec_line.set_data([0, last_ax], [0, last_ay])
    acc_vec_line.set_3d_properties([0, last_az])
    # update mag vector line
    mag_vec_line.set_data([0, last_mx], [0, last_my])
    mag_vec_line.set_3d_properties([0, last_mz])

    # update trails
    if hist_acc:
        acc_arr = np.array(hist_acc)
        acc_trail_scatter._offsets3d = (acc_arr[:,0], acc_arr[:,1], acc_arr[:,2])
    else:
        acc_trail_scatter._offsets3d = ([], [], [])
    if hist_mag:
        mag_arr = np.array(hist_mag)
        mag_trail_scatter._offsets3d = (mag_arr[:,0], mag_arr[:,1], mag_arr[:,2])
    else:
        mag_trail_scatter._offsets3d = ([], [], [])

    # update compass inset using last_heading
    # Convert heading (deg, 0 = North, increasing clockwise) to Cartesian for plotting:
    # angle_rad = radians(90 - heading) -> 0 deg => pointing up (0,1)
    angle_rad = math.radians(90.0 - last_heading)
    length = 0.9
    dx = math.cos(angle_rad) * length
    dy = math.sin(angle_rad) * length
    comp_arrow_line.set_data([0, dx], [0, dy])
    comp_text.set_text(f"{last_heading:.1f}°")

    return acc_vec_line, mag_vec_line, acc_trail_scatter, mag_trail_scatter, comp_arrow_line, comp_text

# start animation
ani = FuncAnimation(fig, update, interval=50, blit=False)

try:
    plt.show()
finally:
    try:
        ser.close()
    except Exception:
        pass