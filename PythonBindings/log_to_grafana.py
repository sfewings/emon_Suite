import emonSuite
import influxdb_client
import time
import datetime
import os
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS, WriteOptions


bucket = "sensors"
client = InfluxDBClient(url="http://localhost:8086", token="my-token", org="my-org")

write_api = client.write_api(write_options=WriteOptions(batch_size=50_000, flush_interval=10_000))
#query_api = client.query_api()
delete_api = client.delete_api()

"""
Delete Data
"""
start ="1970-01-01T00:00:00Z"
stop = "2021-05-25T00:00:00Z"
#delete_api.delete(start, stop, '_measurement="my_measurement2"', bucket=bucket, org='my-org')

def rainMessage(time, rainReading):
    payload = emonSuite.PayloadRain()
    if( emonSuite.EmonSerial.ParseRainPayload(rainReading,payload) ):
        try:
            p = Point("rain").field("value", payload.rainCount/5).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point("temperature/rain").field("value", payload.temperature/100).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point("supplyV/rain").field("value", payload.supplyV).time(time)
            write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"rainException {rainReading} - {ex}")

def temperatureMessage(time, temperatureReading):
    payload = emonSuite.PayloadTemperature()
    if( emonSuite.EmonSerial.ParseTemperaturePayload(temperatureReading,payload) ):
        try:
            for reading in range(payload.numSensors):
                p = Point(f"temperature/temp/{payload.subnode}/{reading}").field("value", payload.temperature[reading]/100).time(time)
                write_api.write(bucket=bucket, record=p)
            p = Point(f"supplyV/temp/{payload.subnode}").field("value", payload.supplyV).time(time)
            write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"temperatureException {temperatureReading} - {ex}")

def pulseMessage(time, pulseReading):
    payload = emonSuite.PayloadPulse()
    if( emonSuite.EmonSerial.ParsePulsePayload(pulseReading,payload) ):
        try:
            for reading in range(emonSuite.PULSE_NUM_PINS):
                p = Point(f"power/{reading}").field("value", payload.power[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
                p = Point(f"pulse/{reading}").field("value", payload.pulse[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"pulseException {pulseReading} - {ex}")

def dispMessage(time, dispReading):
    payload = emonSuite.PayloadDisp()
    if( emonSuite.EmonSerial.ParseDispPayload(dispReading,payload) ):
        try:
            p = Point(f"temperature/disp/{payload.subnode}").field("value", payload.temperature).time(time)
            write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"dispException {dispReading} - {ex}")

def HWSMessage(time, HWSReading):
    payload = emonSuite.PayloadHWS()
    if( emonSuite.EmonSerial.ParseHWSPayload(HWSReading,payload) ):
        try:
            for reading in range(emonSuite.HWS_TEMPERATURES):
                p = Point(f"temperature/HWS/{reading}").field("value", payload.temperature[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
            for reading in range(emonSuite.HWS_PUMPS):
                p = Point(f"pump/HWS/{reading}").field("value", payload.pump[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"HWSException {HWSReading} - {ex}")

def waterMessage(time, waterReading):
    payload = emonSuite.PayloadWater()
    if( emonSuite.EmonSerial.ParseWaterPayload(waterReading,payload) ):
        try:
            for reading in range(payload.numFlowSensors):
                p = Point(f"water/flowCount/{reading}/{payload.subnode}").field("value", payload.flowCount[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
            for reading in range(payload.numHeightSensors):
                p = Point(f"water/height/{reading}/{payload.subnode}").field("value", payload.waterHeight[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
            p = Point(f"supplyV/water/{payload.subnode}").field("value", payload.supplyV).time(time)
            write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"waterException {waterReading} - {ex}")

def scaleMessage(time, scaleReading):
    payload = emonSuite.PayloadScale()
    if( emonSuite.EmonSerial.ParseScalePayload(scaleReading,payload) ):
        try:
            p = Point(f"scale/{payload.subnode}").field("value", payload.grams/1).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"supplyV/scale/{payload.subnode}").field("value", payload.supplyV).time(time)
            write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"scaleException {scaleReading} - {ex}")

def batteryMessage(time, batteryReading):
    payload = emonSuite.PayloadBattery()
    if( emonSuite.EmonSerial.ParseBatteryPayload(batteryReading,payload) ):
        try:
            for reading in range(emonSuite.BATTERY_SHUNTS):
                p = Point(f"battery/power/{reading}/{payload.subnode}").field("value", payload.power[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
            for reading in range(emonSuite.BATTERY_SHUNTS):
                p = Point(f"battery/pulseIn/{reading}/{payload.subnode}").field("value", payload.pulseIn[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
            for reading in range(emonSuite.BATTERY_SHUNTS):
                p = Point(f"battery/pulseOut/{reading}/{payload.subnode}").field("value", payload.pulseOut[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
            for reading in range(emonSuite.MAX_VOLTAGES):
                p = Point(f"battery/voltage/{reading}/{payload.subnode}").field("value", payload.voltage[reading]/1).time(time)
                write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"batteryException {batteryReading} - {ex}")

def inverterMessage(time, inverterReading):
    payload = emonSuite.PayloadInverter()
    if( emonSuite.EmonSerial.ParseInverterPayload(inverterReading,payload) ):
        try:
            p = Point(f"inverter/power/{payload.subnode}").field("value", payload.activePower).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"inverter/apparentPower/{payload.subnode}").field("value", payload.apparentPower).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"inverter/batteryVoltage/{payload.subnode}").field("value", payload.batteryVoltage).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"inverter/batteryDicharge/{payload.subnode}").field("value", payload.batteryDischarge).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"inverter/batteryCharging/{payload.subnode}").field("value", payload.batteryCharging).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"inverter/pvInputPower/{payload.subnode}").field("value", payload.pvInputPower).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"inverter/batteryCapacity/{payload.subnode}").field("value", payload.batteryCapacity).time(time)
            write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"inverterException {inverterReading} - {ex}")

def beeMessage(time, beehiveReading):
    payload = emonSuite.PayloadBeehive()
    if( emonSuite.EmonSerial.ParseBeehivePayload(beehiveReading,payload) ):
        try:
            p = Point(f"beehive/beeInRate/{payload.subnode}").field("value", payload.beeInRate).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"beehive/beeOutRate/{payload.subnode}").field("value", payload.beeOutRate).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"beehive/beesIn/{payload.subnode}").field("value", payload.beesIn).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"beehive/beesOut/{payload.subnode}").field("value", payload.beesOut).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"temperature/beehiveIn/{payload.subnode}").field("value", payload.temperatureIn).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"temperature/beehiveOut/{payload.subnode}").field("value", payload.temperatureOut).time(time)
            write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"beehiveException {beehiveReading} - {ex}")

