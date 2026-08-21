//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_SerialToRF. Receive text data packets from Serial, parse them, and transmit as RF packets.
//  This is the reverse of emon_RaspPiSerial which receives RF packets and writes them to Serial.
//  Text format matches the EmonSerial::Print*Payload() output format.
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <avr/wdt.h>    //watchdog timer

#include <EmonShared.h>
#include <SPI.h>

#undef LORA_RF95

#ifdef LORA_RF95
	//Note: Use board config Moteino 8MHz for the Lora 8MHz boards
	#include <RH_RF95.h>
	RH_RF95 g_rfRadio;
	#define RADIO_BUF_LEN   RH_RF95_MAX_PAYLOAD_LEN
#else
	#include <RH_RF69.h>
	RH_RF69 g_rfRadio;
	#define RADIO_BUF_LEN   RH_RF69_MAX_MESSAGE_LEN
	#define GREEN_LED 		9
	#define RFM69_RST     	4
#endif

//#define HOUSE_BANNER
#define BOAT_BANNER
#ifdef HOUSE_BANNER
    #define NETWORK_FREQUENCY 915.0
#elif defined(BOAT_BANNER)
    #define NETWORK_FREQUENCY 914.0
#endif


void SetLed(uint8_t val)
{
#ifndef LORA_RF95
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, val );
#endif
}

bool sendPacket(uint8_t nodeId, const uint8_t* data, uint8_t len)
{
	g_rfRadio.setHeaderId(nodeId);
	g_rfRadio.send(data, len);
	if( g_rfRadio.waitPacketSent() )
	{
		return true;
	}
	else
	{
		Serial.println(F("No packet sent"));
		return false;
	}
}

