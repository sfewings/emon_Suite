To use pyEnv to install multiple version of python to RaspPi
============================================================
1.See instructions at https://www.samwestby.com/tutorials/rpi-pyenv.html. 
            Windows - https://github.com/pyenv-win/pyenv-win
2. curl https://pyenv.run | bash
3. sudo nano ~/.bashrc and add the follwoing lines to the end of .bashrc
    > export PATH="$HOME/.pyenv/bin:$PATH"
    > eval "$(pyenv init --path)"
    > eval "$(pyenv virtualenv-init -)"
4. Rerun shell
    > exec $SHELL
5. sudo apt-get install --yes libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev libgdbm-dev lzma lzma-dev tcl-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev wget curl make build-essential openssl
6. Setup pyenv
    > pyenv update
7. List availalbe pyenv versions
    > pyenv install --list
8. Install the version you are after
    > pyenv install 3.11.0
9. Run this new version of python from the current shell. Options 'shell', 'local', 'global' 
    > pyenv shell 3.11.0
10. Create a venv using this version of python as below

To create pyemonlib
===================
Instructions as from https://medium.com/analytics-vidhya/how-to-create-a-python-library-7d5aea80cc3f 
1. Create a virtual environment to contain the python setup in pyEmon
    > cd ./emon_Suite/python/pyEmon
    > python3.11 -m venv venv
    > source venv/bin/activate
2. Install the libraries required for setup
    > pip install wheel setuptools twine pybind11
3. Run all the tests in tests folder
    > python setup.py pytest
3. Run setup
    > python setup.py bdist_wheel
     or if using the python/pyEmon/pyproject.toml file
    > pip install build
    > cd /share/emon_Suite
    > python -m build python/pyEmon
4. Copy the wheel from dist and install
    > pip install ./dist/pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl
    or
    > deactivate
    > pip3 uninstall -y pyemonlib && pip3 install ./dist/pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl

To create and enable python environment
=======================================
1. Create environment named venv 
   > python3 -m venv venv
2. Activate the environment
   > source venv/bin/activate
   > (Windows)  venv\Scripts\activate
3. Deactivate the environment
   > deactivate
   > (Windows)  venv\Scripts\deactivate


To build docker file and run
============================
1. cd python
2. docker build -f MQTTToLog.Dockerfile -t "emon_mqtt_to_log:v1" .
3. docker run --rm -it -e "MQTT_IP=mqtt" -v /share/test:/share/Input --name emon_log --network=docker-compose-influxdb-grafana_default emon_mqtt_to_log:v1
4. docker build -f serialToMQTT.Dockerfile -t "emon_serial_to_mqtt:v1" .
5. docker run --rm -it -v /share/emon_Suite/python:/data -e "MQTT_IP=mqtt" -e "SERIAL_PORT=/dev/ttyUSB0" -e "SETTINGS_PATH=/data/emon_config.yml" --device=/dev/ttyUSB1 --name emon_serial --network=docker-compose-influxdb-grafana_default emon_serial_to_mqtt:v1
6. docker build -f MQTTToInflux.Dockerfile -t "emon_mqtt_to_influx:v1" .
7. docker run --rm -it -e "MQTT_IP=mqtt" -e "INFLUX_IP=influxdb" -v /share/emon_Suite/python:/share/config --name emon_influx --network=docker-compose-influxdb-grafana_default emon_mqtt_to_influx:v1

To build multiplatform container (emonSerialToMQTT.py) Needs pyemonlib for all platforms in python/pyEmon/dist 
======================================================
docker buildx create --name emonbuilder --driver docker-container --bootstrap
docker buildx use emonbuilder
docker buildx inspect
docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 -f serialToMQTT.Dockerfile -t "sfewings32/emon_serial_to_mqtt:latest" --push . 
docker buildx build --platform linux/arm64,linux/arm/v7 -f MQTTToInflux.Dockerfile -t "sfewings32/emon_mqtt_to_influx:latest" --push .
docker buildx build --platform linux/arm64,linux/arm/v7 -f MQTTToLog.Dockerfile -t "sfewings32/emon_mqtt_to_log:latest" --push .

Useful docker commands
======================
docker logs --details -f emon_log
docker-compose up -d
docker-compose down
docker container prune
docker container list
docker ps
docker image prune
docker rmi [image name]
docker exec -it [image name] /bin/bash

Dockerhub commands
==================
docker login -u sfewings32
docker image tag emon_serial_to_mqtt:v1 sfewings32/emon_serial_to_mqtt:latest
docker push sfewings32/emon_serial_to_mqtt:latest
docker image tag emon_mqtt_to_influx:v1 sfewings32/emon_mqtt_to_influx:latest
docker push sfewings32/emon_mqtt_to_influx:latest
docker image tag emon_mqtt_to_log:v1 sfewings32/emon_mqtt_to_log:latest
docker push sfewings32/emon_mqtt_to_log:latest


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

To drop a single value from a sensor in a given time range
==========================================================
1. exec influx inside the influx container
    docker exec -it 999fca3ed0cd sh
2. start the influx cli
    influx
3. Use the sensors database
    use sensors
4. Delete the records within a range based on UTC time
    DELETE FROM rain WHERE time > '2023-04-08 02:25:00' and time < '2023-04-08 02:25:04'
5. See if the data was deleted
    SELECT * FROM rain WHERE time > '2023-04-08 02:25:00' and time < '2023-04-08 02:25:04'
 or
4. Show all rain values above a realistic values
    SELECT * FROM rain WHERE value > 5000
        time                sensor sensorGroup sensorName value
        ----                ------ ----------- ---------- -----
        1666951561713521000 rain   rain gauge  Rain gauge 395986585.8
5. Delete each value based on the time from the SELECT results
    DELETE FROM rain WHERE time = 1666951561713521000
