# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm32v7/python:3.9-buster

COPY ./emonSerialToMQTT.py ./
COPY ./pyEmon/dist/pyemonlib-0.1.0-cp39-cp39-linux_armv7l.whl ./
RUN pip3 install pyserial
RUN pip3 install pyemonlib-0.1.0-cp39-cp39-linux_armv7l.whl
RUN pip3 install numpy
ENV MQTT_IP=localhost
ENV SERIAL_PORT=/dev/ttyUSB0
CMD python ./emonSerialToMQTT.py -m $MQTT_IP -c $SERIAL_PORT -s $SETTINGS_PATH
#CMD ["sh"]