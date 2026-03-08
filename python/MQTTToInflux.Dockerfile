FROM python:3.13
ARG TARGETARCH
RUN apt-get update
RUN pip3 install numpy pytz
#writes platform specific wheel filename to /.platform_whl
COPY ./platform.sh ./  
COPY ./pyEmon/dist/* ./
RUN ./platform.sh 
RUN pip install $(cat /.platform_whl)
RUN mkdir -p /share/config
#container specific dependencies from here down
COPY ./emonMQTTToInflux.py ./
COPY ./emonLogToInflux.py ./
ENV INFLUX_IP=localhost
ENV MQTT_IP=localhost
ENV SETTINGS_PATH=/share/config/emon_config.yml
CMD python ./emonMQTTToInflux.py -i $INFLUX_IP -m $MQTT_IP -s $SETTINGS_PATH
