FROM --platform=$TARGETPLATFORM python:3.11
ARG TARGETARCH
#update for numpy dependencies
RUN apt-get update && apt-get install -y cmake
RUN pip3 install numpy pytz
#writes platform specific wheel filename to /.platform_whl
COPY ./platform.sh ./
COPY ./pyEmon/dist/* ./
RUN ./platform.sh 
RUN pip install $(cat /.platform_whl)
RUN mkdir -p /share/config
COPY ./emonMQTTToInflux.py ./
COPY ./emonLogToInflux.py ./
ENV INFLUX_IP=localhost
ENV MQTT_IP=localhost
ENV SETTINGS_PATH=/share/config/emon_config.yml
CMD ["python", "./emonMQTTToInflux.py", "-i", $INFLUX_IP, "-m", $MQTT_IP, "-s", $SETTINGS_PATH]
