#docker build -f queryBOM.Dockerfile -t "query_bom:v1" .
#docker run --rm -it --name query_bom --network=docker-compose-influxdb-grafana_default query_bom:v1
# python:3.13, the same base as the rest of python/*.Dockerfile, and multi-arch so this
# builds for amd64, arm64 and armv7 from one file.
#
# It was arm32v7/python:3.7-buster: a 32-bit ARM image, which pinned the build to one
# architecture while the image published as sfewings32/emon_query_bom was arm64 anyway,
# and a Python that went end of life in June 2023 on a Debian release since archived.
FROM python:3.13

RUN pip3 install weather.au
RUN pip3 install influxdb-client[ciso]
RUN pip3 install bs4 lxml
ENV INFLUX_IP=localhost
COPY ./queryBOM.py ./
# sh -c so $INFLUX_IP is expanded at run time, in JSON form so docker does not have to
# guess. This was a JSON array with $INFLUX_IP unquoted, which is not valid JSON; docker
# fell back to shell form and built exactly this, so the behaviour is unchanged. Written
# out, it stops relying on that fallback and silences JSONArgsRecommended.
CMD ["sh", "-c", "python ./queryBOM.py -i $INFLUX_IP"]
#CMD ["sh"]
