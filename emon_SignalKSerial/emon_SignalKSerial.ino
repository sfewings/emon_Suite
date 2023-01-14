//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_SignalKSerial. Receive each packet from an emon group and write to Serial for RaspbeerryPi input
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <EmonShared.h>
#include <SPI.h>

#include <RH_RF69.h>
RH_RF69 g_rfRadio;
#define RADIO_BUF_LEN   RH_RF69_MAX_MESSAGE_LEN
#define GREEN_LED 		9
#define RFM69_RST     	4


void SetLed(uint8_t val)
{
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, val );
}

void PrintSignalK_GPSPayload(PayloadGPS *pPayloadGPS )
{
  //Update header
//   Serial.print(F(    "{"
//                            //"\"context\": \"vessels.urn:mrn:imo:mmsi:AU-TWA030116CJ4\","
//                            "\"updates\": [{"
//                            "\"source\": {"
//                            "\"label\": \"Arduino SignalK\","
//                            "\"type\": \"signalk\""
//                            "},"
//                            //"\"timestamp\": \"" ));

  Serial.print(F(    "{"
                           "\"updates\": [{"
                           "\"source\": {"
                           "\"label\": \"Arduino_SignalK\","
                           "\"type\": \"signalk\""
                           "},"));

  //timstamp
//   char buf[24];
//   snprintf_P(buf,24,PSTR("%04d-%02d-%02dT%02d:%02d:%02dZ"),year(), month(), day(), hour(), minute(), second() );
//   Serial.print(buf);
//   Serial.print(F("\","));
  
  Serial.print(F("\"values\": ["));
  
  Serial.print(F("{\"path\": \"navigation.position.latitude\",\"value\":"));
  Serial.print(pPayloadGPS->latitude,7);
  Serial.print(F("},"));

  Serial.print(F("{\"path\": \"navigation.position.longitude\",\"value\":"));
  Serial.print(pPayloadGPS->longitude,7);
  Serial.print(F("},"));

  Serial.print(F("{\"path\": \"navigation.courseOverGroundTrue\",\"value\":"));
  Serial.print(pPayloadGPS->course,2);
  Serial.print(F("},"));

  Serial.print(F("{\"path\": \"navigation.speedOverGround\",\"value\":"));
  Serial.print(pPayloadGPS->speed*0.514444,1);   //knots to m/s
  Serial.print(F("}]}]}")); //path/value "}"" values "]", updates "}]", final "}"
}

void PrintSignalK_TemperaturePayload(PayloadTemperature *pPayloadTemperature )
{
  //Update header
  Serial.print(F(    "{"
                           "\"context\": \"vessels.urn:mrn:imo:mmsi:AU-TWA030116CJ4\","
                           "\"updates\": [{"
                           "\"source\": {"
                           "\"label\": \"Arduino SignalK\","
                           "\"type\": \"signalk\""
                           "},"
                           "\"timestamp\": \"" ));

  //timstamp
  char buf[24];
  snprintf_P(buf,24,PSTR("%04d-%02d-%02dT%02d:%02d:%02dZ"),year(), month(), day(), hour(), minute(), second() );
  Serial.print(buf);

  Serial.print(F("\",\"values\": ["));
  
  for(int i=0; i< pPayloadTemperature->numSensors; i++)
  {
	Serial.print(F("{\"path\": \"environment.outside.bimini.temperature\",\"value\":"));
	Serial.print((float)pPayloadTemperature->temperature[i]/100.0, 2);
	Serial.print(F("},"));
  }

  Serial.print(F("{\"path\": \"electrical.batteries.bimini.voltage\",\"value\":"));
  Serial.print((float)pPayloadTemperature->supplyV/100.0,2);

  Serial.print(F("}]}]}")); //path/value "}"" values "]", updates "}]", final "}"
}

void PrintSignalK_PressurePayload(PayloadPressure* pPressurePayload )
{
  //Update header
  Serial.print(F(    "{"
                           "\"context\": \"vessels.urn:mrn:imo:mmsi:AU-TWA030116CJ4\","
                           "\"updates\": [{"
                           "\"source\": {"
                           "\"label\": \"Arduino SignalK\","
                           "\"type\": \"signalk\""
                           "},"
                           "\"timestamp\": \"" ));

  //timstamp
  char buf[24];
  snprintf_P(buf,24,PSTR("%04d-%02d-%02dT%02d:%02d:%02dZ"),year(), month(), day(), hour(), minute(), second() );
  Serial.print(buf);

  Serial.print(F("\",\"values\": ["));
  
  Serial.print(F("{\"path\": \"environment.inside.pressure\",\"value\":"));
  Serial.print(pPressurePayload->pressure,2);
  Serial.print(F("},"));

  Serial.print(F("{\"path\": \"environment.inside.temperature\",\"value\":"));
  Serial.print(pPressurePayload->temperature,2);
  Serial.print(F("},"));

  Serial.print(F("{\"path\": \"environment.inside.humidity\",\"value\":"));
  Serial.print(pPressurePayload->humidity,2);

  Serial.print(F("}]}]}")); //path/value "}"" values "]", updates "}]", final "}"
}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
	SetLed(HIGH);
	Serial.begin(9600);
	delay(1000);
	Serial.println(F("SignalK Serial output for RaspberryPi"));

	pinMode(RFM69_RST, OUTPUT);
	digitalWrite(RFM69_RST, LOW);
	delay(1);
	digitalWrite(RFM69_RST, HIGH);
	delay(10);
	delay(10);

	if (!g_rfRadio.init())
		Serial.println("rf radio init failed");
	if (!g_rfRadio.setFrequency(914.0))
		Serial.println("rf setFrequency failed");
	g_rfRadio.setHeaderId(BASE_JEENODE);

	EmonSerial::PrintTemperaturePayload(NULL);
	EmonSerial::PrintGPSPayload(NULL);
	EmonSerial::PrintPressurePayload(NULL);

	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
	 				0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rfRadio.setEncryptionKey(key);

	SetLed(LOW);
}

