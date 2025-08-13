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