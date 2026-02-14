FROM --platform=$TARGETPLATFORM python:3.11
ARG TARGETARCH
#update for numpy dependencies
RUN apt-get update && apt-get install -y cmake
RUN pip3 install numpy
RUN pip install pyserial
#writes platform specific wheel filename to /.platform_whl
COPY ./platform.sh ./
COPY ./pyEmon/dist/* ./
RUN ./platform.sh 
RUN pip install $(cat /.platform_whl)
COPY ./emonSerialToMQTT.py ./
ENV MQTT_IP=localhost
ENV SERIAL_PORT=/dev/ttyUSB0
CMD ["python", "./emonSerialToMQTT.py", "-m", $MQTT_IP, "-c", $SERIAL_PORT, "-s", $SETTINGS_PATH]
