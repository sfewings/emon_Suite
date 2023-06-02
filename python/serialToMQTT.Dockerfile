# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM --platform=$BUILDPLATFORM python:3.9-buster
ARG TARGETARCH
COPY ./platform.sh ./
RUN ./platform.sh #should write platform specific wheel filename to /.platform_whl
COPY ./emonSerialToMQTT.py ./
COPY ./pyEmon/dist/* ./
RUN pip3 install pyserial
RUN pip3 install $(cat /.platform_whl)
RUN pip3 install numpy
ENV MQTT_IP=localhost
ENV SERIAL_PORT=/dev/ttyUSB0
CMD python ./emonSerialToMQTT.py -m $MQTT_IP -c $SERIAL_PORT -s $SETTINGS_PATH
