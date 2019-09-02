#! /bin/sh
#Start Emon_LogToJson with input from /share/Input and output to /share/Output
# Once processed, listen to data from the localhost MQTT service.

/share/Emon_LogToJson/Emon_LogToJson -i /share/Input -o /share/Output -m localhost:1883
