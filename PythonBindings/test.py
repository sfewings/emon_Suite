import emonSuite
rain = "rain,100,3,2512,3456"
payload = emonSuite.PayloadRain()
emonSuite.EmonSerial.ParseRainPayload(rain,payload)