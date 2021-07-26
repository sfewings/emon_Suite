# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm32v7/python:2.7.13-jessie

# Copy the Python Script to blink LED
COPY blink.py ./

# Intall the rpi.gpio python module
RUN pip install --no-cache-dir rpi.gpio

# Trigger Python script
CMD ["python", "./blink.py"]