import sys
import time
import argparse
import socket
import threading
from pyemonlib import emon_mqtt


#from weather_au import api
from weather_au import observations
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS, WriteOptions


def writeValue(sensorName, temperatureValue, BOM_id, url ):
  client = InfluxDBClient(url, token="my-token", org="my-org")
  p = Point("temperature").tag("sensor",f"temperature/BOM/{sensorName}")\
                                            .tag("sensorGroup", "BOM") \
                                            .tag("sensorName", sensorName)\
                                            .tag("BOM_id", BOM_id)\
                                            .field("value", temperatureValue/1)
  
  ret = client.write_api().write(bucket="sensors", record=p)
  print(f"{sensorName}: {temperatureValue}")
  print(f"Write to influx: {ret}")
  client.close()

# def getPerthTemperature():
#   w = api.WeatherApi(search='perth+wa', debug=0)
#   observations = w.observations()
#   return observations['temp']

print("Query BOM Perth temperature and publish to influxdb:8086. Version release 18 Apr 2024")

parser = argparse.ArgumentParser(description="Query BOM Perth temperature and publish to influxdb:8086 and mqtt")
parser.add_argument("-i", "--influx", help= "IP address of influxDB server", default="localhost")
parser.add_argument("-s", "--settingsPath", help= "Path to emon_config.yml containing emon configuration", default="/share/emon_Suite/python/emon_config.yml")
parser.add_argument("-m", "--MQTT", help= "IP address of MQTT server", default="localhost")
args = parser.parse_args()
influxURL = f"http://{args.influx}:8086"
mqttServer = str(args.MQTT)

start_time = time.time()

emonMQTT = emon_mqtt.emon_mqtt(mqtt_server=mqttServer, mqtt_port = 1883, settingsPath=args.settingsPath)

emonTemperatureNode = 6  # this value has to match the line in emon_config.yml for this installation

socket.setdefaulttimeout(60)

while 1:
  #run for 24 hours
  if time.time() - start_time >= 24*60*60:
    print("Automatic shutdown after 24 hours to overcome 'RuntimeError: can't start new thread'")
    break
  else:
    elapsed_seconds = time.time() - start_time
    hours = int(elapsed_seconds // 3600)
    minutes = int((elapsed_seconds % 3600) // 60)
    seconds = int(elapsed_seconds % 60)
    print(f"Running time: {hours:02d}:{minutes:02d}:{seconds:02d}")
    print(f"threading.active_count() = {threading.active_count()}")
    

#  temperature = getPerthTemperature()
#  writeValue("Perth BOM", temperature, 94608, influxURL)
  try:
    obs_data = observations.Observations('WA')
    perthTemperature = obs_data.air_temperature(94608)
    writeValue("Perth",        float(perthTemperature), 94608, influxURL)
    #writeValue("Meekatharra",  float(obs_data.air_temperature(94430)), 94430, influxURL)
    #writeValue("Mount Magnet", float(obs_data.air_temperature(94429)), 94429, influxURL)
    #writeValue("Murchison",    float(obs_data.air_temperature(94422)), 94422, influxURL)

    # write into emon temperature packet string
    emonPacket = f"temp1,{emonTemperatureNode},0,1,{int(perthTemperature)*100}"
    emonMQTT.process_line("temp", emonPacket)

  except Exception as e:
      print(f"Exception: {e}")

  sys.stdout.flush()

  time.sleep(120)
  