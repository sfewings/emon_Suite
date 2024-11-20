Receives a json string with eccowitt format weatherstation details on the mqtt topic "pantech"
To make docker image 
    docker login -u sfewings32
    docker buildx build --platform linux/arm64 -f PantechToInflux.Dockerfile -t "sfewings32/pantech_to_influx:latest" --push .

Requires bancha/ecowitt2mqtt docker image (https://hub.docker.com/r/bachya/ecowitt2mqtt) installed. (https://github.com/bachya/ecowitt2mqtt)
Running with the following command line
-e ECOWITT2MQTT_MQTT_BROKER=[IP address] -e ECOWITT2MQTT_MQTT_USERNAME=user ECOWITT2MQTT_MQTT_PASSWORD=password -e ECOWITT2MQTT_OUTPUT_UNIT_SYSTEM=metric -e ECOWITT2MQTT_MQTT_TOPIC=pantech -p 8002:8080 bachya/ecowitt2mqttt:latest
run docker image with the follow environmental variables
    LOG_PATH    = directory to store each received reading from the weather station. Default is /share/Input/weather_station
    MQTT_IP     = IP address of the MQTT server. Default is localhost
    INFLUX_IP   = IP address of the influx server. Default is localhost
    TZ          = Timezone for timestamping log files. Default is "Australia/Perth"
Configure the Pantech or Ecowitt weather station using the instructions from the user manual for Customized Upload service. (Use WS View app to configure the weather station)
    Enable
    Protocol Type same as = Ecowitt
    Server IP/Hostname = IP of the machine hosting bancha/ecowitt2mqtt container
    Path = /data/report
    Port = 8002 (The same as configured for bancha/ecowitt2mqtt -p)
    Upload interval = seconds between updates

For docker-compose use the following settings
  ecowitt_to_mqtt:
    image: bachya/ecowitt2mqtt:latest
    container_name: ecowitt_to_mqtt
    environment:
      - ECOWITT2MQTT_MQTT_BROKER: mqtt
      - ECOWITT2MQTT_MQTT_USERNAME: user
      - ECOWITT2MQTT_MQTT_PASSWORD: password
      - ECOWITT2MQTT_OUTPUT_UNIT_SYSTEM: metric
      - ECOWITT2MQTT_MQTT_TOPIC: pantech
    ports:
      - 8002:8080
    depends_on:
      - influxdb
      - mosquitto
    restart: always

  pantech_to_influx:
    image: sfewings32/pantech_to_influx:latest
    container_name: pantech_to_influx
    environment:
      - LOG_PATH: /share/Input/weather_station
      - MQTT_IP: mqtt
      - INFLUX_IP: influxdb
      - TZ=${TIMEZONE}
    depends_on:
      - influxdb
      - mosquitto
      - ecowitt_to_mqtt
    restart: always

