import pyemonlib.emonSuite as emonSuite


def test1():
    print("MAX_SUBNODES           = {}".format(emonSuite.MAX_SUBNODES           ) )
    print("MAX_WATER_SENSORS      = {}".format(emonSuite.MAX_WATER_SENSORS      ) )
    print("PULSE_MAX_SENSORS      = {}".format(emonSuite.PULSE_MAX_SENSORS      ) )
    print("MAX_TEMPERATURE_SENSORS= {}".format(emonSuite.MAX_TEMPERATURE_SENSORS) )
    print("HWS_TEMPERATURES       = {}".format(emonSuite.HWS_TEMPERATURES       ) )
    print("HWS_PUMPS              = {}".format(emonSuite.HWS_PUMPS              ) )
    print("BATTERY_SHUNTS         = {}".format(emonSuite.BATTERY_SHUNTS         ) )
    print("MAX_VOLTAGES           = {}".format(emonSuite.MAX_VOLTAGES           ) )

    rain = "rain,100,3,2512,3456"
    payload = emonSuite.PayloadRain()
    retVal = emonSuite.EmonSerial.ParseRainPayload(rain,payload)
    print('returnVal={},rainCount={},transmitCount={},tempertature={},supplyV={}'.format(retVal, payload.rainCount, payload.transmitCount, payload.temperature, payload.supplyV))


    #TEMP_MSG = "temp,4,2354,2381,2327,2350,2880"
    TEMP_MSG = "temp1,0,4149,4,3554,2513,2651,3606"
    payload = emonSuite.PayloadTemperature()
    retVal = emonSuite.EmonSerial.ParseTemperaturePayload(TEMP_MSG,payload)
    print('returnVal={},subnode={},supplyV={},numSensors={}'.format(retVal, payload.subnode, payload.supplyV, payload.numSensors))
    print("temperature", end='')
    for x in range(payload.numSensors):
        print(",{}".format(payload.temperature[x]), end='')
    print("")


    DISP_MSG = "disp1,3,2425|00000010"
    payload = emonSuite.PayloadDisp()
    retVal = emonSuite.EmonSerial.ParseDispPayload(DISP_MSG,payload)
    print('returnVal={},subnode={},temperature={}'.format(retVal, payload.subnode, payload.temperature))


    PULSE_MSG = "pulse2,3,0,422,61,748650,7417037,10674727,4105306,3236"
    print(PULSE_MSG)
    payload = emonSuite.PayloadPulse()
    retVal = emonSuite.EmonSerial.ParsePulsePayload(PULSE_MSG,payload)
    print('returnVal={},supplyV={}'.format(retVal, payload.supplyV))
    print("power", end = '')
    for x in range(emonSuite.PULSE_MAX_SENSORS):
        print(",{}".format(payload.power[x]), end = '')
    print("")
    print("pulse", end = '')
    for x in range(emonSuite.PULSE_MAX_SENSORS):
        print(",{}".format(payload.pulse[x]), end = '')
    print("")

    HWS_MESSAGE = "hws,19,49,50,52,52,52,39,0,0,0|00000010"
    print(HWS_MESSAGE)
    payload = emonSuite.PayloadHWS()
    retVal = emonSuite.EmonSerial.ParseHWSPayload(HWS_MESSAGE,payload)
    print('returnVal={}'.format(retVal))
    print("temperature", end = '')
    for x in range(emonSuite.HWS_TEMPERATURES):
        print(",{}".format(payload.temperature[x]), end = '')
    print("")
    print("pump", end = '')
    for x in range(emonSuite.HWS_PUMPS):
        print(",{}".format(payload.pump[x]), end = '')
    print("")

    BASE_MESSAGE = "base,1622160032"
    print(BASE_MESSAGE)
    payload = emonSuite.PayloadBase()
    retVal = emonSuite.EmonSerial.ParseBasePayload(BASE_MESSAGE,payload)
    print('returnVal={}'.format(retVal))
    print("time")

    WATER_MESSAGE = "wtr3,1,4096,2,962290,552769|00000100"
    print(WATER_MESSAGE)
    payload = emonSuite.PayloadWater()
    retVal = emonSuite.EmonSerial.ParseWaterPayload(WATER_MESSAGE,payload)
    print('returnVal={}'.format(retVal))
    print(f"subnode={payload.subnode}")
    print(f"supplyV={payload.supplyV}")
    print(f"numFlowSensors={payload.numFlowSensors}", end = '')
    for x in range(payload.numFlowSensors):
        print(",{}".format(payload.flowCount[x]), end = '')
    print("")
    print(f'numHeightSensors={payload.numHeightSensors}', end = '')
    for x in range(payload.numHeightSensors):
        print(",{}".format(payload.waterHeight[x]), end = '')
    print("")

    #               "scl,1,853,3283"
    SCALE_MESSAGE = "scl,0,1522,3352"
    print(SCALE_MESSAGE)
    payload = emonSuite.PayloadScale()
    retVal = emonSuite.EmonSerial.ParseScalePayload(SCALE_MESSAGE,payload)
    print('returnVal={}'.format(retVal))
    print(f"subnode={payload.subnode}")
    print(f"supplyV={payload.supplyV}")
    print(f"grams={payload.grams}")
    
    BATTERY_MESSAGE = "bat2,0,-173,-148,-13,1207598,2822473,42932,875943,11412025,15694,4983,2487,2497,2488,2467,2513,2484,2477,2480" 
    #BATTERY_MESSAGE = "bat2,0,-164,-295,-62,2062374,3376011,227946,1360428,11711291,127177,4888,2437,2446,2425,2414,2505,2434,2428,2429"
    print(BATTERY_MESSAGE)
    payload = emonSuite.PayloadBattery()
    retVal = emonSuite.EmonSerial.ParseBatteryPayload(BATTERY_MESSAGE,payload)
    print('returnVal={}'.format(retVal))
    print(f"subnode={payload.subnode}")
    print("power", end = '')
    for x in range(emonSuite.BATTERY_SHUNTS):
        print(",{}".format(payload.power[x]), end = '')
    print("")
    print("pulseIn", end = '')
    for x in range(emonSuite.BATTERY_SHUNTS):
        print(",{}".format(payload.pulseIn[x]), end = '')
    print("")
    print("pulseOut", end = '')
    for x in range(emonSuite.BATTERY_SHUNTS):
        print(",{}".format(payload.pulseOut[x]), end = '')
    print("")
    print("voltage", end = '')
    for x in range(emonSuite.MAX_VOLTAGES):
        print(",{}".format(payload.voltage[x]), end = '')
    print("")

    INVERTER_MESSAGE = "inv2,1,124,191,487,3,0,2,77"
    print(INVERTER_MESSAGE)
    payload = emonSuite.PayloadInverter()
    retVal = emonSuite.EmonSerial.ParseInverterPayload(INVERTER_MESSAGE,payload)
    print('returnVal={}'.format(retVal))
    print(f"subnode={payload.subnode}")
    print(f"activePower={payload.activePower}")
    print(f"apparentPower={payload.apparentPower}")
    print(f"batteryVoltage={payload.batteryVoltage}")
    print(f"batteryDischarge={payload.batteryDischarge}")
    print(f"batteryCharging={payload.batteryCharging}")
    print(f"pvInputPower={payload.pvInputPower}")
    print(f"batteryCapacity={payload.batteryCapacity}")


    BEEHIVE_MESSAGE = "bee,0,19,20,1123456,1234567,3215,2327,20456,4512"
    print(BEEHIVE_MESSAGE)
    payload = emonSuite.PayloadBeehive()
    retVal = emonSuite.EmonSerial.ParseBeehivePayload(BEEHIVE_MESSAGE,payload)
    print('returnVal={}'.format(retVal))
    print(f"subnode={payload.subnode}")
    print(f"beeInRate={payload.beeInRate}")
    print(f"beeOutRate={payload.beeOutRate}")
    print(f"beesIn={payload.beesIn}")
    print(f"beesOut={payload.beesOut}")
    print(f"temperatureIn={payload.temperatureIn}")
    print(f"temperatureOut={payload.temperatureOut}")
    print(f"grams={payload.grams}")

    AIRQUALITY_MESSAGE = "air,0,1779,502,114,15,4,0"
    print(AIRQUALITY_MESSAGE)
    payload = emonSuite.PayloadAirQuality()
    retVal = emonSuite.EmonSerial.ParseAirQualityPayload(AIRQUALITY_MESSAGE,payload)
    print('returnVal={}'.format(retVal))
    print(f"subnode={payload.subnode}")
    print(f"pm0p3={payload.pm0p3}")
    print(f"pm0p5={payload.pm0p5}")
    print(f"pm1p0={payload.pm1p0}")
    print(f"pm2p5={payload.pm2p5}")
    print(f"pm5p0={payload.pm5p0}")
    print(f"pm10p0={payload.pm10p0}")

    LEAF_MESSAGE = "leaf,0,57876,77,36,64,11440,8"
    print(LEAF_MESSAGE)
    payload = emonSuite.PayloadLeaf()
    retval = emonSuite.EmonSerial.ParseLeafPayload(LEAF_MESSAGE, payload)
    print('returnVal={}'.format(retVal))
    print(f"subnode={payload.subnode}")
    print(f"odometer={payload.odometer}")
    print(f"range={payload.range}")
    print(f"batteryTemperature={payload.batteryTemperature}")
    print(f"batterySOH={payload.batterySOH}")
    print(f"batteryWH={payload.batteryWH}")
    print(f"batteryChargeBars={payload.batteryChargeBars}")

if __name__ == '__main__':
    test1()