def airMessage(time, airReading):
    payload = emonSuite.PayloadAirQuality()
    if( emonSuite.EmonSerial.ParseAirQualityPayload(airReading,payload) ):
        try:
            p = Point(f"airQuality/pm0p3/{payload.subnode}").field("value", payload.pm0p3).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"airQuality/pm0p5/{payload.subnode}").field("value", payload.pm0p5).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"airQuality/pm1p0/{payload.subnode}").field("value", payload.pm1p0).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"airQuality/pm2p5/{payload.subnode}").field("value", payload.pm2p5).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"airQuality/pm5p0/{payload.subnode}").field("value", payload.pm5p0).time(time)
            write_api.write(bucket=bucket, record=p)
            p = Point(f"airQuality/pm10p0/{payload.subnode}").field("value", payload.pm10p0).time(time)
            write_api.write(bucket=bucket, record=p)
        except Exception as ex:
            print(f"airQualityException {airReading} - {ex}")



def otherMessage(otherReading):
    print(otherReading)


dispatch = {
    # 'rain': rainMessage,
    # 'temp' : temperatureMessage,
    # 'disp' : dispMessage,
    # 'pulse' : pulseMessage,
    # 'hws' : HWSMessage,
    # 'wtr' : waterMessage,
    # 'scl' : scaleMessage,
    # 'bat' : batteryMessage,
    # 'inv' : inverterMessage,
    # 'bee' : beeMessage,
    'air' : airMessage,
    'other': otherMessage
}

def process_line(command, time, line):
    if(command in dispatch.keys()):
        dispatch[command](time, line)


def process_file(path):
    f = open(path, "r")
    num_lines = sum(1 for line in f)
    lineNum = 0
    currentPercent = 0
    f.seek(0)
    for line in f:
        try:
            dateAndNode = line.split(',',2)
            t = datetime.datetime.strptime(dateAndNode[0], "%d/%m/%Y %H:%M:%S")
            process_line(dateAndNode[1].rstrip('0123456789'), t, line[len(dateAndNode[0])+1: ])
            lineNum = lineNum+1
            if(int(lineNum/num_lines*100)>currentPercent):
                currentPercent = int(lineNum/num_lines*100)
                print( f"{currentPercent}%", end='\r' )
        except Exception as ex:
            print(f"Exception in process_file {line} - {ex}")

def process_files():
    files = os.listdir("/share/Input")
    files.sort()

    start = 0
    numFiles = len(files)
    for i in range(start, numFiles):
        file = files[i]
        if file.endswith(".TXT"):
            print(f"{datetime.datetime.now()}, {i} of {numFiles}, {file}")
            process_file(os.path.join("/share/Input",file))

    
    # for file in files:
    #     if file.endswith(".TXT"):
    #         count = count + 1
    #         print(f"{datetime.datetime.now()}, {count} of {len(files)}, {file}")
    #         process_file(os.path.join("/share/Input",file))

#process_file( "/share/Input/20210119.TXT")
process_files()
