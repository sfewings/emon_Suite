# to build    docker build -f Dockerfile -t "emon_logtojson:v1" ..
# to run      docker run --rm -it -e "MQTT_IP=mqtt" -e "TZ=Australia/Perth" -v /share:/share --name emon_logtojson --network=docker-compose-influxdb-grafana_default emon_logtojson:v1 
# to publish  docker image tag emon_logtojson:v1 sfewings32/emon_logtojson:latest
#             docker push sfewings32/emon_logtojson:latest


FROM arm32v7/python:3.7-buster

RUN mkdir -p /share/libs
RUN apt-get update
RUN apt-get -y install build-essential gcc make cmake cmake-gui cmake-curses-gui
RUN apt-get -y install fakeroot fakeroot devscripts dh-make lsb-release
RUN apt-get -y install libssl-dev
RUN apt-get -y install doxygen graphviz
RUN apt-get -y install git

WORKDIR /share/libs
RUN git clone https://github.com/eclipse/paho.mqtt.c.git
RUN git clone https://github.com/eclipse/paho.mqtt.cpp.git

WORKDIR /share/libs/paho.mqtt.c
RUN make
RUN make install
RUN cmake -B build
RUN cmake --build build/ --target install

WORKDIR /share/libs/paho.mqtt.cpp
RUN mkdir build
RUN cmake -B build
RUN cmake --build build/ --target install

RUN mkdir /share/Emon_LogToJson
COPY ./Emon_LogToJson /share/Emon_LogToJson
COPY ./EmonShared /share/EmonShared
WORKDIR /share/Emon_LogToJson
RUN g++ Emon_LogToJson.cpp SensorReader.cpp SensorDataArray.cpp ../EmonShared/EmonShared.cpp rs232.c -o /Emon_LogToJson.exe -lstdc++fs -lpaho-mqttpp3 -lpaho-mqtt3a -Wno-psabi -D__linux__ -DMQTT_LIB
WORKDIR /share
ENV LD_LIBRARY_PATH="/usr/local/lib:${LD_LIBRARY_PATH}"
ENV MQTT_IP=localhost
ENV TZ="Australia/Perth"
ENV REPROCESS_LOGS_FROM_YEAR=this
ENTRYPOINT /Emon_LogToJson.exe -i /share/Input -o /share/Output -m $MQTT_IP -y $REPROCESS_LOGS_FROM_YEAR
#CMD ["sh"]