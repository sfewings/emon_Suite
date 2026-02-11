FROM --platform=$TARGETPLATFORM python:3.11
ARG TARGETARCH
COPY ./platform.sh ./
#writes platform specific wheel filename to /.platform_whl
COPY ./pyEmon/dist/* ./
RUN ./platform.sh 
COPY ./emonMQTTToInflux.py ./
COPY ./emonLogToInflux.py ./
RUN pip install $(cat /.platform_whl)
#update for numpy dependencies
RUN apt-get update && apt-get install -y cmake
RUN pip3 install numpy pytz
RUN mkdir -p /share/config
ENV INFLUX_IP=localhost
ENV MQTT_IP=localhost
ENV SETTINGS_PATH=/share/config/emon_config.yml
CMD ["python", "./emonMQTTToInflux.py", "-i", "$INFLUX_IP", "-m", "$MQTT_IP", "-s", "$SETTINGS_PATH"]
#CMD ["sh"]