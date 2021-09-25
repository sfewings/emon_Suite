# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm32v7/python:3.6-buster


# Copy the Python Script to blink LED
COPY ./emonMQTTToLog.py ./
COPY ./pyEmon/dist/pyemonlib-0.1.0-py3-none-any.whl ./
#COPY ./pyEmon/pyemonlib/emonSuite.cpython-37m-arm-linux-gnueabihf.so ./

# Intall the rpi.gpio python module
RUN pip3 install pyemonlib-0.1.0-py3-none-any.whl
#RUN pip3 install emonSuite.cpython-37m-arm-linux-gnueabihf.so

# Trigger Python script
#CMD ["python", "./emonMQTTToLog.py"]
CMD ["sh"]