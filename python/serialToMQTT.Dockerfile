FROM --platform=$BUILDPLATFORM python:3.7-buster
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
#ENV SERIAL_PORT2=none
#CMD python ./emonSerialToMQTT.py -m $MQTT_IP -c $SERIAL_PORT -c2 $SERIAL_PORT2 -s $SETTINGS_PATH
CMD python ./emonSerialToMQTT.py -m $MQTT_IP -c $SERIAL_PORT -s $SETTINGS_PATH
#CMD ["sh"]