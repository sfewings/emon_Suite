"""Write decoded emissions to InfluxDB with the tags emon_influx always used (DESIGN 4.1).

Measurement and tags come from each emission's legacy Influx part, so every existing
Grafana query keeps working. Takes any write_api with influxdb_client's
write(bucket=, record=) signature.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from influxdb_client import Point

from pyemonlib.emon_decoder import Emission


class InfluxSink:
    def __init__(self, write_api: Any, bucket: str, log: Callable[[str], None] = print):
        self.write_api = write_api
        self.bucket = bucket
        self.log = log

    def write(self, emissions: Iterable[Emission], time: Any, context: str = "") -> None:
        """In order, stopping at the first exception, as the old per-type functions did."""
        for emission in emissions:
            if emission.influx is None:
                continue
            try:
                out = emission.influx()
                if out is None:
                    continue
                measurement, tags, value = out
                point = Point(measurement)
                for key, tag in tags:
                    point = point.tag(key, tag)
                point = point.field("value", value).time(time)
                self.write_api.write(bucket=self.bucket, record=point)
            except Exception as ex:
                self.log(f"{context} - {ex}")
                break
