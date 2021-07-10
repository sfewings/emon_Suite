import pyemonlib.emonSuite as emonSuite
import paho.mqtt.client as mqtt

import time
import datetime
import pytz
import os
import yaml
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS, WriteOptions

class emon_influx:
    def __init__(self, url="http://localhost:8086", settingsPath="./emon_config.yml",batchProcess=True):
        self.bucket = "sensors"
        self.client = InfluxDBClient(url, token="my-token", org="my-org")
        if(batchProcess):
            self.write_api = self.client.write_api(write_options=WriteOptions(batch_size=50_000, flush_interval=10_000))
        else:
            self.write_api = self.client.write_api(write_options=WriteOptions(batch_size=50, flush_interval=10))
        self.lineNumber = -1

        settingsFile = open(settingsPath, 'r')
        self.settings = yaml.full_load(settingsFile)
        self.dispatch = {
            'rain' : self.rainMessage,
            'temp' : self.temperatureMessage,
            'disp' : self.dispMessage,
            'pulse': self.pulseMessage,
            'hws'  : self.HWSMessage,
            'wtr'  : self.waterMessage,
            'scl'  : self.scaleMessage,
            'bat'  : self.batteryMessage,
            'inv'  : self.inverterMessage,
            'bee'  : self.beeMessage,
            'air'  : self.airMessage,
            'other': self.otherMessage
        }

    def __del__(self):
        self.client.close()
    
    def printException(self, exceptionSource, reading, ex):
        if( self.lineNumber == -1):
            print(f"{exceptionSource} {reading} - {ex}")
        else:
            print(f"{exceptionSource}:{self.lineNumber}, {reading} - {ex}")

    def rainMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadRain()
        if( emonSuite.EmonSerial.ParseRainPayload(reading,payload) ):
            try:
                p = Point("rain").tag("sensor", "rain")\
                                .tag("sensorName", nodeSettings[0]['name'])\
                                .field("value", payload.rainCount*nodeSettings[0]['mmPerPulse']).time(time)  #each pulse is 0.2mm
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("temperature").tag("sensor", "temperature")\
                                        .tag("sensorGroup","rain gauge")\
                                        .tag("sensorName", nodeSettings[0]['name'])\
                                        .field("value", payload.temperature/100).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("supplyV").tag("sensor", "supply voltage")\
                                    .tag("sensorName", nodeSettings[0]['name'])\
                                    .field("value", payload.supplyV/1000).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("rainException", reading, ex)

    def temperatureMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadTemperature()
        if( emonSuite.EmonSerial.ParseTemperaturePayload(reading,payload) ):
            try:
                for sensor in range(payload.numSensors):
                    p = Point("temperature").tag("sensor",f"temperature/temp/{payload.subnode}/{sensor}")\
                                            .tag("sensorGroup", nodeSettings[payload.subnode]["name"]) \
                                            .tag("sensorName", nodeSettings[payload.subnode][f"t{sensor}"])\
                                            .field("value", payload.temperature[sensor]/100).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                p = Point("supplyV").tag("sensor", f"supplyV/temp/{payload.subnode}")\
                                    .tag("sensorGroup", nodeSettings[payload.subnode]["name"]) \
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value", payload.supplyV/1000).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("temperatureException", reading, ex)

    def pulseMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadPulse()
        if( emonSuite.EmonSerial.ParsePulsePayload(reading,payload) ):
            try:
                for sensor in range(emonSuite.PULSE_NUM_PINS):
                    p = Point("power").tag("sensor",f"power/{sensor}")\
                                    .tag("sensorGroup", nodeSettings[0]["name"]) \
                                    .tag("sensorName", (nodeSettings[0][f"p{sensor}"]))\
                                    .field("value", payload.power[sensor]/1).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                    p = Point("pulse").tag("sensor",f"pulse/{sensor}")\
                                    .tag("sensorGroup", nodeSettings[0]["name"]) \
                                    .tag("sensorName", (nodeSettings[0][f"p{sensor}"]))\
                                    .field("value", payload.pulse[sensor]/1).time(time)
                                #.field("value", payload.pulse[sensor]*nodeSettings[0][f"p{sensor}_wPerPulse"]/1).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("pulseException", reading, ex)

    def dispMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadDisp()
        if( emonSuite.EmonSerial.ParseDispPayload(reading,payload) ):
            try:
                p = Point("temperature").tag("sensor", f"temperature/disp/{payload.subnode}") \
                                        .tag("sensorGroup", nodeSettings[payload.subnode]["name"]) \
                                        .tag("sensorName", (nodeSettings[payload.subnode]["name"])) \
                                        .field("value", payload.temperature/100).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("dispException", reading, ex)

    def HWSMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadHWS()
        if( emonSuite.EmonSerial.ParseHWSPayload(reading,payload) ):
            try:
                for sensor in range(emonSuite.HWS_TEMPERATURES):
                    p = Point("temperature").tag("sensor", f"temperature/HWS/{sensor}")\
                                            .tag("sensorGroup", nodeSettings[0]["name"]) \
                                            .tag("sensorName", nodeSettings[0][f"t{sensor}"])\
                                            .field("value", payload.temperature[sensor]/1).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                for sensor in range(emonSuite.HWS_PUMPS):
                    p = Point("pump").tag("sensor",f"pump/HWS/{sensor}")\
                                    .tag("sensorGroup", nodeSettings[0]["name"]) \
                                    .tag("sensorName",nodeSettings[0][f"p{sensor}"])\
                                    .field("value", payload.pump[sensor]/1).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("HWSException", reading, ex)

    def waterMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadWater()
        if( emonSuite.EmonSerial.ParseWaterPayload(reading,payload) ):
            try:
                for sensor in range(payload.numFlowSensors):
                    p = Point("water").tag("sensor",f"water/flowCount/{sensor}/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode][f"f{sensor}"])\
                                    .field("value", payload.flowCount[sensor]*nodeSettings[payload.subnode][f"f{sensor}_litresPerPulse"]).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                for sensor in range(payload.numHeightSensors):
                    p = Point("tank").tag("sensor", f"water/height/{sensor}/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode][f"h{sensor}"])\
                                    .field("value", payload.waterHeight[sensor]/1).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                p = Point("supplyV").tag("sensor", f"supplyV/water/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value", payload.supplyV/1000).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("waterException", reading, ex)

    def scaleMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadScale()
        if( emonSuite.EmonSerial.ParseScalePayload(reading,payload) ):
            try:
                p = Point("scale").tag("sensor",f"scale/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                .field("value", payload.grams/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("supplyV").tag("sensor",f"supplyV/scale/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value", payload.supplyV/1000).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("scaleException", reading, ex)

    def batteryMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadBattery()
        if( emonSuite.EmonSerial.ParseBatteryPayload(reading,payload) ):
            try:
                for sensor in range(emonSuite.BATTERY_SHUNTS):
                    if(nodeSettings[payload.subnode][f"s{sensor}"] != "Unused"):
                        p = Point("power").tag("sensor",f"battery/power/{sensor}/{payload.subnode}")\
                                        .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                        .tag("sensorName",nodeSettings[payload.subnode][f"s{sensor}"])\
                                        .field("value", payload.power[sensor]/1).time(time)
                        self.write_api.write(bucket=self.bucket, record=p)
                for sensor in range(emonSuite.BATTERY_SHUNTS):
                    if(nodeSettings[payload.subnode][f"s{sensor}"] != "Unused"):
                        p = Point("pulse").tag("sensor",f"battery/pulseIn/{sensor}/{payload.subnode}")\
                                        .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                        .tag("sensorName",nodeSettings[payload.subnode][f"s{sensor}"]+"In")\
                                        .field("value", payload.pulseIn[sensor]/1).time(time)
                        self.write_api.write(bucket=self.bucket, record=p)
                for sensor in range(emonSuite.BATTERY_SHUNTS):
                    if(nodeSettings[payload.subnode][f"s{sensor}"] != "Unused"):
                        p = Point("pulse").tag("sensor",f"battery/pulseOut/{sensor}/{payload.subnode}")\
                                        .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                        .tag("sensorName",nodeSettings[payload.subnode][f"s{sensor}"]+"Out")\
                                        .field("value", payload.pulseOut[sensor]/1).time(time)
                        self.write_api.write(bucket=self.bucket, record=p)
                #get the mid voltages
                railVoltage = payload.voltage[0]
                for sensor in range(emonSuite.MAX_VOLTAGES):
                    if(nodeSettings[payload.subnode][f"v{sensor}"] != "Unused"):
                        voltage = payload.voltage[sensor]
                        if(sensor != 0 ):
                            voltage = voltage - railVoltage/2.0
                        p = Point("voltage").tag("sensor",f"battery/voltage/{sensor}/{payload.subnode}")\
                                            .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                            .tag("sensorName",nodeSettings[payload.subnode][f"v{sensor}"])\
                                            .field("value", voltage/1).time(time)
                        self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("batteryException", reading, ex)

    def inverterMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadInverter()
        if( emonSuite.EmonSerial.ParseInverterPayload(reading,payload) ):
            try:
                p = Point("power").tag("sensor",f"inverter/power/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                .field("value",payload.activePower/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("power").tag("sensor",f"inverter/apparentPower/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - apparent power")\
                                .field("value", payload.apparentPower/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("voltage").tag("sensor",f"inverter/batteryVoltage/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value",payload.batteryVoltage/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("current").tag("sensor",f"inverter/batteryDicharge/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Discharge")\
                                    .field("value",payload.batteryDischarge/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("current").tag("sensor",f"inverter/batteryCharging/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Charge")\
                                    .field("value",payload.batteryCharging/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("power").tag("sensor",f"inverter/pvInputPower/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - PV")\
                                .field("value",payload.pvInputPower/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("capacity").tag("sensor",f"inverter/batteryCapacity/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value",payload.batteryCapacity/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("inverterException", reading, ex)

    def beeMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadBeehive()
        if( emonSuite.EmonSerial.ParseBeehivePayload(reading,payload) ):
            try:
                p = Point("beehive").tag("sensor",f"beehive/beeInRate/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - In rate")\
                                    .field("value",payload.beeInRate).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("beehive").tag("sensor",f"beehive/beeOutRate/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Out rate")\
                                    .field("value",payload.beeOutRate).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("beehive").tag("sensor",f"beehive/beesIn/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - In")\
                                    .field("value",payload.beesIn).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("beehive").tag("sensor",f"beehive/beesOut/{payload.subnode}")\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Out")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .field("value",payload.beesOut).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("temperature").tag("sensor",f"temperature/beehiveIn/{payload.subnode}")\
                                        .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                        .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Inside")\
                                        .field("value",payload.temperatureIn/100).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("temperature").tag("sensor",f"temperature/beehiveOut/{payload.subnode}")\
                                        .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                        .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Outside")\
                                        .field("value",payload.temperatureOut/100).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("supplyV").tag("sensor",f"supplyV/beehive/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value",payload.supplyV/1000).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("beehiveException", reading, ex)

    def airMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadAirQuality()
        if( emonSuite.EmonSerial.ParseAirQualityPayload(reading,payload) ):
            try:
                p = Point("air").tag("sensor",f"airQuality/pm0p3/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - 0.3")\
                                .field("value",payload.pm0p3).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("air").tag("sensor",f"airQuality/pm0p5/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - 0.5")\
                                .field("value",payload.pm0p5).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("air").tag("sensor",f"airQuality/pm1p0/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - 1.0")\
                                .field("value",payload.pm1p0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("air").tag("sensor",f"airQuality/pm2p5/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - 2.5")\
                                .field("value",payload.pm2p5).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("air").tag("sensor",f"airQuality/pm5p0/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - 5.0")\
                                .field("value",payload.pm5p0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("air").tag("sensor",f"airQuality/pm10p0/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - 10.0")\
                                .field("value",payload.pm10p0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
            except Exception as ex:
                self.printException("airQualityException", reading, ex)

    def otherMessage(self, time, reading, nodeSettings ):
        print(reading)


    def process_line(self, command, time, line ):
        if(command in self.dispatch.keys()):
            self.dispatch[command](time, line, self.settings[command])


    def process_file(self, path):
        try:
            #LOCAL_TIMEZONE = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
            local = pytz.timezone("Australia/Perth")
            f = open(path, "r")
            num_lines = sum(1 for line in f)
            self.lineNumber = 0
            currentPercent = 0
            f.seek(0)
            for line in f:
                try:
                    self.lineNumber = self.lineNumber+1
                    dateAndNode = line.split(',',3)
                    node = dateAndNode[1].rstrip('0123456789')
                    time = datetime.datetime.now()
                    if("rain" in dateAndNode[2]):
                        continue    # skip rain,rain,txCount,temperature,supplyV|ms_since_last_pkt 
                    if( " AM" in dateAndNode[0] or" PM" in dateAndNode[0]  ):
                        time = datetime.datetime.strptime(dateAndNode[0], "%d/%m/%Y %I:%M:%S %p")
                    else:
                        time = datetime.datetime.strptime(dateAndNode[0], "%d/%m/%Y %H:%M:%S")
                    local_dt = local.localize(time, is_dst=None)
                    utc_dt = local_dt.astimezone(pytz.utc)                
                    self.process_line( node, utc_dt, line[len(dateAndNode[0])+1: ])
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
