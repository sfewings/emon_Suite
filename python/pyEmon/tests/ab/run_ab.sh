#!/bin/bash
# run_ab.sh <label> <image> <host settings dir> <input files in ab/...>
set -e
AB=${AB:?set AB to a scratch dir holding the inputs, outside /share}
VENV=${VENV:?set VENV to a venv with paho-mqtt}
label=$1; image=$2; settings=$3; shift 3
docker restart emon_live_test_mqtt >/dev/null; sleep 2
rm -f $AB/stop.$label
$VENV/bin/python $AB/capture.py $AB/cap.$label.jsonl $AB/stop.$label & cap=$!
sleep 2
inputs=""; for f in "$@"; do inputs="$inputs /ab/$f"; done
docker run --rm --network emon_live_test -e TZ=Australia/Perth \
  -v $AB:/ab:ro -v $settings:/data:ro $image \
  python /ab/replay.py emon_live_test_mqtt /data/emon_config.yml $inputs > $AB/replay.$label.log 2>&1
touch $AB/stop.$label; wait $cap
tail -1 $AB/replay.$label.log; wc -l < $AB/cap.$label.jsonl