#define PARSE_AND_SEND(NAME, NODE_ID)\
	{\
		Payload##NAME payload;\
		if (EmonSerial::Parse##NAME##Payload(buf, &payload))\
		{\
			if(sendPacket(NODE_ID, (const uint8_t*)&payload, sizeof(payload)))\
				EmonSerial::Print##NAME##Payload(&payload);\
		}\
		else\
		{\
			Serial.println(F("Parse failed: " #NAME));\
		}\
	}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup ()
{
	SetLed(HIGH);
	Serial.begin(9600);
	delay(1000);
	Serial.println(F("emon_SerialToRF: Serial input to RF transmitter"));

#ifndef LORA_RF95
	pinMode(RFM69_RST, OUTPUT);
	digitalWrite(RFM69_RST, LOW);
	delay(1);
	digitalWrite(RFM69_RST, HIGH);
	delay(10);
	delay(10);
#endif

	if (!g_rfRadio.init())
		Serial.println("rf radio init failed");
	if (!g_rfRadio.setFrequency(NETWORK_FREQUENCY))
		Serial.println("rf setFrequency failed");
	Serial.print("RF69 initialise Freq: ");Serial.print(NETWORK_FREQUENCY,1); Serial.println("MHz");

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
	EmonSerial::PrintGPSPayload(NULL);
	EmonSerial::PrintPressurePayload(NULL);
	EmonSerial::PrintDalyBMSPayload(NULL);
	EmonSerial::PrintSevConPayload(NULL);
	EmonSerial::PrintAnemometerPayload(NULL);
	EmonSerial::PrintIMUPayload(NULL);

#ifndef LORA_RF95
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
	 				0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rfRadio.setEncryptionKey(key);
#endif
  	wdt_enable(WDTO_8S);

	SetLed(LOW);
}

//--------------------------------------------------------------------------------------------
// Extract the payload prefix from a text line (e.g. "rain" from "rain,1234,5,200,3300")
// Returns the length of the prefix, or 0 on error
//--------------------------------------------------------------------------------------------
int getPrefix(const char* buf, char* prefix, int maxLen)
{
	int i = 0;
	while (i < maxLen - 1 && buf[i] != ',' && buf[i] != '\0' && buf[i] != '\n' && buf[i] != '\r')
	{
		prefix[i] = buf[i];
		i++;
	}
	prefix[i] = '\0';
	return i;
}


//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop ()
{
	wdt_reset();

	if (Serial.available())
	{
		char buf[256];
		memset(buf, 0, sizeof(buf));
		int len = Serial.readBytesUntil('\n', buf, sizeof(buf) - 1);
		if (len <= 0)
			return;

		//strip trailing \r
		if (len > 0 && buf[len - 1] == '\r')
			buf[--len] = '\0';

		SetLed(HIGH);

		//extract the prefix to determine payload type
		char prefix[16];
		if (getPrefix(buf, prefix, sizeof(prefix)) == 0)
		{
			SetLed(LOW);
			return;
		}

		if (strcmp(prefix, "rain") == 0)
		{
			PARSE_AND_SEND(Rain, RAIN_NODE);
		}
		else if (strcmp(prefix, "base") == 0)
		{
			PARSE_AND_SEND(Base, BASE_JEENODE);
		}
		else if (strcmp(prefix, "disp") == 0 || strcmp(prefix, "disp1") == 0)
		{
			PARSE_AND_SEND(Disp, DISPLAY_NODE);
		}
		else if (strcmp(prefix, "pulse") == 0 || strcmp(prefix, "pulse2") == 0 || strcmp(prefix, "pulse3") == 0)
		{
			PARSE_AND_SEND(Pulse, PULSE_JEENODE);
		}
		else if (strcmp(prefix, "temp") == 0 || strcmp(prefix, "temp1") == 0)
		{
			PARSE_AND_SEND(Temperature, TEMPERATURE_JEENODE);
		}
		else if (strcmp(prefix, "hws") == 0)
		{
			PARSE_AND_SEND(HWS, HWS_JEENODE);
		}
		else if (strcmp(prefix, "wtr") == 0 || strcmp(prefix, "wtr1") == 0 || strcmp(prefix, "wtr2") == 0 || strcmp(prefix, "wtr3") == 0)
		{
			//Water payload needs packing before transmission
			PayloadWater payload;
			if (EmonSerial::ParseWaterPayload(buf, &payload))
			{
				uint8_t packedBuf[sizeof(PayloadWater)];
				int packedSize = EmonSerial::PackWaterPayload(&payload, packedBuf);
				if (packedSize > 0)
				{
					if(sendPacket(WATERLEVEL_NODE, packedBuf, packedSize))
						EmonSerial::PrintWaterPayload(&payload);
				}
				else
				{
					Serial.println(F("Pack failed: Water"));
				}
			}
			else
			{
				Serial.println(F("Parse failed: Water"));
			}
		}
		else if (strcmp(prefix, "scl") == 0)
		{
			PARSE_AND_SEND(Scale, SCALE_NODE);
		}
		else if (strcmp(prefix, "bat") == 0 || strcmp(prefix, "bat2") == 0)
		{
			PARSE_AND_SEND(Battery, BATTERY_NODE);
		}
		else if (strcmp(prefix, "inv") == 0 || strcmp(prefix, "inv2") == 0 || strcmp(prefix, "inv3") == 0)
		{
			PARSE_AND_SEND(Inverter, INVERTER_NODE);
		}
		else if (strcmp(prefix, "bee") == 0)
		{
			PARSE_AND_SEND(Beehive, BEEHIVEMONITOR_NODE);
		}
		else if (strcmp(prefix, "air") == 0)
		{
			PARSE_AND_SEND(AirQuality, AIRQUALITY_NODE);
		}
		else if (strcmp(prefix, "leaf") == 0 || strcmp(prefix, "leaf2") == 0)
		{
			PARSE_AND_SEND(Leaf, LEAF_NODE);
		}
		else if (strcmp(prefix, "gps") == 0)
		{
			PARSE_AND_SEND(GPS, GPS_NODE);
		}
		else if (strcmp(prefix, "pth") == 0)
		{
			PARSE_AND_SEND(Pressure, PRESSURE_NODE);
		}
		else if (strcmp(prefix, "bms") == 0)
		{
			PARSE_AND_SEND(DalyBMS, DALY_BMS_NODE);
		}
		else if (strcmp(prefix, "svc") == 0)
		{
			PARSE_AND_SEND(SevCon, SEVCON_CAN_NODE);
		}
		else if (strcmp(prefix, "mwv") == 0)
		{
			PARSE_AND_SEND(Anemometer, ANEMOMETER_NODE);
		}
		else if (strcmp(prefix, "imu") == 0)
		{
			PARSE_AND_SEND(IMU, IMU_NODE);
		}
		else
		{
			Serial.print(F("Unknown payload type: "));
			Serial.println(prefix);
		}

		SetLed(LOW);
	}
}
