docker build -f MQTTToLog.Dockerfile -t "sfewings32/emon_mqtt_to_log:latest" .
docker build -f serialToMQTT.Dockerfile -t "sfewings32/emon_serial_to_mqtt:latest" .
docker build -f MQTTToInflux.Dockerfile -t "sfewings32/emon_mqtt_to_influx:latest" .
#docker login -u sfewings32 
docker push sfewings32/emon_serial_to_mqtt:latest
docker push sfewings32/emon_mqtt_to_influx:latest
docker push sfewings32/emon_mqtt_to_log:latest
