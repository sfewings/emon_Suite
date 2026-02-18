#!/usr/bin/env python3
"""
Read yaw, roll, pitch (CSV) from serial (default COM4, 115200) and animate a 3D wireframe
object rotated by the incoming Euler angles.

Usage:
  python wireFramePitchRollYaw.py --port COM4 --baud 115200

Requires: pyserial, matplotlib, numpy
  pip install pyserial matplotlib numpy
"""
import argparse
import sys
import math
import time
from collections import deque

import numpy as np
import serial
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from matplotlib.animation import FuncAnimation

com_port = "/dev/tty.usbserial-A50285BI"
# CLI
parser = argparse.ArgumentParser(description="Plot yaw,roll,pitch from serial as rotating wireframe")
parser.add_argument("--port", "-p", default=com_port, help="serial port (e.g. COM4 or /dev/ttyUSB0)")
parser.add_argument("--baud", "-b", type=int, default=115200, help="baud rate")
parser.add_argument("--history", "-n", type=int, default=100, help="trail length")
args = parser.parse_args()

# open serial
try:
    ser = serial.Serial(args.port, args.baud, timeout=0.05)
except Exception as e:
    print("Failed to open serial port:", e, file=sys.stderr)
    sys.exit(1)

# globals for latest angles (degrees)
last_yaw = 0.0    # expected 0..360
last_roll = 0.0   # expected -180..180
last_pitch = 0.0  # expected -180..180

# history (optional trail of orientations applied to a marker)
hist_pts = deque(maxlen=args.history)

# add history deques for X and Y axis endpoints
hist_x = deque(maxlen=args.history)
hist_y = deque(maxlen=args.history)

# create 3D figure
fig = plt.figure(figsize=(8, 7))
ax = fig.add_subplot(111, projection="3d")
ax.set_xlim3d(-1.2, 1.2)
ax.set_ylim3d(-1.2, 1.2)
ax.set_zlim3d(-1.2, 1.2)
ax.set_xlabel("X")
ax.set_ylabel("Y")
ax.set_zlabel("Z")
ax.set_title("Wireframe rotated by Yaw(Z), Pitch(Y), Roll(X)")

# build a wireframe cube centered at origin, size 2 (covers -1..1)
def cube_wireframe(size=2.0):
    s = size / 2.0
    corners = np.array([
        [-s, -s, -s],
        [ s, -s, -s],
        [ s,  s, -s],
        [-s,  s, -s],
        [-s, -s,  s],
        [ s, -s,  s],
        [ s,  s,  s],
        [-s,  s,  s],
    ])
    edges = [
        (0,1),(1,2),(2,3),(3,0),
        (4,5),(5,6),(6,7),(7,4),
        (0,4),(1,5),(2,6),(3,7)
    ]
    return corners, edges

base_corners, base_edges = cube_wireframe(2.0)

# plot initial wireframe and keep line artists and original endpoints
edge_lines = []
edge_orig = []
for a,b in base_edges:
    p1 = base_corners[a]
    p2 = base_corners[b]
    (ln,) = ax.plot([p1[0], p2[0]], [p1[1], p2[1]], [p1[2], p2[2]],
                    color="gray", linewidth=1.0, alpha=0.8)
    edge_lines.append(ln)
    edge_orig.append((p1.copy(), p2.copy()))

# axis arrows
axis_lines = {}
axis_lines['x'], = ax.plot([0,1.0],[0,0],[0,0], color='r', linewidth=2)
axis_lines['y'], = ax.plot([0,0],[0,1.0],[0,0], color='g', linewidth=2)
axis_lines['z'], = ax.plot([0,0],[0,0],[0,1.0], color='b', linewidth=2)

# marker at cube front center to show orientation / history trail
marker, = ax.plot([0],[0],[0], marker='o', color='orange')
trail_scatter = ax.scatter([], [], [], color='orange', s=8, alpha=0.5)

# add red and green history markers + trails for X and Y axes
x_marker, = ax.plot([0],[0],[0], marker='o', color='red')
x_trail_scatter = ax.scatter([], [], [], color='red', s=6, alpha=0.4)
y_marker, = ax.plot([0],[0],[0], marker='o', color='green')
y_trail_scatter = ax.scatter([], [], [], color='green', s=6, alpha=0.4)

# rotation helpers (degrees -> radians)
def R_x(rad):
    c = math.cos(rad); s = math.sin(rad)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]])

def R_y(rad):
    c = math.cos(rad); s = math.sin(rad)
    return np.array([[c,0,s],[0,1,0],[-s,0,c]])

def R_z(rad):
    c = math.cos(rad); s = math.sin(rad)
    return np.array([[c,-s,0],[s,c,0],[0,0,1]])

def compose_rotation(yaw_deg, pitch_deg, roll_deg):
    """
    Compose rotation matrix from Euler angles in degrees.
    Angles expected:
      - yaw (Z) : 0..360
      - pitch (Y): -180..180
      - roll (X) : -180..180

    Rotation order: apply roll about X, then pitch about Y, then yaw about Z:
      R = Rz(yaw) * Ry(pitch) * Rx(roll)
    """
    # convert degrees to radians
    y = math.radians(yaw_deg)
    p = math.radians(pitch_deg)
    r = math.radians(roll_deg)
    return R_z(y) @ R_y(p) @ R_x(r)

