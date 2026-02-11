import pyemonlib.emonSuite as emonSuite
#from pyEmon.pyemonlib import emon_settings
import pyemonlib.emon_settings as emon_settings
import paho.mqtt.client as mqtt
import re

class emon_mqtt:
    def __init__(self, mqtt_server="localhost",mqtt_port=1883, settingsPath="./emon_config.yml"):
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
            'imu'  : self.imuMessage,
            'other': self.otherMessage
        }
        self.mqttClient = mqtt.Client()
        self.mqttClient.on_connect = self.on_connect
        self.mqttClient.connect(mqtt_server, mqtt_port, 120)
        self.mqttClient.loop_start()
        self.lineNumber = -1

    # def __del__(self):
    #     self.client.close()

    def on_connect(self, client, userdata, flags, rc):
        print(f"emon_mqtt:Connected with result code {rc}")

    def on_disconnect(self, client, userdata,rc=0):
        print("DisConnected result code {rc}")
        self.mqttClient.loop_stop()
    
    @property
    def settings(self):
        """Property to access current settings from settings manager."""
        return self.settings_manager.get_settings()
    
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
                    self.mqttClient.publish(f"water/flowCount/{payload.subnode}/{sensor}",\
                            payload.flowCount[sensor]*nodeSettings[payload.subnode][f"f{sensor}_litresPerPulse"])
                for sensor in range(payload.numHeightSensors):
                    self.mqttClient.publish(f"water/height/{payload.subnode}/{sensor}",payload.waterHeight[sensor]/1)
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

    def batteryMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadBattery()
        if( emonSuite.EmonSerial.ParseBatteryPayload(reading,payload) ):
            try:
                for sensor in range(emonSuite.BATTERY_SHUNTS):
                    if(nodeSettings[payload.subnode][f"s{sensor}"] != "Unused"):
                        self.mqttClient.publish(f"battery/power/{payload.subnode}/{sensor}", payload.power[sensor]/1)
                        self.mqttClient.publish(f"battery/pulseIn/{payload.subnode}/{sensor}", payload.pulseIn[sensor]/1)
                        self.mqttClient.publish(f"battery/pulseOut/{payload.subnode}/{sensor}", payload.pulseOut[sensor]/1)
                #if a vX_reference setting, get the mid voltages from the rail voltage reference
                refSensor = emon_mqtt.find_v_reference(nodeSettings[payload.subnode])
                if(refSensor != -1):                
                    railVoltage = payload.voltage[refSensor]/100.0  #voltages are in 100ths
                else:
                    railVoltage = 0.0
                for sensor in range(emonSuite.MAX_VOLTAGES):
                    voltage = payload.voltage[sensor]/100.0
                    if(refSensor != -1 and sensor != refSensor):
                        voltage = voltage - railVoltage/2.0
                    self.mqttClient.publish(f"battery/voltage/{payload.subnode}/{sensor}", voltage/1)
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
                self.mqttClient.publish(f"inverter/batteryVoltage/{payload.subnode}",payload.batteryVoltage/10)
                self.mqttClient.publish(f"inverter/batteryDicharge/{payload.subnode}",payload.batteryDischarge/1)
                self.mqttClient.publish(f"inverter/batteryCharging/{payload.subnode}",payload.batteryCharging/1)
                self.mqttClient.publish(f"inverter/pvInputPower/{payload.subnode}",payload.pvInputPower/1)
                self.mqttClient.publish(f"inverter/batteryCapacity/{payload.subnode}",payload.batteryCapacity/1)
                self.mqttClient.publish(f"inverter/pulse/{payload.subnode}",payload.pulse/1)
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
                self.mqttClient.publish(f"beehive/scale/{payload.subnode}",payload.grams/1)                
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
                self.mqttClient.publish(f"leaf/chargeTimeRemaining/{payload.subnode}",payload.chargeTimeRemaining)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("leafException", reading, ex)

    def gpsMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadGPS()
        if( emonSuite.EmonSerial.ParseGPSPayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"gps/latitude/{payload.subnode}",payload.latitude)
                self.mqttClient.publish(f"gps/longitude/{payload.subnode}",payload.longitude)
                self.mqttClient.publish(f"gps/course/{payload.subnode}",payload.course)
                self.mqttClient.publish(f"gps/speed/{payload.subnode}",payload.speed)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("GPSException", reading, ex)

    def pthMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadPressure()
        if( emonSuite.EmonSerial.ParsePressurePayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"pth/pressure/{payload.subnode}",payload.pressure)
                self.mqttClient.publish(f"temperature/pth/{payload.subnode}",payload.temperature)
                self.mqttClient.publish(f"pth/humidity/{payload.subnode}",payload.humidity)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("PressureException", reading, ex)

    def bmsMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadDalyBMS()
        if( emonSuite.EmonSerial.ParseDalyBMSPayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"bms/voltage{payload.subnode}",payload.batteryVoltage/10.0)
                self.mqttClient.publish(f"bms/batterySoC/{payload.subnode}",payload.batterySoC/10.0)
                self.mqttClient.publish(f"bms/power/{payload.subnode}",payload.current*payload.batteryVoltage/10.0)
                self.mqttClient.publish(f"bms/resCapacity/{payload.subnode}",payload.resCapacity)
                self.mqttClient.publish(f"temperature/bms/{payload.subnode}",payload.temperature)
                self.mqttClient.publish(f"bms/lifetimeCycles{payload.subnode}",payload.lifetimeCycles)
                for cell in range(emonSuite.MAX_BMS_CELLS):
                    self.mqttClient.publish(f"bms/cellVoltage/{payload.subnode}/{cell}",payload.cellmv[cell]/1000.0)                    
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("DalyBMSException", reading, ex)

    def sevConMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadSevCon()
        if( emonSuite.EmonSerial.ParseSevConPayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"sevCon/temperature/motor/{payload.subnode}",payload.motorTemperature)
                self.mqttClient.publish(f"sevCon/temperature/controller/{payload.subnode}",payload.controllerTemperature)
                self.mqttClient.publish(f"sevCon/voltage{payload.subnode}",payload.capVoltage)
                self.mqttClient.publish(f"sevCon/current{payload.subnode}",payload.batteryCurrent)
                self.mqttClient.publish(f"sevCon/rpm{payload.subnode}",payload.rpm)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("SevConException", reading, ex)

    def mwvMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadAnemometer()
        if( emonSuite.EmonSerial.ParseAnemometerPayload(reading,payload) ):
            try:
                self.mqttClient.publish(f"anemometer/temperature/{payload.subnode}",payload.temperature)
                self.mqttClient.publish(f"anemometer/windSpeed/{payload.subnode}",payload.windSpeed)
                self.mqttClient.publish(f"anemometer/windDirection/{payload.subnode}",payload.windDirection)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("AnemometerException", reading, ex)

    def imuMessage(self, reading, nodeSettings ):
        payload = emonSuite.PayloadIMU()
        if( emonSuite.EmonSerial.ParseIMUPayload(reading,payload) ):
            try:
                for axis in range(3):
                    self.mqttClient.publish(f"imu/{payload.subnode}/acc/{axis}",float(payload.acc[axis]))
                for axis in range(3):
                    self.mqttClient.publish(f"imu/{payload.subnode}/mag/{axis}",float(payload.mag[axis]))
                for axis in range(3):
                    self.mqttClient.publish(f"imu/{payload.subnode}/gyro/{axis}",float(payload.gyro[axis]))
                self.mqttClient.publish(f"imu/{payload.subnode}/heading",payload.heading)
                if(':' in reading):
                    self.publishRSSI( nodeSettings[payload.subnode]['name'], reading )
            except Exception as ex:
                self.printException("IMUException", reading, ex)


    def otherMessage(self, reading, nodeSettings ):
        print(reading)

    def check_int(self, s):
        if s[0] in ('-', '+'):
            return s[1:].isdigit()
        return s.isdigit()

    def process_line(self, line ):
        # Check if settings need to be reloaded
        self.settings_manager.check_and_reload_settings()
        
        lineFields = line.split(',',2)
        command = lineFields[0].rstrip('0123456789')
        if( len(lineFields)<3 or not self.check_int(lineFields[1])):
           raise ValueError(f"Invalid line format: {line}")
        if not command in self.settings_manager.get_current_nodes():
            raise ValueError(f"No current configuration for node: {command} in line: {line}")
        if(not command in self.dispatch.keys()):
            raise ValueError(f"Unknown device: {command} in line: {line}")
        
        self.dispatch[command](line, self.settings[command])
        # Now publish the entire string
        self.mqttClient.publish("EmonLog",line)
