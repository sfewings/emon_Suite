#!/bin/bash

# Used in Docker build to set platform dependent variables.
#
# Picks the pyemonlib wheel matching this image and writes its filename to
# /.platform_whl, which the Dockerfile then pip installs.
#
# The Python tag is read from the interpreter in the image rather than written here as a
# constant: a base image moving from 3.13 to 3.14 then picks the right wheel, or fails
# saying which one is missing, instead of installing one built for another Python.
#
# amd64 used to name pyemonlib-0.1.0-cp314-cp314-win_amd64.whl, a *Windows* wheel, which
# cannot install on Linux: every amd64 build of the four images that use this script was
# broken. Fixed 3 Nov 2026, with a linux_x86_64 wheel built to go with it.

set -e

PYTAG=$(python3 -c 'import sys; print("cp%d%d" % sys.version_info[:2])')

case "$TARGETARCH" in
    "amd64")
        PLATTAG=linux_x86_64
        ;;
    "arm64")
        PLATTAG=linux_aarch64
        ;;
    "arm")
        PLATTAG=linux_armv7l
        ;;
    *)
        echo "platform.sh: unsupported TARGETARCH '$TARGETARCH'" >&2
        exit 1
        ;;
esac

WHEEL="pyemonlib-0.1.0-${PYTAG}-${PYTAG}-${PLATTAG}.whl"

# Loudly, and naming what is there. A missing wheel used to surface as a pip error about
# a filename with no explanation of where it should have come from.
if [ ! -f "$WHEEL" ]; then
    echo "platform.sh: $WHEEL not found." >&2
    echo "  TARGETARCH=$TARGETARCH, python $(python3 -V 2>&1)" >&2
    echo "  Build it from python/pyEmon (DESIGN 9.3: the wheel before the images)." >&2
    echo "  Wheels present:" >&2
    ls -1 pyemonlib-*.whl >&2 2>/dev/null || echo "    (none)" >&2
    exit 1
fi

echo "$WHEEL" > /.platform_whl
echo "platform.sh: $TARGETARCH -> $WHEEL"