# normalize helpers
def normalize_yaw(y):
    # bring into [0,360)
    return (y % 360.0 + 360.0) % 360.0

def normalize_angle_pm180(a):
    # bring into [-180, 180)
    a = (a + 180.0) % 360.0 - 180.0
    return a

# serial reading: read lines, accept three comma separated floats [yaw, roll, pitch]
def try_read_serial():
    global last_yaw, last_roll, last_pitch
    newest = None
    try:
        while True:
            line = ser.readline()
            if not line:
                break
            try:
                s = line.decode('ascii', errors='ignore').strip()
            except Exception:
                continue
            if not s:
                continue
            parts = [p.strip() for p in s.split(',') if p.strip()!='']
            print(parts)
            if len(parts) < 3:
                continue
            try:
                # input order yaw, roll, pitch (as requested)
                vals = [float(parts[0]), float(parts[1]), float(parts[2])]
            except ValueError:
                continue
            newest = vals
    except Exception:
        newest = None

    if newest is not None:
        yaw_in, roll_in, pitch_in = newest[0], newest[1], newest[2]

        # normalize according to ranges supplied by user
        yaw = normalize_yaw(yaw_in)
        roll = normalize_angle_pm180(roll_in)
        pitch = normalize_angle_pm180(pitch_in)

        last_yaw, last_roll, last_pitch = yaw, roll, pitch

        # add a point on cube front face center transformed by current rotation for trail
        R = compose_rotation(last_yaw, last_pitch, last_roll)
        front_center = np.array([0, 0, 1.0])  # front face center (z=+1)
        p = R.dot(front_center)
        hist_pts.append(p)

# animation update
def update(frame):
    try_read_serial()

    # compute rotation matrix
    R = compose_rotation(last_yaw, last_pitch, last_roll)

    # update cube edges
    for idx, (p1, p2) in enumerate(edge_orig):
        pts = np.vstack((p1, p2))
        r = (R @ pts.T).T
        edge_lines[idx].set_data([r[0,0], r[1,0]], [r[0,1], r[1,1]])
        edge_lines[idx].set_3d_properties([r[0,2], r[1,2]])

    # update axes (rotated)
    x_end = R.dot(np.array([1.0,0,0]))
    y_end = R.dot(np.array([0,1.0,0]))
    z_end = R.dot(np.array([0,0,1.0]))
    axis_lines['x'].set_data([0, x_end[0]], [0, x_end[1]])
    axis_lines['x'].set_3d_properties([0, x_end[2]])
    axis_lines['y'].set_data([0, y_end[0]], [0, y_end[1]])
    axis_lines['y'].set_3d_properties([0, y_end[2]])
    axis_lines['z'].set_data([0, z_end[0]], [0, z_end[1]])
    axis_lines['z'].set_3d_properties([0, z_end[2]])

    # append axis endpoints to their history deques
    hist_x.append(x_end)
    hist_y.append(y_end)

    # update X axis history marker + trail (red)
    if hist_x:
        arrx = np.array(hist_x)
        x_marker.set_data([arrx[-1,0]], [arrx[-1,1]])
        x_marker.set_3d_properties([arrx[-1,2]])
        x_trail_scatter._offsets3d = (arrx[:,0], arrx[:,1], arrx[:,2])
    else:
        x_marker.set_data([0],[0]); x_marker.set_3d_properties([0])
        x_trail_scatter._offsets3d = ([],[],[])

    # update Y axis history marker + trail (green)
    if hist_y:
        arry = np.array(hist_y)
        y_marker.set_data([arry[-1,0]], [arry[-1,1]])
        y_marker.set_3d_properties([arry[-1,2]])
        y_trail_scatter._offsets3d = (arry[:,0], arry[:,1], arry[:,2])
    else:
        y_marker.set_data([0],[0]); y_marker.set_3d_properties([0])
        y_trail_scatter._offsets3d = ([],[],[])

    # update marker at front center transformed
    if hist_pts:
        arr = np.array(hist_pts)
        marker.set_data([arr[-1,0]], [arr[-1,1]])
        marker.set_3d_properties([arr[-1,2]])
        trail_scatter._offsets3d = (arr[:,0], arr[:,1], arr[:,2])
    else:
        marker.set_data([0],[0]); marker.set_3d_properties([0])
        trail_scatter._offsets3d = ([],[],[])

    # show numeric angles in title (yaw shown 0..360, roll/pitch -180..180)
    ax.set_title(f"Yaw(Z)={last_yaw:.1f}°  Pitch(Y)={last_pitch:.1f}°  Roll(X)={last_roll:.1f}°")

    # include new artists in return list
    return edge_lines + list(axis_lines.values()) + [marker, trail_scatter, 
           x_marker, x_trail_scatter, y_marker, y_trail_scatter]

ani = FuncAnimation(fig, update, interval=50, blit=False)

try:
    plt.show()
finally:
    try:
        ser.close()
    except Exception:
        pass