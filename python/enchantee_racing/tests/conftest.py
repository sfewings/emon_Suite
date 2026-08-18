"""Put the project root on sys.path so tests import the way the app does.

There is no packaging step. The app is deployed by copying the directory onto the
Pi and running app.py, so `from engine import nav` has to work from the root
without an install.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
