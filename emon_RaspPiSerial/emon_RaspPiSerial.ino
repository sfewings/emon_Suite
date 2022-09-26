//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_RaspPiSerial. Receive each packet from an emon group and write to Serial for RaspbeerryPi input
//Note: Use Moteino 8MHz for the Lora 8MHz boards
//-------------------------------------------------------------------------------------------------------------------------------------------------
#undef USE_JEELIB

#include <EmonShared.h>

#include <SPI.h>
#include <RH_RF95.h>
// Singleton instance of the radio driver
RH_RF95 g_rf95;
#define RFM69_RST     4

//const int GREEN_LED = 9;  //Pin 9 on the Emon node.

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
//	pinMode(GREEN_LED, OUTPUT);
//	digitalWrite(GREEN_LED, HIGH);		//Red LED has inverted logic. LOW is on, HIGH is off!
	Serial.begin(9600);
	
	delay(1000);
	Serial.println(F("Fewings Serial output for RaspberryPi"));

	pinMode(RFM69_RST, OUTPUT);
	digitalWrite(RFM69_RST, LOW);
	delay(1);
	digitalWrite(RFM69_RST, HIGH);
	delay(10);
	digitalWrite(RFM69_RST, LOW);
	delay(10);


	if (!g_rf95.init())
		Serial.println("rf69 init failed");
	if (!g_rf95.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	Serial.println("RF95 initialise node: 10 Freq: 915MHz");
	// The encryption key has to be the same as the one in the client
	// uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
	// 				0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	// g_rf95.setEncryptionKey(key);
	g_rf95.setHeaderId(BASE_JEENODE);


	EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBasePayload(NULL);
	EmonSerial::PrintPulsePayload(NULL);
	EmonSerial::PrintDispPayload(NULL);
	EmonSerial::PrintTemperaturePayload(NULL);
	EmonSerial::PrintHWSPayload(NULL);
	EmonSerial::PrintWaterPayload(NULL);
	EmonSerial::PrintScalePayload(NULL);
	EmonSerial::PrintBatteryPayload(NULL);
	EmonSerial::PrintInverterPayload(NULL);
	EmonSerial::PrintBeehivePayload(NULL);
	EmonSerial::PrintAirQualityPayload(NULL);
	EmonSerial::PrintLeafPayload(NULL);

//	digitalWrite(GREEN_LED, LOW);
}

#define SERIAL_OUT(NAME, PAYLOAD)\
		Payload##NAME* pPayload = (Payload##NAME*)data; \
		EmonSerial::Print##NAME##PAYLOAD(pPayload);\


void loop () 
{
	volatile uint8_t *data = NULL;
	uint8_t len = 0;
	int node_id = 0;

	if(g_rf95.available())
	{
		//digitalWrite(GREEN_LED, HIGH);
		// Should be a message for us now   
		uint8_t buf[RH_RF95_MAX_PAYLOAD_LEN];
		memset(buf, 0, RH_RF95_MAX_PAYLOAD_LEN);
		len = sizeof(buf);
		if (g_rf95.recv(buf, &len))
		{
			//RH_RF95::printBuffer("Received: ", buf, len);
			//Serial.print("Got request: ");
			//Serial.print((char*)buf);
			Serial.print("RSSI: ");
			Serial.println(g_rf95.lastRssi(), DEC);

			node_id = g_rf95.headerId();
			data = buf;

			if (node_id == BASE_JEENODE && len == sizeof(PayloadBase))		
			{
				SERIAL_OUT(Base, Payload);
			}
			if (node_id == PULSE_JEENODE && len == sizeof(PayloadPulse))
			{
				SERIAL_OUT(Pulse, Payload);
			}
			if (node_id == TEMPERATURE_JEENODE && len == sizeof(PayloadTemperature))
			{
				SERIAL_OUT(Temperature, Payload);
			}
			if (node_id == HWS_JEENODE  && len == sizeof(PayloadHWS))
			{
				SERIAL_OUT(HWS, Payload);
			}
			if (node_id == RAIN_NODE  && len == sizeof(PayloadRain))
			{
				SERIAL_OUT(Rain, Payload);
			}
			if (node_id == DISPLAY_NODE && len == sizeof(PayloadDisp))
			{
				SERIAL_OUT(Disp, Payload);
			}
			if (node_id == WATERLEVEL_NODE)
			{
				PayloadWater* pPayload = (PayloadWater*)data;
				int packedSize = EmonSerial::UnpackWaterPayload((byte*)pPayload, pPayload);
				if( len == packedSize)
				{
					EmonSerial::PrintWaterPayload(pPayload);
				}
			}
			if (node_id == SCALE_NODE  && len == sizeof(PayloadScale))
			{
				SERIAL_OUT(Scale, Payload);
			}
			if (node_id == BATTERY_NODE && len == sizeof(PayloadBattery))
			{
				SERIAL_OUT(Battery, Payload);
			}
			if (node_id == INVERTER_NODE  && len == sizeof(PayloadInverter))
			{
				SERIAL_OUT(Inverter, Payload);
			}
			if (node_id == BEEHIVEMONITOR_NODE  && len == sizeof(PayloadBeehive) )
			{
				SERIAL_OUT(Beehive, Payload);
			}
			if (node_id == AIRQUALITY_NODE  && len == sizeof(PayloadAirQuality))
			{
				SERIAL_OUT(AirQuality, Payload);
			}
			if (node_id == LEAF_NODE  && len == sizeof(PayloadLeaf))
			{
				SERIAL_OUT(Leaf, Payload);
			}
			if (node_id == BASE_JEENODE  && len == sizeof(PayloadBase))
			{
				SERIAL_OUT(Base, Payload);
			}
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
				g_rf95.send((const uint8_t*) &basePayload, sizeof(basePayload));
				if( g_rf95.waitPacketSent() )
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

		//digitalWrite(GREEN_LED, LOW);
	}
} 
