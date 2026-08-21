# Sail racing support app for Enchantee (DESIGN.md, CLAUDE.md in this directory).
#
# Flask on port 5002, behind the Pi's existing nginx front door at /race/, subscribing
# to the boat's mosquitto for instrument readings and position.
#
# Build context is python/, not this directory, because that is what build.sh and
# build.cmd pass. Hence every COPY path starts with enchantee_racing/.
#
#   ./build.sh -c enchantee_racing            # local
#   ./build.sh -m push -c enchantee_racing    # multi-platform, to Docker Hub
#
# Three deliberate choices, each of which has a reason that is easy to undo by accident:
#
# 1. python:3.13-slim, not the python:3.13 base the other python/*.Dockerfile images
#    share. Those share a base layer because they all install numpy and the pyemonlib
#    wheel; this app needs neither. Its engine is standard library only and it talks to
#    the broker through paho directly, so it has no use for the ~800 MB of shared
#    layers, and slim is the same interpreter version the app is tested against on the
#    Pi. event_recorder set this precedent with python:3.11-slim.
#
# 2. The COPY list is an allow-list, naming each thing the app serves. It is NOT
#    `COPY enchantee_racing/ ./`. docs/reference/ holds the club's fixtures PDF and the
#    Geng course marks chart; the latter is copyright Geng Pty Ltd and carries a notice
#    against redistribution, and DESIGN 6 records the decision to keep it in the
#    repository as internal reference material while keeping it out of anything the app
#    publishes. This image is pushed to a public registry, so copying the directory
#    wholesale would redistribute it. An allow-list cannot leak a file that is added to
#    docs/ later; a deny-list can. Dockerfile.dockerignore beside this file excludes the
#    same paths again, which is about build speed rather than safety: docs/ and tests/
#    are 6.6 MB of the 7.4 MB this directory contributes to the context.
#
# 3. PYTHONDONTWRITEBYTECODE. In the deployment the whole app directory is bind-mounted
#    from the working tree so the crew can edit config, and the front end, from a laptop
#    on a jetty (CLAUDE.md). Without this the container writes root-owned __pycache__
#    directories into that tree, which then need sudo to clean up.

# No --platform on the FROM: that is buildkit's default for the target being built, and
# stating it explicitly is both redundant and a way to pin the wrong arch by accident.
# Unlike the other python/*.Dockerfile images this one needs no TARGETARCH either, since
# it installs nothing platform-specific and so never consults platform.sh.
FROM python:3.13-slim

LABEL maintainer="Enchantee racing"
LABEL description="Sail racing support app: pre-start countdown, next mark, instrument HUD"

WORKDIR /app

# Dependencies before source, so editing the app does not re-run pip. Flask and
# paho-mqtt only; the pin on paho's major version is deliberate and explained in
# requirements.txt.
COPY enchantee_racing/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The application. app.py is a script rather than a package, and imports `engine` and
# `mqtt_client` as top-level names, so these land directly in /app and /app is the
# working directory.
COPY enchantee_racing/app.py \
     enchantee_racing/mqtt_client.py \
     enchantee_racing/store.py \
     ./
COPY enchantee_racing/engine/    ./engine/
COPY enchantee_racing/templates/ ./templates/
COPY enchantee_racing/static/    ./static/
COPY enchantee_racing/config/    ./config/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV TZ=UTC

# MQTT_IP names the broker, matching every other image in python/. On host networking,
# which is how this runs on the Pi, that is localhost; on a bridge network it is the
# mosquitto service name.
ENV MQTT_IP=localhost
ENV MQTT_PORT=1883

# BIND_HOST is 127.0.0.1 because nginx proxies to 127.0.0.1:5002 and host networking
# puts the app straight on the host's loopback. Override to 0.0.0.0 when running on a
# bridge network with a published port, or the port is unreachable from outside.
ENV BIND_HOST=127.0.0.1
ENV SERVICE_PORT=5002

EXPOSE 5002

# /api/state rather than a dedicated /health route, because it is the endpoint every
# page actually polls: if it answers, the store, the config load and the race engine are
# all up. urllib keeps this to the standard library, the way event_recorder's does.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/state' % os.environ.get('SERVICE_PORT','5002'), timeout=5)" || exit 1

# Stopping this container cleanly takes both of the next two lines, and neither is
# sufficient alone. Measured, because the first attempt looked right and was not: with
# only the exec form, `docker stop` still took 10.2 s.
#
# STOPSIGNAL SIGINT, because the Werkzeug development server installs no SIGTERM
# handler. The default docker stop signal is therefore ignored, the container sits out
# the full 10 s stop timeout, and docker resorts to SIGKILL. SIGINT raises
# KeyboardInterrupt out of app.run(), which is what app.py's `finally: source.stop()`
# is written to catch, so the paho loop is shut down rather than killed mid-publish.
STOPSIGNAL SIGINT

# Exec form wrapping one shell, rather than the bare shell form the other images in
# python/ use. The environment variables above still expand, but `exec` replaces the
# shell with python, so python becomes PID 1 and receives the signal at all. In shell
# form it goes to /bin/sh, which does not forward it, and STOPSIGNAL above would have
# no effect.
CMD ["sh", "-c", "exec python app.py --broker $MQTT_IP --broker-port $MQTT_PORT --host $BIND_HOST --port $SERVICE_PORT"]
