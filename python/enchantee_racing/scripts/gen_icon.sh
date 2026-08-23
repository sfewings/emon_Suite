#!/bin/bash
# Render static/icon.svg to the PNGs iOS and the manifest need.
#
#   scripts/gen_icon.sh
#
# Writes static/icon-180.png (apple-touch-icon) and static/icon-512.png (manifest).
# Both outputs are committed, so this only has to run again if the artwork changes.
#
# Why PNG at all, when the SVG is right there: iOS does not accept an SVG for
# apple-touch-icon. The manifest would take the SVG, but pointing both at one PNG each
# keeps the two in step and needs no per-browser reasoning.
#
# Why chromium out of a container. The Pi has no image library installed and no internet
# on the water to fetch one, but it already carries sfewings32/emon_event_recorder, whose
# image bundles chromium for the folium map export. Borrowing it costs nothing and adds no
# dependency to this project. That does mean this script is a dockside tool like
# gen_audio.py: it needs that image present, so run it before the boat leaves.
#
# Each size is rendered by laying the page out at that size, not by scaling a 512 px
# render. --force-device-scale-factor was the obvious way and it silently does not work:
# chromium clamps the factor at 0.5, so asking for 180/512 produced a 256 px file named
# icon-180.png. The test that checks each PNG's real dimensions against the size the
# manifest declares is what caught it. The artwork is an SVG, so laying it out at the
# target size costs nothing and is exact.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(dirname "$HERE")"
IMAGE="sfewings32/emon_event_recorder:latest"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "error: $IMAGE is not present, and it carries the chromium this needs." >&2
    echo "       docker pull $IMAGE   (needs the dock wifi)" >&2
    exit 1
fi

# The wrapper strips the default margin and pins the page to the artwork's own size, so
# the screenshot is the icon and nothing else. Written into the mounted directory rather
# than /tmp so chromium can reach it, and removed afterwards.
WRAP="$APP/static/.icon-wrap.html"
trap 'rm -f "$WRAP"' EXIT

for size in 180 512; do
    cat > "$WRAP" <<HTML
<!doctype html>
<meta charset="utf-8">
<style>
  html, body { margin: 0; padding: 0; background: #000; }
  img { display: block; width: ${size}px; height: ${size}px; }
</style>
<img src="icon.svg" alt="">
HTML
    docker run --rm --network none \
        -v "$APP/static:/art" \
        --entrypoint sh "$IMAGE" -c "
            chromium --headless --no-sandbox --disable-gpu --hide-scrollbars \
                --default-background-color=000000ff \
                --window-size=$size,$size \
                --screenshot=/art/icon-$size.png \
                file:///art/.icon-wrap.html >/dev/null 2>&1
        "
    # chromium runs as root in the container, so the file lands root-owned in a directory
    # the user owns, and the next run or a hand edit would need sudo. Hand it back.
    # Done here rather than with docker run --user, because chromium wants a writable
    # HOME and giving it one is more moving parts than one chown.
    docker run --rm --network none -v "$APP/static:/art" --entrypoint sh "$IMAGE" \
        -c "chown $(id -u):$(id -g) /art/icon-$size.png"
    printf 'static/icon-%s.png  %s bytes\n' "$size" "$(stat -c %s "$APP/static/icon-$size.png")"
done

echo "done. Both are committed, so this need not run again unless icon.svg changes."
