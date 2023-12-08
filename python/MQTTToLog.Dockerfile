# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm64v8/python:3.11

COPY ./emonMQTTToLog.py ./
COPY ./pyEmon/dist/pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl ./
RUN pip3 install pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl
RUN pip3 install pytz
RUN mkdir -p /share/Input
ENV MQTT_IP=localhost
ENV TZ="Australia/Perth"
CMD python ./emonMQTTToLog.py -m $MQTT_IP
#CMD ["sh"]