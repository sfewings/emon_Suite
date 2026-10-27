"""Feed recorded lines through emon_influx.process_line, as emonMQTTToInflux does, and
write every Point as line protocol instead of sending it to Influx.

Runs inside an emon_mqtt_to_influx image (old or new). Each line's time is its log
timestamp (Perth), or a fixed time for untimestamped fixture lines, so settings-file
selection and Point times are the same in both images.
"""
import datetime
import re
import sys

import influxdb_client
import pytz

out_path, settings_path, *files = sys.argv[1:]
out = open(out_path, "w")


class FakeWriteApi:
    def write(self, bucket, record, **kw):
        out.write(f"{bucket} {record.to_line_protocol()}\n")

    def close(self):
        pass

    def flush(self):
        pass


influxdb_client.InfluxDBClient.write_api = lambda self, *a, **k: FakeWriteApi()
from pyemonlib import emon_influx  # noqa: E402  (after the patch)

perth = pytz.timezone("Australia/Perth")
fixed = perth.localize(datetime.datetime(2026, 10, 18, 12, 0, 0)).astimezone(pytz.utc)
e = emon_influx.emon_influx(url="http://127.0.0.1:1", settingsPath=settings_path, batchProcess=False)

stamp = re.compile(r"^(\d\d/\d\d/\d{4} \d\d:\d\d:\d\d),")
fed = errors = 0
for path in files:
    for raw in open(path, encoding="utf-8", errors="replace"):
        line = raw.rstrip("\r\n")
        m = stamp.match(line)
        if m:
            t = perth.localize(datetime.datetime.strptime(m.group(1), "%d/%m/%Y %H:%M:%S")).astimezone(pytz.utc)
            line = line[m.end():]
        else:
            t = fixed
        if not line:
            continue
        fed += 1
        try:
            e.process_line(t, line)
        except Exception as ex:
            errors += 1
            out.write(f"ERROR {type(ex).__name__}\n")
out.close()
print(f"INFLUX fed={fed} errors={errors}")
