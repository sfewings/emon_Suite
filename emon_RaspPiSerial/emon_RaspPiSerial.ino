//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_RaspPiSerial. Receive each packet from an emon group and write to Serial for RaspbeerryPi input
//-------------------------------------------------------------------------------------------------------------------------------------------------

#include <LowPower.h>
#define RF69_COMPAT 1


//JeeLab libraires				http://github.com/jcw
#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <EmonShared.h>

const int GREEN_LED = 9;  //Pin 9 on the Emon node.

RF12Init rf12Init = { EMON_LOGGER, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

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

	Serial.println(F("rf12_initialize"));
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);

	EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBasePayload(NULL);
	EmonSerial::PrintPulsePayload(NULL);
	EmonSerial::PrintDispPayload(NULL);
	EmonSerial::PrintTemperaturePayload(NULL);
	EmonSerial::PrintHWSPayload(NULL);
	EmonSerial::PrintWaterPayload(NULL);
	EmonSerial::PrintScalePayload(NULL);
	EmonSerial::PrintBatteryPayload(NULL);

	digitalWrite(GREEN_LED, LOW);
}

#define SERIAL_OUT(NAME, PAYLOAD)\
		Payload##NAME* pPayload = (Payload##NAME*)rf12_data; \
		EmonSerial::Print##NAME##PAYLOAD(pPayload);\




void loop () 
{
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

		if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)	// and no rf errors
		{
			int node_id = (rf12_hdr & 0x1F);
			int subnode = 0;

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
				PayloadWater* pPayload = (PayloadWater*)rf12_data;
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
		}
		

		digitalWrite(GREEN_LED, LOW);
	}
} 
