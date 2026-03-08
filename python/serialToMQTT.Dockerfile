FROM python:3.13
ARG TARGETARCH
RUN apt-get update
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
