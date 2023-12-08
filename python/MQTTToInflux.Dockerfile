# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm64v8/python:3.11

COPY ./emonMQTTToInflux.py ./
COPY ./emonLogToInflux.py ./
COPY ./pyEmon/dist/pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl ./
RUN pip install pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl
RUN pip3 install numpy pytz
RUN mkdir -p /share/config
ENV INFLUX_IP=localhost
ENV MQTT_IP=localhost
ENV SETTINGS_PATH=/share/config/emon_config.yml
CMD python ./emonMQTTToInflux.py -i $INFLUX_IP -m $MQTT_IP -s $SETTINGS_PATH
#CMD ["sh"]