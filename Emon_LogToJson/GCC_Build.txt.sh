g++ Emon_LogToJson.cpp SensorReader.cpp SensorDataArray.cpp ../EmonShared/EmonShared.cpp rs232.c -o Emon_LogToJson -lstdc++fs -Wno-psabi -D__linux__ -DMQTT_LIB
