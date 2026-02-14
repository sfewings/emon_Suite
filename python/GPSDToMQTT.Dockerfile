FROM --platform=$TARGETPLATFORM python:3.11
ARG TARGETARCH
#update for numpy dependencies
RUN apt-get update && apt-get install -y cmake
RUN pip3 install numpy
RUN pip3 install gpsdclient
COPY ./platform.sh ./
#writes platform specific wheel filename to /.platform_whl
COPY ./pyEmon/dist/* ./
RUN ./platform.sh 
RUN pip install $(cat /.platform_whl)
COPY ./emonGPSDToMQTT.py ./
ENV GPS_NODE_NUMBER=0
ENV MQTT_IP=localhost
ENV SETTINGS_PATH=/share/config/emon_config.yml
CMD ["python", "./emonGPSDToMQTT.py", "-m", $MQTT_IP, "-s", $SETTINGS_PATH, "-p", $GPS_NODE_NUMBER"]
#CMD ["sh"]