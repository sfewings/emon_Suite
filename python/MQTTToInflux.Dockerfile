# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm32v7/python:3.7-buster

COPY ./emonMQTTToInflux.py ./
COPY ./pyEmon/dist/pyemonlib-0.1.0-cp37-cp37m-linux_armv7l.whl ./
RUN pip3 install pyemonlib-0.1.0-cp37-cp37m-linux_armv7l.whl
RUN pip3 install numpy
RUN mkdir -p /share/config
ENV INFLUX_IP=localhost
ENV MQTT_IP=localhost
ENV SETTINGS_PATH=/share/config/emon_config.yml
CMD python ./emonMQTTToInflux.py -i $INFLUX_IP -m $MQTT_IP -s $SETTINGS_PATH
#CMD ["sh"]