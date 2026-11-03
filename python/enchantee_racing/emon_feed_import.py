"""Find pyemonlib.emon_feed, wherever this app happens to be running from.

emon_feed is the shared definition of the boat's envelope format and of the angles the
whole suite agrees on: TWA, AWA, leeway and heel, which were this app's own maths before
they were moved there (PLAN 1b). Importing it here rather than keeping a second copy is
what stops the two drifting.

It is standard library only, so it costs this image nothing. The pyemonlib wheel and its
compiled emonSuite extension are still not installed: this app is python:3.13-slim with
paho and nothing else, and the Dockerfile's note explains why that is deliberate.

Three places are tried, in order:

  ../pyEmon          a full checkout, which is how the tests and a laptop run it
  /python/pyEmon     a mounted source tree, as emon_live's compose provides
  /opt/pyemonlib     the copy the Dockerfile puts in the image

The checkout comes first so an edit to emon_feed is live without a rebuild, as it is for
emon_live. The image's own copy comes last so the app still runs with no bind mount at
all, which is the rule the rest of this app follows.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

CANDIDATES = (
    os.path.join(os.path.dirname(_HERE), "pyEmon"),
    "/python/pyEmon",
    "/opt/pyemonlib",
)


def _locate() -> str:
    for candidate in CANDIDATES:
        if os.path.isdir(os.path.join(candidate, "pyemonlib")):
            return candidate
    raise ImportError(
        "pyemonlib not found. Looked in: " + ", ".join(CANDIDATES) + ".\n"
        "The app needs emon_feed to read the boat's envelopes. In a checkout it is at "
        "python/pyEmon; in the container the Dockerfile copies it to /opt/pyemonlib.")


SOURCE = _locate()
if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)

from pyemonlib import emon_feed  # noqa: E402

__all__ = ["emon_feed", "SOURCE", "CANDIDATES"]
