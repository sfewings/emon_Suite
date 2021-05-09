import emonSuite

def test1():
    rain = "rain,100,3,2512,3456"
    payload = emonSuite.PayloadRain()
    retVal = emonSuite.EmonSerial.ParseRainPayload(rain,payload)
    print('returnVal={},rainCount={},transmitCount={},tempertature={},supplyV={}'.format(retVal, payload.rainCount, payload.transmitCount, payload.temperature, payload.supplyV))

    temp = "temp: 4,2354,2381,2327,2350,2880"
    payload = emonSuite.PayloadTemperature()
    retVal = emonSuite.EmonSerial.ParseTemperaturePayload(temp,payload)
    print('returnVal={},subnode={},supplyV={},numSensors={}'.format(retVal, payload.subnode, payload.supplyV, payload.numSensors))
    for x in range(payload.numSensors):
        print("{}".format(payload.temperature[x]))

    print('MAX_SUBNODES = {}'.format(emonSuite.MAX_SUBNODES) )


