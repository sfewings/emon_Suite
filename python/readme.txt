To create pyemonlib
===================
Instructions as from https://medium.com/analytics-vidhya/how-to-create-a-python-library-7d5aea80cc3f 
1. Create a virtual environment to contain the python setup in pyEmon
    > cd ./emon_Suite/python/pyEmon
    > python3 -m venv venv
    > source venv/bin/activate
2. Install the libraries required for setup
    > pip install wheel setuptools twine pybind11
3. Run all the tests in tests folder
    > python setup.py pytest
3. Run setup
    > python setup.py bdist_wheel
4. Copy the wheel from dist and install
    > pip install ./dist/pyemonlib-0.1.0-cp37-cp37m-linux_armv7l.whl
    or
    > deactivate
    > pip3 uninstall -y pyemonlib && pip3 install ./dist/pyemonlib-0.1.0-cp37-cp37m-linux_armv7l.whl

To create and enable python environment
=======================================
1. Create environment named venv 
   > python3 -m venv venv
2. Activate the environment
   > source venv/bin/activate
3. Deactivate the environment
   > deactivate

To build docker file and run
============================
1. cd python
2. docker build -f MQTTToLog.Dockerfile -t "emon_mqtt_to_log:v1" .
3. docker run --rm -it -e "MQTT_IP=mqtt" -v /share/test:/share/Input --name emon_log --network=docker-compose-influxdb-grafana_default emon_mqtt_to_log:v1
4. docker build -f serialToMQTT.Dockerfile -t "emon_serial_to_mqtt:v1" .
5. docker run --rm -it -e "MQTT_IP=mqtt" -e "SERIAL_PORT=/dev/ttyUSB1" --device=/dev/ttyUSB1 --name emon_serial --network=docker-compose-influxdb-grafana_default emon_serial_to_mqtt:v1
6. docker build -f MQTTToInflux.Dockerfile -t "emon_mqtt_to_influx:v1" .
7. docker run --rm -it -e "MQTT_IP=mqtt" -e "INFLUX_IP=influxdb" -v /share/emon_Suite/python:/share/config --name emon_influx --network=docker-compose-influxdb-grafana_default emon_mqtt_to_influx:v1

Useful docker commands
======================
docker logs --details -f emon_log
docker-compose up -d
docker-compose down
docker container prune
docker container list
docker ps


To drop the sensor database from influx and create a new one
============================================================
1. exec influx inside the influx container
    docker exec -it 999fca3ed0cd sh
2. start the influx cli
    influx
3. drop the existing sensors database 
    DROP DATABASE sensors
4. Create a new sensors database
    CREATE DATABASE sensors
