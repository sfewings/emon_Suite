FROM python:3.13
ARG TARGETARCH
RUN apt-get update && apt-get install -y cmake
RUN pip3 install numpy pytz
#writes platform specific wheel filename to /.platform_whl
COPY ./platform.sh ./  
COPY ./pyEmon/dist/* ./
RUN ./platform.sh 
RUN pip install $(cat /.platform_whl)
RUN mkdir -p /share/config
#container specific dependencies from here down
RUN pip3 install gpsdclient
COPY ./emonGPSDToMQTT.py ./
ENV GPS_NODE_NUMBER=0
ENV MQTT_IP=localhost
ENV SETTINGS_PATH=/share/config/emon_config.yml
CMD python ./emonGPSDToMQTT.py -m $MQTT_IP -s $SETTINGS_PATH -p $GPS_NODE_NUMBER
