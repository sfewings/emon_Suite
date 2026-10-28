"""Compatibility shim: the emon_influx class, now over emon_decoder and sink_influx (DESIGN D4).

Keeps the class name, constructor, process_line(time, line), process_file, process_files
and close that emonMQTTToInflux.py and emonLogToInflux.py use. Every Point is written
with exactly the measurement and tags it always had, so Grafana is unaffected. New code
should use the decoder and sink directly. This file is deleted in PLAN phase 4.
"""

import datetime
import os

import pytz
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import WriteOptions

import pyemonlib.emon_settings as emon_settings
from pyemonlib import emon_decoder
from pyemonlib.sink_influx import InfluxSink


class emon_influx:
    def __init__(self, url="http://localhost:8086", settingsPath="./emon_config.yml", batchProcess=True):
        self.bucket = "sensors"
        self.client = InfluxDBClient(url, token="my-token", org="my-org")
        if batchProcess:
            self.write_api = self.client.write_api(write_options=WriteOptions(batch_size=50_000, flush_interval=10_000))
        else:
            self.write_api = self.client.write_api(write_options=WriteOptions(batch_size=50, flush_interval=10))
        self.lineNumber = -1

        # Initialize settings manager
        self.settings_manager = emon_settings.EmonSettings(settingsPath)

        self.dispatch = {key: None for key in emon_decoder.DECODERS}
        self.dispatch["other"] = None
        self.sink = InfluxSink(self.write_api, self.bucket, log=print)

    def __del__(self):
        self.close()

    def close(self):
        """
        Properly close the InfluxDB connection and ensure all pending batches are written.
        This uses the write_api's close() method to properly shut down the batch executor
        and wait for all pending writes to complete.
        """
        try:
            if hasattr(self, 'write_api') and self.write_api:
                print("Closing write API and flushing pending batches...")
                self.write_api.close()
                print("Write API closed and all batches flushed")
        except Exception as e:
            print(f"Error closing write_api: {e}")

        try:
            if hasattr(self, 'client') and self.client:
                print("Closing InfluxDB client...")
                self.client.close()
                print("InfluxDB client closed")
        except Exception as e:
            print(f"Error closing client: {e}")

    @property
    def settings(self):
        """Property to access current settings from settings manager."""
        return self.settings_manager.get_settings()

    def printException(self, exceptionSource, reading, ex):
        if self.lineNumber == -1:
            print(f"{exceptionSource} {reading} - {ex}")
        else:
            print(f"{exceptionSource}:{self.lineNumber}, {reading} - {ex}")

    find_v_reference = staticmethod(emon_decoder.find_v_reference)

    def process_line(self, time, line):
        # Check if settings need to be reloaded based on current time
        self.settings_manager.check_and_reload_settings_by_time(time)

        command = line.split(',', 1)[0].rstrip('0123456789')

        if command not in self.settings_manager.get_current_nodes():
            raise ValueError(f"No current configuration for node: {command} in line: {line}")
        if command not in self.dispatch.keys():
            raise ValueError(f"Unknown device: {command} in line: {line}")
        if command == "other":
            print(line)
            return
        t = time.timestamp() if hasattr(time, "timestamp") else None
        emissions = emon_decoder.decode(line, self.settings[command], t)
        context = f"{command}Exception {line}" if self.lineNumber == -1 else \
            f"{command}Exception:{self.lineNumber}, {line}"
        self.sink.write(emissions, time, context=context)

    # ---- unchanged from the original module -------------------------------------------

    def replace_at_position_with_comma(self, line, position):
        s = list(line)
        s[position] = ','
        return ''.join(s)

    def process_file(self, path):
        try:
            local = pytz.timezone("Australia/Perth")
            f = open(path, "r")
            num_lines = sum(1 for line in f)
            self.lineNumber = 0
            currentPercent = 0
            f.seek(0)
            for line in f:
                try:
                    self.lineNumber = self.lineNumber+1
                    colonPositionAfterDateTime = line[19:].find(":")
                    if(colonPositionAfterDateTime != -1):     # 20190314.TXT to 20190624.TXT used : to separate node name from values
                        line = self.replace_at_position_with_comma(line, colonPositionAfterDateTime+19)
                    if (line[19] != ',' and line[19] == ' '): # 20211231.TXT to 20220116.TXT had a space instead of comma after the date-time
                        line = self.replace_at_position_with_comma(line, 19)
                    date_node_line = line.split(',',2)
                    dateStr = date_node_line[0]
                    line = date_node_line[1] + ',' + date_node_line[2]
                    time = datetime.datetime.now()
                    if("rain" in date_node_line[2]):
                        continue    # skip rain,rain,txCount,temperature,supplyV|ms_since_last_pkt
                    if( " AM" in dateStr or" PM" in dateStr  ):
                        time = datetime.datetime.strptime(dateStr, "%d/%m/%Y %I:%M:%S %p")
                    else:
                        time = datetime.datetime.strptime(dateStr, "%d/%m/%Y %H:%M:%S")
                    local_dt = local.localize(time, is_dst=None)
                    utc_dt = local_dt.astimezone(pytz.utc)
                    self.process_line( utc_dt, line)
                    if(int(self.lineNumber/num_lines*100)>currentPercent):
                        currentPercent = int(self.lineNumber/num_lines*100)
                        print( f"{currentPercent}%", end='\r' )
                except Exception as ex:
                    print(f"Exception in process_file {line}:{self.lineNumber} - {ex}")

        except Exception as ex:
            print(f"Exception in process_file - {ex}")

    def process_files(self, path):
        files = os.listdir(path)
        files.sort()

        start = 0
        numFiles = len(files)

        for i in range(start, numFiles):
            file = files[i]
            if file.endswith(".TXT"):
                print(f"{datetime.datetime.now()}, {i} of {numFiles}, {file}")
                self.process_file(os.path.join(path,file))
