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
		Serial.println(F("rain: rain,txCount,supplyV|ms_since_last_pkt"));
	}
	else
	{
		Serial.print(F("rain: "));
		Serial.print(pPayloadRain->rainCount);
		Serial.print(F(","));
		Serial.print(pPayloadRain->transmitCount);
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
