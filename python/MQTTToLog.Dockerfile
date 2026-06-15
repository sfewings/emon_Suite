FROM python:3.13
ARG TARGETARCH
#update for numpy dependencies
RUN apt-get update && apt-get install -y cmake
RUN pip3 install numpy pytz
COPY ./platform.sh ./
#writes platform specific wheel filename to /.platform_whl
COPY ./pyEmon/dist/* ./
RUN ./platform.sh 
RUN pip install $(cat /.platform_whl)
COPY ./emonMQTTToLog.py ./
RUN mkdir -p /share/Input
ENV MQTT_IP=localhost
ENV TZ="Australia/Perth"
CMD python ./emonMQTTToLog.py -m $MQTT_IP
