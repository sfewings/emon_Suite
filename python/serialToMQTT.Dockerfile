FROM python:3.13
ARG TARGETARCH
#Common base layers. Kept byte-identical across the python/*.Dockerfile set so
#docker reuses one cached set of layers for all of these images. Anything added
#above the marker below must be added to every one of them or the sharing breaks.
#cmake is required where numpy has no prebuilt wheel for the target platform.
RUN apt-get update && apt-get install -y cmake
RUN pip3 install numpy pytz
#writes platform specific wheel filename to /.platform_whl
COPY ./platform.sh ./
COPY ./pyEmon/dist/* ./
RUN ./platform.sh
RUN pip install $(cat /.platform_whl)
#container specific dependencies from here down
RUN pip install pyserial
COPY ./emonSerialToMQTT.py ./
ENV MQTT_IP=localhost
ENV SERIAL_PORT=/dev/ttyUSB0
CMD python ./emonSerialToMQTT.py -m $MQTT_IP -c $SERIAL_PORT -s $SETTINGS_PATH
