# emon_live: one site's live state and pages (docs/emon_live_ui/DESIGN.md 4.4).
#
# Build context is python/, as for every image build.sh makes:
#
#   ./build.sh -c emon_live
#
# The image holds the interpreter and the three dependencies, and no code. The code is
# bind-mounted from the checkout (python/ for emon_live and emon_feed, ui/ for the pages'
# engine, the site's emon-ui/ folder), so an edit is live after a container restart and
# a page edit at once, as "the checkout is the deployment" in the root CLAUDE.md.
#
# python:3.13-slim, not the python:3.13 base the decoder images share: emon_live needs
# neither numpy nor the pyemonlib wheel, since emon_feed is standard library only and is
# imported from the source tree (state.py). The race app set this precedent.

FROM python:3.13-slim

LABEL description="emon_live: live feeds by name, derived values and pages for one site"

WORKDIR /python/emon_live

COPY emon_live/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# The code is mounted read-only; nothing may try to write bytecode into it.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENV MQTT_IP=mqtt
ENV MQTT_PORT=1883
ENV INFLUX_URL=http://influxdb:8086
ENV SITE_DIR=/site
ENV UI_DIR=/ui
ENV BIND_HOST=0.0.0.0
ENV SERVICE_PORT=5003
ENV PUBLISH_DERIVED=1

EXPOSE 5003

# /api/state, the endpoint every page polls: if it answers, the store and the site are up.
# The start period covers the Influx replay that seeds today's totals (about 30 s).
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/state' % os.environ.get('SERVICE_PORT','5003'), timeout=5)" || exit 1

# SIGINT, because the Werkzeug server installs no SIGTERM handler: docker stop would wait
# out its timeout and kill it mid-publish. Exec form through one shell, so python is PID 1
# and receives it (enchantee_racing/Dockerfile, where this was measured).
STOPSIGNAL SIGINT
CMD ["sh", "-c", "exec python app.py"]
