#!/bin/bash
g++ Emon_LogToJson.cpp SensorReader.cpp SensorDataArray.cpp ../EmonShared/EmonShared.cpp rs232.c -o Emon_LogToJson -lstdc++fs -lpaho-mqttpp3 -lpaho-mqtt3a -Wno-psabi -D__linux__ -DMQTT_LIB
