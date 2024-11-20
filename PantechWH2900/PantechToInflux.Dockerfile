FROM arm64v8/python:3.11
COPY ./PantechWH2900_to_influx.py ./
RUN pip3 install pytz paho-mqtt influxdb-client[ciso]
RUN mkdir -p /share/Input/weather_station
ENV LOG_PATH=/share/Input/weather_station
ENV MQTT_IP=localhost
ENV INFLUX_IP=localhost
ENV TZ="Australia/Perth"
CMD python ./PantechWH2900_to_influx.py -m $MQTT_IP -i $INFLUX_IP -l $LOG_PATH
#CMD ["sh"]