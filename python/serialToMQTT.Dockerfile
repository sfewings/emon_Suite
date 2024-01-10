FROM --platform=$TARGETPLATFORM python:3.11
ARG TARGETARCH
COPY ./platform.sh ./
#writes platform specific wheel filename to /.platform_whl
COPY ./pyEmon/dist/* ./
RUN ./platform.sh 
COPY ./emonSerialToMQTT.py ./
RUN pip install pyserial
RUN pip install $(cat /.platform_whl)
#update for numpy dependencies
RUN apt-get update && apt-get install -y cmake
RUN pip3 install numpy
ENV MQTT_IP=localhost
ENV SERIAL_PORT=/dev/ttyUSB0
CMD python ./emonSerialToMQTT.py -m $MQTT_IP -c $SERIAL_PORT -s $SETTINGS_PATH
#CMD ["sh"]