#docker build -f queryBOM.Dockerfile -t "query_bom:v1" .
#docker run --rm -it --name query_bom --network=docker-compose-influxdb-grafana_default query_bom:v1
# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm32v7/python:3.7-buster

RUN pip3 install weather.au
RUN pip3 install influxdb-client[ciso]
RUN pip3 install bs4 lxml
COPY ./queryBOM.py ./
CMD python ./queryBOM.py
#CMD ["sh"]
