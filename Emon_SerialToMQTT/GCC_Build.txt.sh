g++ Emon_SerialToMQTT.cpp MQTTClient.cpp PayloadFactory.cpp ../EmonShared/EmonShared.cpp rs232.c -o Emon_SerialToMQTT -lstdc++fs -lpaho-mqttpp3 -lpaho-mqtt3a -Wno-psabi -D__linux__ -DMQTT_LIB
