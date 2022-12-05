# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM python:3.7-buster

COPY ./emonSerialToMQTT.py ./
COPY ./pyEmon/dist/pyemonlib-0.1.0-cp37-cp37m-linux_x86_64.whl ./
RUN pip3 install pyserial
RUN pip3 install pyemonlib-0.1.0-cp37-cp37m-linux_x86_64.whl
RUN pip3 install numpy
ENV MQTT_IP=localhost
ENV SERIAL_PORT=/dev/ttyUSB0
ENV SERIAL_PORT2=none
CMD python ./emonSerialToMQTT.py -m $MQTT_IP -c $SERIAL_PORT -c2 $SERIAL_PORT2 -s $SETTINGS_PATH
#CMD ["sh"]