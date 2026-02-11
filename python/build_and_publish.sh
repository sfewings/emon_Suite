#docker login -u sfewings32 
# docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 -f serialToMQTT.Dockerfile -t "sfewings32/emon_serial_to_mqtt:latest" --push . 
# docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 -f MQTTToInflux.Dockerfile -t "sfewings32/emon_mqtt_to_influx:latest" --push .
# docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 -f MQTTToLog.Dockerfile -t "sfewings32/emon_mqtt_to_log:latest" --push .
docker buildx build --platform linux/arm64 -f emon_settings_web/Dockerfile -t "sfewings32/emon_settings_web:date_settings" --push . 
docker buildx build --platform linux/arm64 -f serialToMQTT.Dockerfile -t "sfewings32/emon_serial_to_mqtt:date_settings" --push . 
docker buildx build --platform linux/arm64 -f MQTTToInflux.Dockerfile -t "sfewings32/emon_mqtt_to_influx:date_settings" --push .
docker buildx build --platform linux/arm64 -f MQTTToLog.Dockerfile -t "sfewings32/emon_mqtt_to_log:date_settings" --push .
docker buildx build --platform linux/arm64 -f GPSDToMQTT.Dockerfile -t "sfewings32/emon_gpsd_to_mqtt:date_settings" --push .
