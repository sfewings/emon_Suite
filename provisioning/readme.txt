If not using docker-compose
grafana
=======
docker pull grafana/grafana
docker run -d --name=grafana -p 3000:3000 grafana/grafana

influxdb
========
docker pull influxdb
docker run -p 8086:8086 -v influxdb:/var/lib/influxdb influxdb:1.8



docker-compose
==============
docker-compose up -d
docker-compose down

To execute within docker container
==================================
1. Get docker container name
    docker stats
2. Execute interactive
    docker exec -it [container name] sh

To delete influx database and create another 
============================================
1. influx
2. DROP DATABASE sensors
3. CREATE DATABASE sensors

To repopulate influx database from emon log files
================================================
1. Create a tmux session on the RapsPi and attach to it
    tmux new -d -s emon
    tmux a -t emon
2. Go to emon python directory and enable the venv environment. Create one if not exists
    cd /share/emon_suite/python
    source venv/bin/activate
   To create -
    python3 -m venv venv
    source venv/bin/activate
    pip install ./dist/pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl
3. Run the script to populate influx database
    python emonLogToInflux.py --fromFile 20240804.TXT --toFile 20250813.TXT -s /share/emon_Suite/provisioning/shannstainable/emon_config/emon_config.yml /share/Input
4. Detach from tmux session
    Ctrl+b then d
5. Kill the tmux session
    tmux kill-session -t emon