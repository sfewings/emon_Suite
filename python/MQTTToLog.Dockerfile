FROM --platform=$TARGETPLATFORM python:3.11
ARG TARGETARCH
COPY ./platform.sh ./
#writes platform specific wheel filename to /.platform_whl
COPY ./pyEmon/dist/* ./
RUN ./platform.sh 
COPY ./emonMQTTToLog.py ./
RUN pip install $(cat /.platform_whl)
RUN pip3 install pytz
RUN mkdir -p /share/Input
ENV MQTT_IP=localhost
ENV TZ="Australia/Perth"
CMD ["python", "./emonMQTTToLog.py", "-m", "$MQTT_IP"]
#CMD ["sh"]