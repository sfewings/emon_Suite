"""Test the pyemonlib source in this checkout, with whatever emonSuite build is installed.

The source tree has no compiled emonSuite extension; an installed wheel does. So the
source directory goes first on sys.path, and if it holds no build of the extension, the
installed package's directory is appended to pyemonlib.__path__, which lets
`import pyemonlib.emonSuite` find the compiled module while every .py file comes from here.

emon_feed tests need none of this and run on any Python with pytest. Tests that need the
extension are skipped when no build is installed (HAS_EMONSUITE).
"""

import os
import sys

PYEMON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(PYEMON))           # emon_Suite
if PYEMON not in sys.path:
    sys.path.insert(0, PYEMON)

import pyemonlib  # noqa: E402

_source = os.path.abspath(pyemonlib.__path__[0])


def _has_build(directory):
    try:
        return any(f.startswith("emonSuite") and f.endswith((".pyd", ".so"))
                   for f in os.listdir(directory))
    except OSError:
        return False


if not _has_build(_source):
    for entry in sys.path:
        candidate = os.path.abspath(os.path.join(entry, "pyemonlib"))
        if candidate != _source and _has_build(candidate):
            pyemonlib.__path__.append(candidate)
            break

try:
    import pyemonlib.emonSuite  # noqa: F401,E402
    HAS_EMONSUITE = True
except ImportError:
    HAS_EMONSUITE = False
