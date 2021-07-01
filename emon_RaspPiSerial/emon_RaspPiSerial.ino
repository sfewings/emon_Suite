//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_RaspPiSerial. Receive each packet from an emon group and write to Serial for RaspbeerryPi input
//-------------------------------------------------------------------------------------------------------------------------------------------------
#undef USE_JEELIB

#include <EmonShared.h>

#ifdef USE_JEELIB
	#define RF69_COMPAT 1

	//JeeLab libraires				http://github.com/jcw
	#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
	RF12Init rf12Init = { BASE_JEENODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };
#else
	#include <SPI.h>
	#include <RH_RF69.h>
	// Singleton instance of the radio driver
	RH_RF69 g_rf69;
	#define RFM69_RST     4
#endif


const int GREEN_LED = 9;  //Pin 9 on the Emon node.
//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, HIGH);		//Red LED has inverted logic. LOW is on, HIGH is off!
	Serial.begin(9600);
	
	delay(1000);
	Serial.println(F("Fewings Serial output for RaspberryPi"));
#ifdef USE_JEELIB
	Serial.println(F("rf12_initialize"));
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);
#else
	pinMode(RFM69_RST, OUTPUT);
	digitalWrite(RFM69_RST, LOW);
	delay(1);
	digitalWrite(RFM69_RST, HIGH);
	delay(10);
	digitalWrite(RFM69_RST, LOW);
	delay(10);


	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	Serial.println("RF69 initialise node: 10 Freq: 915MHz");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(BASE_JEENODE);
#endif

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

	digitalWrite(GREEN_LED, LOW);
}

#define SERIAL_OUT(NAME, PAYLOAD)\
		Payload##NAME* pPayload = (Payload##NAME*)data; \
		EmonSerial::Print##NAME##PAYLOAD(pPayload);\


void loop () 
{
	volatile uint8_t *data = NULL;
	int node_id = 0;

#ifdef USE_JEELIB
	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	if (rf12_recvDone())
	{
		digitalWrite(GREEN_LED, HIGH);

		if (rf12_crc)
		{
			Serial.print(F("rcv crc err:"));
			Serial.print(rf12_crc);
			Serial.print(F(",len:"));
			Serial.println(rf12_hdr);
		}

	//read the time basePayload 
		if (Serial.available())
		{
			char buf[100];
			PayloadBase basePayload;
			Serial.readBytesUntil('\0', buf, 100);
			if (EmonSerial::ParseBasePayload(buf, &basePayload))
			{
				int wait = 1000;
				while (!rf12_canSend() && wait--)
					rf12_recvDone();
				if (wait)
				{
					rf12_sendStart(0, &basePayload, sizeof basePayload);
					rf12_sendWait(0);
					Serial.println(F("BasePayload with time sent"));
					EmonSerial::PrintBasePayload(&basePayload);  //send it back down the serial line
				}
			}
		}

		if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)	// and no rf errors
		{
			node_id = (rf12_hdr & 0x1F);
			data = rf12_data;
#else
	if (g_rf69.available())
	{
		digitalWrite(GREEN_LED, HIGH);
		// Should be a message for us now   
		uint8_t buf[RH_RF69_MAX_MESSAGE_LEN];
		uint8_t len = sizeof(buf);
		if (g_rf69.recv(buf, &len))
		{
			//RH_RF69::printBuffer("Received: ", buf, len);
			//Serial.print("Got request: ");
			//Serial.print((char*)buf);
			Serial.print("RSSI: ");
			Serial.println(g_rf69.lastRssi(), DEC);

			node_id = g_rf69.headerId();
			data = buf;
#endif

			if (node_id == BASE_JEENODE)		
			{
				SERIAL_OUT(Base, Payload);
			}
			if (node_id == PULSE_JEENODE)
			{
				SERIAL_OUT(Pulse, Payload);
			}
			if (node_id == TEMPERATURE_JEENODE)
			{
				SERIAL_OUT(Temperature, Payload);
			}
			if (node_id == HWS_JEENODE )
			{
				SERIAL_OUT(HWS, Payload);
			}
			if (node_id == RAIN_NODE)				
			{
				SERIAL_OUT(Rain, Payload);
			}
			if (node_id == DISPLAY_NODE)
			{
				SERIAL_OUT(Disp, Payload);
			}
			if (node_id == WATERLEVEL_NODE)
			{
				PayloadWater* pPayload = (PayloadWater*)data;
				EmonSerial::UnpackWaterPayload((byte*)pPayload, pPayload);
				EmonSerial::PrintWaterPayload(pPayload);
			}
			if (node_id == SCALE_NODE)
			{
				SERIAL_OUT(Scale, Payload);
			}
			if (node_id == BATTERY_NODE)
			{
				SERIAL_OUT(Battery, Payload);
			}
			if (node_id == INVERTER_NODE)
			{
				SERIAL_OUT(Inverter, Payload);
			}
			if (node_id == BEEHIVEMONITOR_NODE)
			{
				SERIAL_OUT(Beehive, Payload);
			}
			if (node_id == AIRQUALITY_NODE)
			{
				SERIAL_OUT(AirQuality, Payload);
			}
		}

#ifdef USE_JEELIB
#else
		//read the time basePayload 
		if (Serial.available())
		{
			char sendBuf[100];
			PayloadBase basePayload;
			Serial.readBytesUntil('\0', sendBuf, 100);
			if (EmonSerial::ParseBasePayload(sendBuf, &basePayload))
			{
				g_rf69.send((const uint8_t*) &basePayload, sizeof(basePayload));
				if( g_rf69.waitPacketSent() )
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
#endif

		digitalWrite(GREEN_LED, LOW);
	}
} 
