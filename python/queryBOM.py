import sys
import time
from weather_au import api
from weather_au import observations
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS, WriteOptions


def writeValue(sensorName, temperatureValue, BOM_id, url="10.0.0.114:8086" ):
  client = InfluxDBClient(url, token="my-token", org="my-org")
  p = Point("temperature").tag("sensor",f"temperature/BOM/{sensorName}")\
                                            .tag("sensorGroup", "BOM") \
                                            .tag("sensorName", sensorName)\
                                            .tag("BOM_id", BOM_id)\
                                            .field("value", temperatureValue)
  
  ret = client.write_api().write(bucket="sensors", record=p)
  print(f"{sensorName}: {temperatureValue}")
  print(f"Write to influx: {ret}")
  client.close()

def getPerthTemperature():
  w = api.WeatherApi(search='perth+wa', debug=0)
  observations = w.observations()
  return observations['temp']

print("Query BOM Perth temperature and publish to influxdb:8086")

while 1:
  temperature = getPerthTemperature()
  writeValue("Perth BOM", temperature, 94608)

  obs_data = observations.Observations('WA')
  writeValue("Murchison",    float(obs_data.air_temperature(94422)), 94422)
  writeValue("Meekatharra",  float(obs_data.air_temperature(94430)), 94430)
  writeValue("Mount Magnet", float(obs_data.air_temperature(94429)), 94429)
  writeValue("Perth",        float(obs_data.air_temperature(94608)), 94608)

  sys.stdout.flush()

  time.sleep(120)