#define SIGNALK_OUT(NAME, PAYLOAD)\
		Payload##NAME* pPayload = (Payload##NAME*)data; \
		PrintSignalK_##NAME##PAYLOAD(pPayload);\

#define SERIAL_OUT(NAME, PAYLOAD)\
		Payload##NAME* pPayload = (Payload##NAME*)data; \
		EmonSerial::Print##NAME##PAYLOAD(pPayload);\


void loop () 
{
	volatile uint8_t *data = NULL;
	uint8_t len = 0;
	int node_id = 0;

	if(g_rfRadio.available())
	{
		SetLed(HIGH);
		uint8_t buf[RADIO_BUF_LEN];
		memset(buf, 0, RADIO_BUF_LEN);

		len = sizeof(buf);
		if (g_rfRadio.recv(buf, &len))
		{
			//RH_RF95::printBuffer("Received: ", buf, len);
			//Serial.print("Got request: ");
			//Serial.print((char*)buf);
			//Serial.print("RSSI: ");
			//Serial.println(g_rfRadio.lastRssi(), DEC);

			node_id = g_rfRadio.headerId();
			data = buf;

			if (node_id == GPS_NODE && len == sizeof(PayloadGPS))
			{
				//SIGNALK_OUT(GPS, Payload);
				SERIAL_OUT(GPS, Payload);
			}
			if (node_id == PRESSURE_NODE && len == sizeof(PayloadPressure))
			{
				//SIGNALK_OUT(Pressure, Payload);
				SERIAL_OUT(Pressure, Payload);
			}
			if (node_id == TEMPERATURE_JEENODE && len == sizeof(PayloadTemperature))
			{
				//SIGNALK_OUT(Temperature, Payload);
				SERIAL_OUT(Temperature, Payload);
			}
			// if (node_id == BASE_JEENODE && len == sizeof(PayloadBase))		
			// {
			// 	SIGNALK_OUT(Base, Payload);
			// }
			// if (node_id == PULSE_JEENODE && len == sizeof(PayloadPulse))
			// {
			// 	SERIAL_OUT(Pulse, Payload);
			// }
			// if (node_id == HWS_JEENODE  && len == sizeof(PayloadHWS))
			// {
			// 	SERIAL_OUT(HWS, Payload);
			// }
			// if (node_id == RAIN_NODE  && len == sizeof(PayloadRain))
			// {
			// 	SERIAL_OUT(Rain, Payload);
			// }
			// if (node_id == DISPLAY_NODE && len == sizeof(PayloadDisp))
			// {
			// 	SERIAL_OUT(Disp, Payload);
			// }
			// if (node_id == WATERLEVEL_NODE)
			// {
			// 	PayloadWater* pPayload = (PayloadWater*)data;
			// 	int packedSize = EmonSerial::UnpackWaterPayload((byte*)pPayload, pPayload);
			// 	if( len == packedSize)
			// 	{
			// 		EmonSerial::PrintWaterPayload(pPayload);
			// 	}
			// }
			// if (node_id == SCALE_NODE  && len == sizeof(PayloadScale))
			// {
			// 	SERIAL_OUT(Scale, Payload);
			// }
			// if (node_id == BATTERY_NODE && len == sizeof(PayloadBattery))
			// {
			// 	SERIAL_OUT(Battery, Payload);
			// }
			// if (node_id == INVERTER_NODE  && len == sizeof(PayloadInverter))
			// {
			// 	SERIAL_OUT(Inverter, Payload);
			// }
			// if (node_id == BEEHIVEMONITOR_NODE  && len == sizeof(PayloadBeehive) )
			// {
			// 	SERIAL_OUT(Beehive, Payload);
			// }
			// if (node_id == AIRQUALITY_NODE  && len == sizeof(PayloadAirQuality))
			// {
			// 	SERIAL_OUT(AirQuality, Payload);
			// }
			// if (node_id == LEAF_NODE  && len == sizeof(PayloadLeaf))
			// {
			// 	SERIAL_OUT(Leaf, Payload);
			// }
		}

		//read the time basePayload 
		if (Serial.available())
		{
			char sendBuf[100];
			memset(sendBuf, 0, 100);
			PayloadBase basePayload;
			Serial.readBytesUntil('\0', sendBuf, 100);
			if (EmonSerial::ParseBasePayload(sendBuf, &basePayload) )
			{
				g_rfRadio.send((const uint8_t*) &basePayload, sizeof(basePayload));
				if( g_rfRadio.waitPacketSent() )
				{
					Serial.println(F("BasePayload with time sent"));
					EmonSerial::PrintBasePayload(&basePayload);  //send it back down the serial line
				}
				else
				{
					Serial.println(F("No packet sent"));
				}
			}
		}

		SetLed(LOW);
	}
} 
