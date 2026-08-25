#!/usr/bin/env python3
"""Build a one-page A4 PDF of QR codes for every Enchantee service.

Phones cannot easily be told to type http://enchantee.local/portainer/, so this
is the sheet you print and stick up: scan to join the hotspot, then scan to open
whichever service you want.

    sudo ./make-qr-sheet.py [output.pdf]

sudo is needed only to read the hotspot passphrase out of NetworkManager for the
join code. Without it the sheet still builds, but the wifi card is emitted
without the passphrase and the phone will prompt for it.

The passphrase is read at run time and never stored here, which is why this repo
holds the generator rather than the finished PDF. Keep the generated PDF out of
git: it contains the hotspot password in scannable form.

The heads-up display card points at /hud, which nginx redirects to /race/hud, the
racing app's ported HUD. The Node-RED original stays reachable at /nodered/hud for
the side-by-side comparison (DESIGN 13 steps 3 and 4) but is deliberately not on
this sheet: two cards captioned "heads-up display" is worse than one, and /hud is
the URL that survives the Node-RED tab being retired.

Needs only reportlab, which is already installed; its built-in QR widget draws
vector codes that stay sharp at any print size.
"""
import subprocess
import sys

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

SSID = "Enchantee"
HOST = "http://enchantee.local"

INK = HexColor("#101418")
MUTED = HexColor("#5b6670")
RULE = HexColor("#c8d0d6")
ACCENT = HexColor("#1f6feb")

# (title, url path, one-line description)
SERVICES = [
    ("Main display",     "/",              "Node-RED dashboard, the usual screen"),
    ("Heads-up display", "/hud",           "Large-format live readout"),
    ("Charts",           "/grafana/",      "Grafana history for all activities"),
    ("Event recorder",   "/events/",       "Track logs, photos and publishing"),
    ("Sensor settings",  "/settings/",     "Sensor configuration"),
    ("Portainer",        "/portainer/",    "Docker container console"),
]


def wifi_passphrase():
    """Read the hotspot PSK from NetworkManager. Returns None if not permitted."""
    try:
        out = subprocess.run(
            ["nmcli", "-s", "-g", "802-11-wireless-security.psk",
             "connection", "show", SSID.lower()],
            capture_output=True, text=True, timeout=10, check=True)
        return out.stdout.strip() or None
    except Exception:
        return None


def wifi_payload(psk):
    """WIFI: URI per the de-facto standard both iOS and Android camera apps read."""
    def esc(s):
        for ch in '\\;,:"':
            s = s.replace(ch, "\\" + ch)
        return s
    if psk:
        return f"WIFI:T:WPA;S:{esc(SSID)};P:{esc(psk)};;"
    return f"WIFI:T:nopass;S:{esc(SSID)};;"


def draw_qr(c, payload, x, y, size):
    """Draw a QR of exactly `size` points with its lower-left corner at x, y."""
    widget = qr.QrCodeWidget(payload, barLevel="M")
    b = widget.getBounds()
    d = Drawing(size, size,
                transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x, y)


def centred(c, text, cx, y, font, size, colour):
    c.setFont(font, size)
    c.setFillColor(colour)
    c.drawCentredString(cx, y, text)


def build(path):
    psk = wifi_passphrase()
    W, H = A4
    m = 15 * mm
    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle("Enchantee services")

    # ---- header -----------------------------------------------------------
    y = H - m
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(m, y - 20, "Enchantee")
    c.setFont("Helvetica", 11)
    c.setFillColor(MUTED)
    c.drawRightString(W - m, y - 19, "Scan with your phone camera")
    y -= 32
    c.setStrokeColor(RULE)
    c.setLineWidth(1)
    c.line(m, y, W - m, y)
    y -= 12

    # ---- step 1: join the wifi -------------------------------------------
    card_h = 46 * mm
    qr_size = 36 * mm
    c.setFillColor(HexColor("#f2f6f9"))
    c.roundRect(m, y - card_h, W - 2 * m, card_h, 6, stroke=0, fill=1)
    draw_qr(c, wifi_payload(psk), m + 7 * mm, y - card_h + (card_h - qr_size) / 2, qr_size)

    tx = m + 7 * mm + qr_size + 8 * mm
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(tx, y - 13 * mm, "STEP 1")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(tx, y - 20 * mm, f"Join the {SSID} wifi")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 10)
    if psk:
        c.drawString(tx, y - 27 * mm, "Scan to join. Only needed when the Pi is running")
        c.drawString(tx, y - 32 * mm, "its own hotspot, not when it is on a house network.")
    else:
        c.drawString(tx, y - 27 * mm, f"Scan to join network \"{SSID}\", then enter the")
        c.drawString(tx, y - 32 * mm, "passphrase when your phone asks for it.")
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(tx, y - 38 * mm, "Already on the boat wifi? Skip straight to step 2.")
    y -= card_h + 9 * mm

    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(m, y, "STEP 2")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(m + 17 * mm, y, "Scan whichever screen you want")
    y -= 6 * mm

    # ---- service grid -----------------------------------------------------
    cols, gap = 2, 8 * mm
    cw = (W - 2 * m - gap) / cols
    ch = 52 * mm
    q = 30 * mm

    for i, (title, path_, desc) in enumerate(SERVICES):
        col, row = i % cols, i // cols
        cx = m + col * (cw + gap)
        cy = y - (row + 1) * ch - row * (3 * mm)

        c.setStrokeColor(RULE)
        c.setLineWidth(0.8)
        c.roundRect(cx, cy, cw, ch, 5, stroke=1, fill=0)

        draw_qr(c, HOST + path_, cx + (cw - q) / 2, cy + ch - q - 6 * mm, q)

        mid = cx + cw / 2
        centred(c, title, mid, cy + 12 * mm, "Helvetica-Bold", 12, INK)
        shown = ("enchantee.local" + path_).rstrip("/") if path_ != "/" else "enchantee.local"
        centred(c, shown, mid, cy + 7.5 * mm, "Helvetica-Bold", 9, ACCENT)
        centred(c, desc, mid, cy + 3.5 * mm, "Helvetica", 7.5, MUTED)

    # ---- footer -----------------------------------------------------------
    fy = m + 4 * mm
    c.setStrokeColor(RULE)
    c.line(m, fy + 9 * mm, W - m, fy + 9 * mm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(m, fy + 5 * mm,
                 "These addresses work both on the Enchantee hotspot and when the Pi has joined a wifi network.")
    c.drawString(m, fy + 1.5 * mm,
                 "If a name will not open on an Android phone, check Settings > Network > Private DNS is Off or Automatic.")
    c.showPage()
    c.save()
    return psk is not None


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/home/pi/enchantee-urls.pdf"
    had_psk = build(out)
    print(f"wrote {out}")
    if not had_psk:
        print("note: hotspot passphrase not readable, wifi code emitted without it "
              "(re-run with sudo to embed it)", file=sys.stderr)
    else:
        print("note: this PDF contains the hotspot passphrase in scannable form; "
              "do not commit it to git")
