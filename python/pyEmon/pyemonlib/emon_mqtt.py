import pyemonlib.emonSuite as emonSuite
import paho.mqtt.client as mqtt

# import time
# import datetime
# import pytz
import os
import yaml

class emon_mqtt:
    def __init__(self, mqtt_server="localhost",mqtt_port=1883, settingsPath="./emon_config.yml"):
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
            'leaf' : self.leafMessage,
            'other': self.otherMessage
        }
        self.mqttClient = mqtt.Client()
        self.mqttClient.on_connect = self.on_connect
        self.mqttClient.connect(mqtt_server, mqtt_port, 60)

    # def __del__(self):
    #     self.client.close()

    def on_connect(client, userdata, flags, rc):
        print(f"emon_mqtt:Connected with result code {rc}")
    
    def printException(self, exceptionSource, reading, ex):
        if( self.lineNumber == -1):
            print(f"MQTT:{exceptionSource} {reading} - {ex}")
        else:
            print(f"MQTT:{exceptionSource}:{self.lineNumber}, {reading} - {ex}")

    def publishRSSI(self, sensorName, reading):
        vals = reading.split(':')
        if('|' in vals[0]):         #reading has a relay value. Add the relay node to the sensor name
            relay = vals[0].split('|')[1]   # get the relay string e.g."00001010"
            if(relay.count("1")>1):
                return              #don't publish RSSI values that have more than 1 relay. As we don't know which relay node the RSSI represents
            sensorName = sensorName +'-'+vals[0].split('|')[1]
        self.mqttClient.publish(f"rssi/{sensorName}", int(vals[1]))
        

    def rainMessage(self,  reading, nodeSettings ):
        payload = emonSuite.PayloadRain()
        if( emonSuite.EmonSerial.ParseRainPayload(reading,payload) ):
            try:
                self.mqttClient.publish("rain",payload.rainCount)
                self.mqttClient.publish("temperature/rain/0",payload.temperature / 100)
                self.mqttClient.publish("supplyV/rain",payload.supplyV)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[0]['name'], reading )
            except Exception as ex:
                self.printException("rainException", reading, ex)

    def temperatureMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadTemperature()
        if( emonSuite.EmonSerial.ParseTemperaturePayload(reading,payload) ):
            try:
                for sensor in range(payload.numSensors):
                    self.mqttClient.publish(f"temperature/temp/{payload.subnode}/{sensor}",payload.temperature[sensor]/100);
                self.mqttClient.publish(f"supplyV/temp/{payload.subnode}", payload.supplyV/1000)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )

            except Exception as ex:
                self.printException("temperatureException", reading, ex)

    def pulseMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadPulse()
        if( emonSuite.EmonSerial.ParsePulsePayload(reading,payload) ):
            try:
                for sensor in range(emonSuite.PULSE_MAX_SENSORS):
                    self.mqttClient.publish(f"power/{payload.subnode}/{sensor}", payload.power[sensor]/1)
                    self.mqttClient.publish(f"pulse/{payload.subnode}/{sensor}", payload.pulse[sensor]/1)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("pulseException", reading, ex)

    def dispMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadDisp()
        if( emonSuite.EmonSerial.ParseDispPayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"temperature/disp/{payload.subnode}",payload.temperature/100)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name']+" display", reading )
            except Exception as ex:
                self.printException("dispException", reading, ex)

    def HWSMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadHWS()
        if( emonSuite.EmonSerial.ParseHWSPayload(reading,payload) ):
            try:
                for sensor in range(emonSuite.HWS_TEMPERATURES):
                    self.mqttClient.publish(f"temperature/HWS/{sensor}", payload.temperature[sensor]/1)
                for sensor in range(emonSuite.HWS_PUMPS):
                    self.mqttClient.publish(f"pump/HWS/{sensor}", payload.pump[sensor]/1)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[0]['name'], reading )
            except Exception as ex:
                self.printException("HWSException", reading, ex)

    def waterMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadWater()
        if( emonSuite.EmonSerial.ParseWaterPayload(reading,payload) ):
            try:
                for sensor in range(payload.numFlowSensors):
                    self.mqttClient.publish(f"water/flowCount/{sensor}/{payload.subnode}",\
                            payload.flowCount[sensor]*nodeSettings[payload.subnode][f"f{sensor}_litresPerPulse"])
                for sensor in range(payload.numHeightSensors):
                    self.mqttClient.publish(f"water/height/{sensor}/{payload.subnode}",payload.waterHeight[sensor]/1)
                self.mqttClient.publish(f"supplyV/water/{payload.subnode}", payload.supplyV/1000)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("waterException", reading, ex)

    def scaleMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadScale()
        if( emonSuite.EmonSerial.ParseScalePayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"scale/{payload.subnode}",payload.grams/1)
                self.mqttClient.publish(f"supplyV/scale/{payload.subnode}", payload.supplyV/1000)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("scaleException", reading, ex)

    def batteryMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadBattery()
        if( emonSuite.EmonSerial.ParseBatteryPayload(reading,payload) ):
            try:
                #get the mid voltages from the rail voltage reference
                railVoltage = payload.voltage[0]/100.0  #voltages are in 100ths
                for sensor in range(emonSuite.BATTERY_SHUNTS):
                    if(nodeSettings[payload.subnode][f"s{sensor}"] != "Unused"):
                        self.mqttClient.publish(f"battery/power/{sensor}/{payload.subnode}", payload.power[sensor]/1)
                        self.mqttClient.publish(f"battery/pulseIn/{sensor}/{payload.subnode}", payload.pulseIn[sensor]/1)
                        self.mqttClient.publish(f"battery/pulseOut/{sensor}/{payload.subnode}", payload.pulseOut[sensor]/1)
                        voltage = payload.voltage[sensor]/100.0
                        if(sensor != 0 ):
                            voltage = voltage - railVoltage/2.0
                        self.mqttClient.publish(f"battery/voltage/{sensor}/{payload.subnode}", voltage/1)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("batteryException", reading, ex)

    def inverterMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadInverter()
        if( emonSuite.EmonSerial.ParseInverterPayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"inverter/power/{payload.subnode}",payload.activePower/1)
                self.mqttClient.publish(f"inverter/apparentPower/{payload.subnode}",payload.apparentPower/1)
                self.mqttClient.publish(f"inverter/batteryVoltage/{payload.subnode}",payload.batteryVoltage/1)
                self.mqttClient.publish(f"inverter/batteryDicharge/{payload.subnode}",payload.batteryDischarge/1)
                self.mqttClient.publish(f"inverter/batteryCharging/{payload.subnode}",payload.batteryCharging/1)
                self.mqttClient.publish(f"inverter/pvInputPower/{payload.subnode}",payload.pvInputPower/1)
                self.mqttClient.publish(f"inverter/batteryCapacity/{payload.subnode}",payload.batteryCapacity/1)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("inverterException", reading, ex)

    def beeMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadBeehive()
        if( emonSuite.EmonSerial.ParseBeehivePayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"beehive/beeInRate/{payload.subnode}",payload.beeInRate)
                self.mqttClient.publish(f"beehive/beeOutRate/{payload.subnode}",payload.beeOutRate)
                self.mqttClient.publish(f"beehive/beesIn/{payload.subnode}",payload.beesIn)
                self.mqttClient.publish(f"beehive/beesOut/{payload.subnode}",payload.beesOut)
                self.mqttClient.publish(f"temperature/beehiveIn/{payload.subnode}",payload.temperatureIn/100)
                self.mqttClient.publish(f"temperature/beehiveOut/{payload.subnode}",payload.temperatureOut/100)
                self.mqttClient.publish(f"supplyV/beehive/{payload.subnode}",payload.supplyV/1000)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("beehiveException", reading, ex)

    def airMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadAirQuality()
        if( emonSuite.EmonSerial.ParseAirQualityPayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"airQuality/pm0p3/{payload.subnode}",payload.pm0p3)
                self.mqttClient.publish(f"airQuality/pm0p5/{payload.subnode}",payload.pm0p5)
                self.mqttClient.publish(f"airQuality/pm1p0/{payload.subnode}",payload.pm1p0)
                self.mqttClient.publish(f"airQuality/pm2p5/{payload.subnode}",payload.pm2p5)
                self.mqttClient.publish(f"airQuality/pm5p0/{payload.subnode}",payload.pm5p0)
                self.mqttClient.publish(f"airQuality/pm10p0/{payload.subnode}",payload.pm10p0)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name']+" air", reading )
            except Exception as ex:
                self.printException("airQualityException", reading, ex)

    def leafMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadLeaf()
        if( emonSuite.EmonSerial.ParseLeafPayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"leaf/odometer/{payload.subnode}",payload.odometer)
                self.mqttClient.publish(f"leaf/range/{payload.subnode}",payload.range)
                self.mqttClient.publish(f"temperature/leaf/{payload.subnode}",payload.batteryTemperature)
                self.mqttClient.publish(f"leaf/batterySOH/{payload.subnode}",payload.batterySOH)
                self.mqttClient.publish(f"leaf/batteryWH/{payload.subnode}",payload.batteryWH)
                self.mqttClient.publish(f"leaf/batteryChargeBars/{payload.subnode}",payload.batteryChargeBars)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("leafException", reading, ex)

    def otherMessage(self, reading, nodeSettings ):
        print(reading)


    def process_line(self, command, line ):
        if(command in self.dispatch.keys()):
            self.dispatch[command](line, self.settings[command])
            # Now publish the entire string
            self.mqttClient.publish("EmonLog",line)
