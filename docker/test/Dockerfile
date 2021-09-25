# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm32v7/python:2.7.13-jessie

# Copy the Python Script to blink LED
COPY ../../python/emonMQTTToLog.py ./
COPY ../../python/pyEmon/dist/pyemonlib-0.1.0-py3-none-any.whl ./

# Intall the rpi.gpio python module
RUN pip3 install --no-cache-dir pyemonlib-0.1.0-py3-none-any.whl

# Trigger Python script
CMD ["python3", "./emonMQTTToLog.py"]