#include "EmonShared.h"



void EmonSerial::PrintRF12Init(const RF12Init &rf12Init)
{
	Serial.print(F("Node: "));
	Serial.print(rf12Init.node);
	Serial.print(F(" Freq: "));
	//From RF12.h
	//#define RF12_433MHZ     1   ///< RFM12B 433 MHz frequency band.
	//#define RF12_868MHZ     2   ///< RFM12B 868 MHz frequency band.
	//#define RF12_915MHZ     3   ///< RFM12B 915 MHz frequency band.
	if (rf12Init.freq == 1) Serial.print(F("433Mhz"));
	if (rf12Init.freq == 2) Serial.print(F("868Mhz"));
	if (rf12Init.freq == 3) Serial.print(F("915Mhz"));
	Serial.print(" Network: ");
	Serial.println(rf12Init.group);
}


void EmonSerial::PrintEmonPayload(PayloadEmon* pPayloadEmon, unsigned long timeSinceLast)
{
	if (pPayloadEmon == NULL)
	{
		Serial.println(F("emon: power,pulse,ct1,supplyV,temperature,raingauge|ms_since_last_pkt"));
	}
	else
	{
		Serial.print(F("emon: "));
		Serial.print(pPayloadEmon->power);
		Serial.print(F(","));
		Serial.print(pPayloadEmon->pulse);
		Serial.print(F(","));
		Serial.print(pPayloadEmon->ct1);
		Serial.print(F(","));
		Serial.print(pPayloadEmon->supplyV);
		Serial.print(F(","));
		Serial.print(pPayloadEmon->temperature);
		Serial.print(F(","));
		Serial.print(pPayloadEmon->rainGauge);
		if (timeSinceLast != 0)
		{
			Serial.print(F("|"));
			Serial.print(timeSinceLast);
		}
		Serial.println();
	}
}


void EmonSerial::PrintRainPayload(PayloadRain* pPayloadRain, unsigned long timeSinceLast)
{
	if (pPayloadRain == NULL)
	{
		Serial.println(F("rain: rain,txCount,temperature,supplyV|ms_since_last_pkt"));
	}
	else
	{
		Serial.print(F("rain: "));
		Serial.print(pPayloadRain->rainCount);
		Serial.print(F(","));
		Serial.print(pPayloadRain->transmitCount);
		Serial.print(F(","));
		Serial.print(pPayloadRain->temperature);
		Serial.print(F(","));
		Serial.print(pPayloadRain->supplyV);
		if (timeSinceLast != 0)
		{
			Serial.print(F("|"));
			Serial.print(timeSinceLast);
		}
		Serial.println();
	}
}


void EmonSerial::PrintBasePayload(PayloadBase *pPayloadBase, unsigned long timeSinceLast)
{
	if (pPayloadBase == NULL)
	{
		Serial.print(F("base: time|ms_since_last_packet"));
	}
	else
	{
		Serial.print(F("base: "));
		Serial.print(pPayloadBase->time);
		if (timeSinceLast != 0)
		{
			Serial.print(F("|"));
			Serial.print(timeSinceLast);
		}
	}
	Serial.println();
}

int EmonSerial::ParseEmonPayload(char* str, PayloadEmon *pPayloadEmon)
{
	char* pch = strtok(str, ": ,|&");
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "emon"))
		return 0;	//can't find "emon:" as first token

	pPayloadEmon->power						= atoi(strtok(NULL, ": ,|\r\n&"));
	pPayloadEmon->pulse						= atoi(strtok(NULL, ": ,|\r\n&"));
	pPayloadEmon->ct1							= atoi(strtok(NULL, ": ,|\r\n&"));
	pPayloadEmon->supplyV					= atoi(strtok(NULL, ": ,|\r\n&"));
	pPayloadEmon->temperature			= atoi(strtok(NULL, ": ,|\r\n&"));
	pPayloadEmon->rainGauge			  = atoi(strtok(NULL, ": ,|\r\n&"));

	pch = strtok(NULL, ": ,|\r\n&");
	unsigned long timeSinceLast = atol(pch);

	return 1;
}


int EmonSerial::ParseRainPayload(char* str, PayloadRain *pPayloadRain)
{
	char* pch = strtok(str, ": ,|&");
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "rain"))
		return 0;	//can't find "base:" as first token

	pPayloadRain->rainCount = atol(strtok(NULL, ": ,|\r\n&"));
	pPayloadRain->transmitCount = atol(strtok(NULL, ": ,|\r\n&"));
	pPayloadRain->temperature = atoi(strtok(NULL, ": ,|\r\n&"));
	pPayloadRain->supplyV = atol(strtok(NULL, ": ,|\r\n&"));

	pch = strtok(NULL, ": ,|\r\n&");
	unsigned long timeSinceLast = atol(pch);

	return 1;
}


int EmonSerial::ParseBasePayload(char* str, PayloadBase *pPayloadBase)
{
	char* pch = strtok(str, ": ,|&");
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "base"))
		return 0;	//can't find "base:" as first token

	pch = strtok(NULL, ": ,|\r\n&");
	pPayloadBase->time = (time_t)atol(pch);

	pch = strtok(NULL, ": ,|\r\n&");
	unsigned long timeSinceLast = atol(pch);

	return 1;
}
