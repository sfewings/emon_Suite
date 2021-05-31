If not using docker-compose
grafana
=======
docker pull grafana/grafana
docker run -d --name=grafana -p 3000:3000 grafana/grafana

influxdb
========
docker pull influxdb
docker run -p 8086:8086 -v influxdb:/var/lib/influxdb influxdb:1.8