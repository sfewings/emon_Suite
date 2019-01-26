#include <JeeLib.h>
//Temperature support - OneWire Dallas temperature sensor

#include <Ports.h>
#include <RF12.h>
#include <avr/eeprom.h>
#include <util/crc16.h>		//cyclic redundancy check
#include <time.h>					//required for EmonShared.h
#include <EmonShared.h>

PayloadHWS hwsPayload;

#define ENABLE_SERIAL 1

RF12Init rf12Init = { HWS_JEENODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };


//--------------------------------------------------------------------------------------------
// RFM12B Setup
//--------------------------------------------------------------------------------------------

void printAddress(uint8_t deviceAddress[8])
{
	Serial.print("{ ");
	for (uint8_t i = 0; i < 8; i++)
	{
		// zero pad the address if necessary
		Serial.print("0x");
		if (deviceAddress[i] < 16) Serial.print("0");
		Serial.print(deviceAddress[i], HEX);
		if (i < 7) Serial.print(", ");

	}
	Serial.print(" }");
}


void setup()
{
	Serial.begin(9600);

	delay(500);

	Serial.println(F("Fewings Jeenode Heattrap solar HWS node for emon network"));

	// Data wire JeeNode port,	Arduino pin,		RF12 Group
	//				1				4				20
	//				2				5				21
	//				3				6				22
	//				4				7				23

	EmonSerial::PrintHWSPayload(NULL);

	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group, 1600);
	rf12_sleep(RF12_SLEEP);

	EmonSerial::PrintRF12Init(rf12Init);
}

void loop()
{
	char tok[] = ",";
	char line[256] = "";
	char* pch= NULL;
	
	//format is THx, 097, 066, 066, 062, 064, 060,PCB,042 ,PUMPS 1-4, ON  , ON  , OFF , OFF , Pump mA,2694\n\r
	if (Serial.readBytesUntil('\r', line, 256))
		;// Serial.println(line);
	pch = strtok(line, tok );

	if (strcmp(pch, "THx") == 0)
	{
		for (int i = 0; i < HWS_TEMPERATURES - 1; i++)
		{
			pch = strtok(NULL, tok);
			hwsPayload.temperature[i] = (byte)atoi(pch);
		}
		pch = strtok(NULL, tok);	//swallow the "PCB"
		pch = strtok(NULL, tok);
		hwsPayload.temperature[HWS_TEMPERATURES - 1] = (byte)atoi(pch);
		pch = strtok(NULL, tok);	//swallow the "PUMPS 1-4"
		for (int i = 0; i < HWS_PUMPS; i++)
		{
			pch = strtok(NULL, tok);
			hwsPayload.pump[i] = strcmp(pch, " OFF ");
		}

		//transmit
		rf12_sleep(RF12_WAKEUP);
		int wait = 1000;
		while (!rf12_canSend() && wait--)
			rf12_recvDone();
		if (wait)
		{
			rf12_sendStart(0, &hwsPayload, sizeof(PayloadHWS));

			rf12_sendWait(0);
		}
		rf12_sleep(RF12_SLEEP);

		EmonSerial::PrintHWSPayload(&hwsPayload);

		delay(50);	//time for the serial buffer to empty
	}
}
