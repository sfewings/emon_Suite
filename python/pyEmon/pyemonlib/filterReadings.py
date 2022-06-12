import pyemonlib.emonSuite as emonSuite

WATER_MAX_INCREMENT = 100
PULSE_MAX_INCREMENT = 100
ODOMETER_MAX_INCREMENT = 100
RAIN_MAX_INCREMENT = 20
TEMPERATURE_MAX_INCREMENT = 50  #100ths of a degree
SUPPLY_VOLTAGE_MAX_INCREMENT = 50  #100ths of a volt

class filterReadings:
    def __init__(self):
        self.lastReading = {}


    def validCounterReading(self, readingID, value, MAX_INCREMENT):
        if( not readingID in self.lastReading ):
            self.lastReading[readingID] = value
        else:
            if value < self.lastReading[readingID]:
                return False
            elif value < self.lastReading[readingID] + MAX_INCREMENT:
                self.lastReading[readingID] = value
        return True

    def validRainPayload(self, rainPayload):
        if( not self.validCounterReading("rain.rainCount", rainPayload.rainCount, RAIN_MAX_INCREMENT) or
            not self.validCounterReading("rain.temperature", rainPayload.temperature, TEMPERATURE_MAX_INCREMENT) or
            not self.validCounterReading("rain.voltage", rainPayload.voltage, SUPPLY_VOLTAGE_MAX_INCREMENT):
            return False


    def isValid(self, readingID, value):
        readingIDelements = readingID.split('/')
        if readingIDelements[0] == 'temperature':
            if value < -120 or value > 120:
                return False
        elif(readingIDelements[0] == 'supplyV'):
            if( value < 0 or value > 24000):
                return False
        elif(readingIDelements[0] =='water'):
            if( readingIDelements[1] == 'flowCount'):
                return self.validCounterReading(readingID, value, WATER_MAX_INCREMENT)
        elif(readingIDelements[0] == 'pulse'):
            return self.validCounterReading(readingID, value, PULSE_MAX_INCREMENT)
        elif(readingIDelements[0] == 'leaf'):
            if( readingIDelements[1] == 'batteryWH'):
                if( value >24000):
                    return False
            if( readingIDelements[1] == 'odometer'):
                return self.validCounterReading(readingID, value, ODOMETER_MAX_INCREMENT)
        elif(readingIDelements[0] == 'rain'):
            return self.validCounterReading(readingID, value, RAIN_MAX_INCREMENT)
        elif(readingIDelements[0] == 'battery'):
            if( readingIDelements[1] == 'pulseIn' or readingIDelements[1] == 'pulseOut'):
                return self.validCounterReading(readingID, value, PULSE_MAX_INCREMENT)

        return True 