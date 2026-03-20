FROM python:3.10-slim

RUN pip install --no-cache-dir pyserial

WORKDIR /app
COPY orin_emon.py .

# Configurable environment variables
ENV SERIAL_PORT="/dev/ttyUSB0"
ENV LOG_DIR="/data/logs"
ENV INTERVAL="5"

VOLUME ["/data/logs"]

CMD python3 orin_emon.py \
    --port "${SERIAL_PORT}" \
    --log-dir "${LOG_DIR}" \
    --interval "${INTERVAL}" \
    --verbose
