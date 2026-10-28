# Image A/B check before a deploy (PLAN 1e)

Replays one recorded log through the running production image and through a new image,
and compares what each puts on the wire. Not collected by pytest; run by hand on a Pi.
Uses a throwaway broker on 127.0.0.1:1884, never the production one (DESIGN 9.2).

```bash
export AB=<scratch dir outside /share> VENV=<venv with paho-mqtt>
cp tests/ab/*.py tests/ab/run_ab.sh tests/data/emonlog_sample.txt $AB/
awk -F'[ ,]' '$2 < "02:00:00"' /share/Input/<yyyymmdd>.TXT > $AB/house_2h.txt
docker network create emon_live_test
docker run -d --name emon_live_test_mqtt --network emon_live_test \
    -p 127.0.0.1:1884:1883 eclipse-mosquitto mosquitto -c /mosquitto-no-auth.conf

# MQTT: legacy topics must match in order, except channels named Unused
$AB/run_ab.sh house_old sfewings32/emon_serial_to_mqtt:latest    <site>/emon_config emonlog_sample.txt house_2h.txt
$AB/run_ab.sh house_new sfewings32/emon_serial_to_mqtt:live-test <site>/emon_config emonlog_sample.txt house_2h.txt
python3 $AB/compare.py $AB house
$VENV/bin/python $AB/retained.py      # envelopes and emon/config still retained

# Influx: line protocol must be byte-identical
mkdir -m 777 $AB/out
docker run --rm -e TZ=Australia/Perth -v $AB:/ab:ro -v $AB/out:/out -v <site>/emon_config:/data:ro \
    sfewings32/emon_mqtt_to_influx:<tag> python /ab/influx_replay.py /out/influx.house_<old|new>.txt \
    /data/emon_config.yml /ab/emonlog_sample.txt /ab/house_2h.txt
cmp $AB/out/influx.house_old.txt $AB/out/influx.house_new.txt

docker rm -f emon_live_test_mqtt && docker network rm emon_live_test
```

A broker clears the retain flag on live delivery, so `compare.py` cannot see it;
`retained.py`, run after a replay, is the retention check.
