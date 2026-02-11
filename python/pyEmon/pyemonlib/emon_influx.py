import pyemonlib.emonSuite as emonSuite
import pyemonlib.emon_settings as emon_settings
#import pyEmon.pyemonlib.emon_settings as emon_settings
import paho.mqtt.client as mqtt

import time
import os
import re
import datetime
import pytz
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

        # Initialize settings manager
        self.settings_manager = emon_settings.EmonSettings(settingsPath)
        
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
            'leaf' : self.leafMessage,
            'gps'  : self.gpsMessage,
            'pth'  : self.pthMessage,            
            'bms'  : self.bmsMessage,
            'svc'  : self.sevConMessage,
            'mwv'  : self.mwvMessage,
            'other': self.otherMessage
        }

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
                # Close the write_api, which will flush and wait for all pending batches
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
        if( self.lineNumber == -1):
            print(f"{exceptionSource} {reading} - {ex}")
        else:
            print(f"{exceptionSource}:{self.lineNumber}, {reading} - {ex}")

    def publishRSSI(self, time, sensorName, reading):
        vals = reading.split(':')
        if('|' in vals[0]):         #reading has a relay value. Add the relay node to the sensor name
            relay = vals[0].split('|')[1]   # get the relay string e.g."00001010"
            if(relay.count("1")>1):
                return              #don't publish RSSI values that have more than 1 relay. As we don't know which relay node the RSSI represents
            sensorName = sensorName +'-'+vals[0].split('|')[1]
        p = Point("rssi").tag("sensor", f"rssi/{sensorName}")\
                        .tag("sensorGroup","RSSI")\
                        .tag("sensorName", sensorName)\
                        .field("value", int(vals[1])).time(time)
        self.write_api.write(bucket=self.bucket, record=p)
        

    def rainMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadRain()
        if( emonSuite.EmonSerial.ParseRainPayload(reading,payload) ):
            try:
                p = Point("rain").tag("sensor", "rain")\
                                .tag("sensorGroup","rain gauge")\
                                .tag("sensorName", nodeSettings[0]['name'])\
                                .field("value", payload.rainCount*nodeSettings[0]['mmPerPulse']).time(time)  #each pulse is 0.2mm
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("temperature").tag("sensor", "temperature/rain")\
                                        .tag("sensorGroup","rain gauge")\
                                        .tag("sensorName", nodeSettings[0]['name'])\
                                        .field("value", payload.temperature/100).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("supplyV").tag("sensor", "supply voltage")\
                                    .tag("sensorName", nodeSettings[0]['name'])\
                                    .field("value", payload.supplyV/1000).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[0]['name'], reading )

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
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )

            except Exception as ex:
                self.printException("temperatureException", reading, ex)

    def pulseMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadPulse()
        if( emonSuite.EmonSerial.ParsePulsePayload(reading,payload) ):
            try:
                for sensor in range(emonSuite.PULSE_MAX_SENSORS):
                    p = Point("power").tag("sensor",f"power/{payload.subnode}/{sensor}")\
                                    .tag("sensorGroup", nodeSettings[payload.subnode]["name"]) \
                                    .tag("sensorName", (nodeSettings[payload.subnode][f"p{sensor}"]))\
                                    .field("value", payload.power[sensor]/1).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                    p = Point("pulse").tag("sensor",f"pulse/{payload.subnode}/{sensor}")\
                                    .tag("sensorGroup", nodeSettings[payload.subnode]["name"]) \
                                    .tag("sensorName", (nodeSettings[payload.subnode][f"p{sensor}"]))\
                                    .field("value", payload.pulse[sensor]/1).time(time)
                                #.field("value", payload.pulse[sensor]*nodeSettings[0][f"p{sensor}_wPerPulse"]/1).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
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
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name']+" display", reading )
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
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[0]['name'], reading )
            except Exception as ex:
                self.printException("HWSException", reading, ex)

    def waterMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadWater()
        if( emonSuite.EmonSerial.ParseWaterPayload(reading,payload) ):
            try:
                for sensor in range(payload.numFlowSensors):
                    p = Point("water").tag("sensor",f"water/flowCount/{payload.subnode}/{sensor}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode][f"f{sensor}"])\
                                    .field("value", payload.flowCount[sensor]*nodeSettings[payload.subnode][f"f{sensor}_litresPerPulse"]).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                for sensor in range(payload.numHeightSensors):
                    p = Point("tank").tag("sensor", f"water/height/{payload.subnode}/{sensor}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode][f"h{sensor}"])\
                                    .field("value", payload.waterHeight[sensor]/1).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                p = Point("supplyV").tag("sensor", f"supplyV/water/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value", payload.supplyV/1000).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
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
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("scaleException", reading, ex)

    def find_v_reference(config):
        """
        Returns X (int) where 'vX_reference' == True.
        Returns -1 if no v_X_reference found.
        """
        for k, val in config.items():
            if(isinstance(k, str) and k.endswith('_reference')):
                m = re.match(r'^v(\d+)_reference$', k)
                if m and val is True:
                    return int(m.group(1))
        return -1

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
                #if a vX_reference setting is set to True, use that as the refence for midvoltages
                refSensor = emon_influx.find_v_reference(nodeSettings[payload.subnode])
                if(refSensor != -1):                
                    railVoltage = payload.voltage[refSensor]/100.0  #voltages are in 100ths
                else:
                    railVoltage = 0.0
                for sensor in range(emonSuite.MAX_VOLTAGES):
                    if(nodeSettings[payload.subnode][f"v{sensor}"] != "Unused"):
                        voltage = payload.voltage[sensor]/100.0
                        if(refSensor != -1 and sensor != refSensor):
                            voltage = voltage - railVoltage/2.0
                        p = Point("voltage").tag("sensor",f"battery/voltage/{sensor}/{payload.subnode}")\
                                            .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                            .tag("sensorName",nodeSettings[payload.subnode][f"v{sensor}"])\
                                            .field("value", voltage/1).time(time)
                        self.write_api.write(bucket=self.bucket, record=p)
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
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
                                    .field("value",payload.batteryVoltage/10).time(time)
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
                p = Point("pulse").tag("sensor",f"inverter/pulse/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value",payload.pulse/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
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
                p = Point("scale").tag("sensor",f"scale/beehive/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value", payload.grams/1).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("supplyV").tag("sensor",f"supplyV/beehive/{payload.subnode}")\
                                    .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                    .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                    .field("value",payload.supplyV/1000).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
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
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name']+" air", reading )
            except Exception as ex:
                self.printException("airQualityException", reading, ex)

    def leafMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadLeaf()
        if( emonSuite.EmonSerial.ParseLeafPayload(reading,payload) ):
            try:
                p = Point("leaf").tag("sensor",f"leaf/odometer/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+ " - Odometer")\
                                .field("value",payload.odometer).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("leaf").tag("sensor",f"leaf/range/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Range")\
                                .field("value",payload.range).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("leaf").tag("sensor",f"leaf/batteryTemperature/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Battery Temperature")\
                                .field("value",payload.batteryTemperature).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("leaf").tag("sensor",f"leaf/batterySOH/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Battery SOH")\
                                .field("value",payload.batterySOH).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("leaf").tag("sensor",f"leaf/batteryWH/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Battery WH")\
                                .field("value",payload.batteryWH).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("leaf").tag("sensor",f"leaf/batteryChargeBars/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Battery charge bars")\
                                .field("value",payload.batteryChargeBars).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("leaf").tag("sensor",f"leaf/chargeTimeRemaining/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Charge time remaining")\
                                .field("value",payload.chargeTimeRemaining).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("leafException", reading, ex)

    def gpsMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadGPS()
        if( emonSuite.EmonSerial.ParseGPSPayload(reading,payload) ):
            try:
                p = Point("gps").tag("sensor",f"gps/{payload.subnode}/latitude")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName","latitude")\
                                .field("value",payload.latitude).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("gps").tag("sensor",f"gps/{payload.subnode}/longitude")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName","longitude")\
                                .field("value",payload.longitude).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("gps").tag("sensor",f"gps/course/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+"-course")\
                                .field("value",payload.course).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("gps").tag("sensor",f"gps/speed/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+"-speed")\
                                .field("value",payload.speed).time(time)
                self.write_api.write(bucket=self.bucket, record=p)

                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("gpsException", reading, ex)

    def pthMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadPressure()
        if( emonSuite.EmonSerial.ParsePressurePayload(reading,payload) ):
            try:
                p = Point("pressure").tag("sensor",f"pressure/pth/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Pressure")\
                                .field("value",payload.pressure).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("temperature").tag("sensor",f"temperature/pth/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Temperature")\
                                .field("value",payload.temperature).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("humidity").tag("sensor",f"humidity/pth/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+" - Humidity")\
                                .field("value",payload.humidity).time(time)
                self.write_api.write(bucket=self.bucket, record=p)


                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("pthException", reading, ex)

    def bmsMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadDalyBMS()
        if( emonSuite.EmonSerial.ParseDalyBMSPayload(reading,payload) ):
            try:
                p = Point("voltage").tag("sensor",f"bms/voltage/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                .field("value",payload.batteryVoltage/10.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("bms").tag("sensor",f"bms/SoC/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+ " - SoC")\
                                .field("value",payload.batterySoC/10.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("power").tag("sensor",f"bms/power/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                .field("value",(payload.current*payload.batteryVoltage)/10.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("bms").tag("sensor",f"bms/resCapacity/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+ " - Res capacity")\
                                .field("value",payload.resCapacity/1.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("temperature").tag("sensor",f"bms/temperature/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                .field("value",payload.temperature/1.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("bms").tag("sensor",f"bms/lifetimeCycles/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"] + " - Lifetime cycles")\
                                .field("value",payload.lifetimeCycles/1.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)

                for cell in range(emonSuite.MAX_BMS_CELLS):
                    voltage = payload.cellmv[cell]/1000.0
                    p = Point("voltage").tag("sensor",f"bms/cellVoltage/{payload.subnode}/{cell}")\
                                        .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                        .tag("sensorName",nodeSettings[payload.subnode]["name"]+ f" - cell {cell}")\
                                        .field("value", voltage/1.0).time(time)
                    self.write_api.write(bucket=self.bucket, record=p)
                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("bmsException", reading, ex)

    def sevConMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadSevCon()
        if( emonSuite.EmonSerial.ParseSevConPayload(reading,payload) ):
            try:
                p = Point("temperature").tag("sensor",f"sevCon/temperature/{payload.subnode}/motor")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+ "motor")\
                                .field("value",payload.motorTemperature/1.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("temperature").tag("sensor",f"sevCon/temperature/{payload.subnode}/controller")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+ "controller")\
                                .field("value",payload.controllerTemperature/1.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("voltage").tag("sensor",f"sevCon/voltage/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"])\
                                .field("value",payload.capVoltage).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("power").tag("sensor",f"sevCon/current/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+ " - current")\
                                .field("value",payload.batteryCurrent).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("sevCon").tag("sensor",f"sevCon/rpm/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+ " - RPM")\
                                .field("value",(payload.rpm)/1.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)

                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("sevConException", reading, ex)

    def mwvMessage(self, time, reading, nodeSettings ):
        payload = emonSuite.PayloadAnemometer()
        if( emonSuite.EmonSerial.ParseAnemometerPayload(reading,payload) ):
            try:
                p = Point("temperature").tag("sensor",f"anemometer/temperature/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+ " - Temperature")\
                                .field("value",payload.temperature/1.0).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("anemometer").tag("sensor",f"anemometer/windSpeed/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"] + " - Wind Speed")\
                                .field("value",payload.windSpeed).time(time)
                self.write_api.write(bucket=self.bucket, record=p)
                p = Point("anemometer").tag("sensor",f"anemometer/windDirection/{payload.subnode}")\
                                .tag("sensorGroup",nodeSettings[payload.subnode]["name"])\
                                .tag("sensorName",nodeSettings[payload.subnode]["name"]+ " - Wind Direction")\
                                .field("value",payload.windDirection).time(time)
                self.write_api.write(bucket=self.bucket, record=p)

                if(':' in reading):
                    self.publishRSSI( time, nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("anemometerException", reading, ex)

    def otherMessage(self, time, reading, nodeSettings ):
        print(reading)


    def process_line(self, time, line ):
        # Check if settings need to be reloaded based on current time
        self.settings_manager.check_and_reload_settings_by_time(time)
        
        command = line.split(',',1)[0].rstrip('0123456789')

        if not command in self.settings_manager.get_current_nodes():
            raise ValueError(f"No current configuration for node: {command} in line: {line}")
        if(not command in self.dispatch.keys()):
            raise ValueError(f"Unknown device: {command} in line: {line}")
        self.dispatch[command](time, line, self.settings[command])

    def replace_at_position_with_comma(self, line, position):
        s = list(line)
        s[position] = ','
        return ''.join(s)
    
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
