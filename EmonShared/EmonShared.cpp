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

String EmonSerial::PrintBasePayload(String &str, PayloadBase *pPayloadBase, unsigned long timeSinceLast)
{
	char buf[60];
	if (pPayloadBase == NULL)
	{
		strcpy_P(buf, PSTR("base: time|ms_since_last_packet"));
		str = buf;
	}
	else
	{
		strcpy_P(buf, PSTR("base: "));
		str = buf;
		str += pPayloadBase->time;
		if (timeSinceLast != 0)
		{
			str += "|";
			str += timeSinceLast;
		}
	}
	return str;
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

void EmonSerial::PrintDispPayload(PayloadDisp *pPayloadDisp, unsigned long timeSinceLast)
{
	if (pPayloadDisp == NULL)
	{
		Serial.print(F("disp: temperature|ms_since_last_packet"));
	}
	else
	{
		Serial.print(F("disp: "));
		Serial.print(pPayloadDisp->temperature);
		if (timeSinceLast != 0)
		{
			Serial.print(F("|"));
			Serial.print(timeSinceLast);
		}
	}
	Serial.println();
}

void EmonSerial::PrintPulsePayload(PayloadPulse* pPayloadPulse, unsigned long timeSinceLast)
{
	if (pPayloadPulse == NULL)
	{
		Serial.println(F("pulse: power1,pulse1,power2,pulse2,supplyV|ms_since_last_pkt"));
	}
	else
	{
		Serial.print(F("pulse: "));
		Serial.print(pPayloadPulse->power1);
		Serial.print(F(","));
		Serial.print(pPayloadPulse->pulse1);
		Serial.print(F(","));
		Serial.print(pPayloadPulse->power2);
		Serial.print(F(","));
		Serial.print(pPayloadPulse->pulse2);
		Serial.print(F(","));
		Serial.print(pPayloadEmon->supplyV);
		if (timeSinceLast != 0)
		{
			Serial.print(F("|"));
			Serial.print(timeSinceLast);
		}
		Serial.println();
	}
}

int EmonSerial::ParseEmonPayload(char* str, PayloadEmon *pPayloadEmon)
{
	char tok[] = ":, | \r\r&";
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "emon"))
		return 0;	//can't find "emon:" as first token

	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadEmon->power = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadEmon->pulse = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadEmon->ct1 = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadEmon->supplyV = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadEmon->temperature = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadEmon->rainGauge = atoi(pch);

	pch = strtok(NULL, tok);
	if (pch != NULL)
	{
		unsigned long timeSinceLast = atol(pch);
	}
	return 1;
}


int EmonSerial::ParseRainPayload(char* str, PayloadRain *pPayloadRain)
{
	char tok[] = ":, | \r\r&";
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "rain"))
		return 0;	//can't find "base:" as first token

	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->rainCount = atol(pch);

	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->transmitCount = atol(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->temperature = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->supplyV = atol(pch);

	if (NULL != (pch = strtok(NULL, tok)))
	{
		unsigned long timeSinceLast = atol(pch);
	}

	return 1;
}


int EmonSerial::ParseBasePayload(char* str, PayloadBase *pPayloadBase)
{
	char tok[] = ":, | \r\r&";
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "base"))
		return 0;	//can't find "base:" as first token

	pch = strtok(NULL, tok);
	if (pch == NULL)
		return 0;
	pPayloadBase->time = (time_t)atol(pch);

	pch = strtok(NULL, tok);
	if (pch != NULL)
	{
		//unsigned long timeSinceLast = atol(pch);
	}

	return 1;
}

int EmonSerial::ParseDispPayload(char* str, PayloadDisp *pPayloadDisp)
{
	char tok[] = ":, | \r\r&";
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "disp"))
		return 0;	//can't find "disp:" as first token

	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadDisp->temperature = atoi(pch);

	if (NULL != (pch = strtok(NULL, tok)))
	{
		unsigned long timeSinceLast = atol(pch);
	}

	return 1;
}
