# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm32v7/python:3.7-buster

COPY ./emonMQTTToLog.py ./
COPY ./pyEmon/dist/pyemonlib-0.1.0-cp37-cp37m-linux_armv7l.whl ./
RUN pip3 install pyemonlib-0.1.0-cp37-cp37m-linux_armv7l.whl
RUN pip3 install pytz
RUN mkdir -p /share/Input
ENV MQTT_IP=localhost
ENV TZ="Australia/Perth"
CMD python ./emonMQTTToLog.py -m $MQTT_IP
#CMD ["sh"]