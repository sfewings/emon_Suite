#include "EmonShared.h"
#ifdef __linux__
	#include <cstring>
	#include <cstdlib>
#endif

char tok[] = ":, | \r\r&";  //tokens used to separate 
#ifndef MQTT_LIB

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
	Serial.print(F(" Network: "));
	Serial.print(rf12Init.group);
	if(rf12Init.rf69compat )
		Serial.println(F(" Component: RF69CW"));
	else
		Serial.println(F(" Component: RF12B"));
}


void EmonSerial::PrintRelay(Stream& stream, PayloadRelay* pPayloadRelay)
{
	if (pPayloadRelay->relay != 0)
	{
		stream.print(F("|"));
		for (int i = 7; i >= 0; i--)
			stream.print((pPayloadRelay->relay >> i & 0x1) ? "1" : "0");
	}
}

void EmonSerial::PrintRainPayload(PayloadRain* pPayloadRain, unsigned long timeSinceLast)
{
	PrintRainPayload(Serial, pPayloadRain, timeSinceLast);
}

void EmonSerial::PrintRainPayload(Stream& stream, PayloadRain* pPayloadRain, unsigned long timeSinceLast)
{
	if (pPayloadRain == NULL)
	{
		stream.println(F("rain,rain,txCount,temperature,supplyV|ms_since_last_pkt"));
	}
	else
	{
		stream.print(F("rain,"));
		stream.print(pPayloadRain->rainCount);
		stream.print(F(","));
		stream.print(pPayloadRain->transmitCount);
		stream.print(F(","));
		stream.print(pPayloadRain->temperature);
		stream.print(F(","));
		stream.print(pPayloadRain->supplyV);

		PrintRelay(stream, pPayloadRain);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
		stream.println();
	}
}

void EmonSerial::PrintBasePayload(PayloadBase *pPayloadBase, unsigned long timeSinceLast)
{
	PrintBasePayload(Serial, pPayloadBase, timeSinceLast);
}

void EmonSerial::PrintBasePayload(Stream& stream, PayloadBase *pPayloadBase, unsigned long timeSinceLast)
{
	if (pPayloadBase == NULL)
	{
		stream.print(F("base,time|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("base,"));
		stream.print(pPayloadBase->time);

		PrintRelay(stream, pPayloadBase);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

void EmonSerial::PrintDispPayload(PayloadDisp *pPayloadDisp, unsigned long timeSinceLast)
{
	PrintDispPayload(Serial, pPayloadDisp, timeSinceLast);
}

void EmonSerial::PrintDispPayload(Stream& stream, PayloadDisp *pPayloadDisp, unsigned long timeSinceLast)
{
	if (pPayloadDisp == NULL)
	{
		stream.print(F("disp1,subnode,temperature|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("disp1,"));
		stream.print(pPayloadDisp->subnode);
		stream.print(F(","));
		stream.print(pPayloadDisp->temperature);

		PrintRelay(stream, pPayloadDisp);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

void EmonSerial::PrintPulsePayload(PayloadPulse* pPayloadPulse, unsigned long timeSinceLast)
{
	PrintPulsePayload(Serial, pPayloadPulse, timeSinceLast);
}

void EmonSerial::PrintPulsePayload(Stream& stream, PayloadPulse* pPayloadPulse, unsigned long timeSinceLast)
{
	if (pPayloadPulse == NULL)
	{
		stream.println(F("pulse2,power[0..3],pulse[0..3],supplyV|ms_since_last_pkt"));
	}
	else
	{
		stream.print(F("pulse2,"));
		for(int i=0; i< PULSE_NUM_PINS;i++)
		{
			stream.print(pPayloadPulse->power[i]);
			stream.print(F(","));
		}
		for (int i = 0; i < PULSE_NUM_PINS; i++)
		{
			stream.print(pPayloadPulse->pulse[i]);
			stream.print(F(","));
		}
		stream.print(pPayloadPulse->supplyV);

		PrintRelay(stream, pPayloadPulse);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
		stream.println();
	}
}

void EmonSerial::PrintTemperaturePayload(PayloadTemperature *pPayloadTemperature, unsigned long timeSinceLast)
{
	PrintTemperaturePayload(Serial, pPayloadTemperature, timeSinceLast);
}

void EmonSerial::PrintTemperaturePayload(Stream& stream, PayloadTemperature *pPayloadTemperature, unsigned long timeSinceLast)
{
	if (pPayloadTemperature == NULL)
	{
		stream.print(F("temp1,subnode,supplyV,numSensors,temperature[0..numSensors]|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("temp1,"));
		stream.print(pPayloadTemperature->subnode);
		stream.print(F(","));
		stream.print(pPayloadTemperature->supplyV);
		stream.print(F(","));
		stream.print(pPayloadTemperature->numSensors);
		int nSensors = (pPayloadTemperature->numSensors < MAX_TEMPERATURE_SENSORS ? pPayloadTemperature->numSensors : MAX_TEMPERATURE_SENSORS);
		for (int i = 0; i < nSensors; i++)
		{
			stream.print(F(","));
			stream.print(pPayloadTemperature->temperature[i]);
		}
		
		PrintRelay(stream, pPayloadTemperature);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

void EmonSerial::PrintHWSPayload(PayloadHWS *pPayloadHWS, unsigned long timeSinceLast)
{
	PrintHWSPayload(Serial, pPayloadHWS, timeSinceLast);
}

void EmonSerial::PrintHWSPayload(Stream& stream, PayloadHWS *pPayloadHWS, unsigned long timeSinceLast)
{
	if (pPayloadHWS == NULL)
	{
		stream.print(F("hws,temperature[0..7],pump[0..2]|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("hws,"));
		for (int i = 0; i < HWS_TEMPERATURES; i++)
		{
			stream.print(pPayloadHWS->temperature[i]);
			stream.print(F(","));
		}
		for (int i = 0; i < HWS_PUMPS; i++)
		{
			stream.print(pPayloadHWS->pump[i]);
			if( i< HWS_PUMPS-1 ) 
				stream.print(F(","));
		}

		PrintRelay(stream, pPayloadHWS);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

void EmonSerial::PrintWaterPayload(PayloadWater* pPayloadWater, unsigned long timeSinceLast)
{
	PrintWaterPayload(Serial, pPayloadWater, timeSinceLast);
}

void EmonSerial::PrintWaterPayload(Stream& stream, PayloadWater* pPayloadWater, unsigned long timeSinceLast)
{
	if (pPayloadWater == NULL)
	{
		stream.print(F("wtr2,subnode,waterHeight(mm),flowRate,flowCount|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("wtr2,"));
		stream.print(pPayloadWater->subnode);
		stream.print(F(","));
		stream.print(pPayloadWater->waterHeight);
		stream.print(F(","));
		stream.print(pPayloadWater->flowRate);
		stream.print(F(","));
		stream.print(pPayloadWater->flowCount);

		PrintRelay(stream, pPayloadWater);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

void EmonSerial::PrintScalePayload(PayloadScale* pPayloadScale, unsigned long timeSinceLast)
{
	PrintScalePayload(Serial, pPayloadScale, timeSinceLast);
}

void EmonSerial::PrintScalePayload(Stream& stream, PayloadScale* pPayloadScale, unsigned long timeSinceLast)
{
	if (pPayloadScale == NULL)
	{
		stream.print(F("scl,subnode,grams,supplyV|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("scl,"));
		stream.print(pPayloadScale->subnode);
		stream.print(F(","));
		stream.print(pPayloadScale->grams);
		stream.print(F(","));
		stream.print(pPayloadScale->supplyV);

		PrintRelay(stream, pPayloadScale);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}
#endif
//---------------Parse routines -------------------

void EmonSerial::ParseRelay(PayloadRelay* pPayloadRelay, char* pch)
{
	//convert a binary value to a number e.g. 00100101 => 37
	size_t len = strlen(pch);
	byte relay = 0;
	for (size_t i = 0; i < len; i++)
		relay = (relay << 1) + (pch[i] != '0');
	pPayloadRelay->relay = relay;
}

int EmonSerial::ParseRainPayload(char* str, PayloadRain *pPayloadRain)
{
	memset(pPayloadRain, 0, sizeof(PayloadRain));
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "rain"))
		return 0;	//can't find "rain:" as first token

	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->rainCount = atol(pch);

	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->transmitCount = atol(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->temperature = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->supplyV = atol(pch);

	if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
	{
		ParseRelay(pPayloadRain, pch);
		//unsigned long timeSinceLast = atol(pch);
	}

	return 1;
}


int EmonSerial::ParseBasePayload(char* str, PayloadBase *pPayloadBase)
{
	memset(pPayloadBase, 0, sizeof(PayloadBase));

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
	if (pch != NULL && strlen(pch) == 8) //8 differentiates timeSinceLast from relay)
	{
		ParseRelay(pPayloadBase, pch);
	}

	return 1;
}

int EmonSerial::ParseDispPayload(char* str, PayloadDisp* pPayloadDisp)
{
	memset(pPayloadDisp, 0, sizeof(PayloadDisp));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 == strcmp(pch, "disp"))	//version 1
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadDisp->temperature = atoi(pch);
	}
	else if (0 == strcmp(pch,"disp1")) //version 2
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadDisp->subnode = atoi(pch);	//the last char is the subnode number
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadDisp->temperature = atoi(pch);
		if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
		{
			ParseRelay(pPayloadDisp, pch);
				//unsigned long timeSinceLast = atol(pch);
		}
	}
	else
		return 0;	//can't find "disp" or "disp1" as first token

	return 1;
}


int EmonSerial::ParsePulsePayload(char* str, PayloadPulse *pPayloadPulse)
{
	memset(pPayloadPulse, 0, sizeof(PayloadPulse));
	//version 1 stored pulse as int. version2 sotred as unsigned long
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything
	int version;
	if (0 == strcmp(pch, "pulse") )
		version = 1;
	else if(0 == strcmp(pch, "pulse2"))
		version = 2;
	else
		return 0;	//can't find "pulse" or "pulse2" as first token
	
	for (int i = 0; i < PULSE_NUM_PINS; i++)
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadPulse->power[i] = atoi(pch);
	}
	for (int i = 0; i < PULSE_NUM_PINS; i++)
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadPulse->pulse[i] = atol(pch);
	}

	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadPulse->supplyV = atol(pch);


	if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8 ) //8 differentiates timeSinceLast from relay
	{
		ParseRelay(pPayloadPulse, pch);
		//unsigned long timeSinceLast = atol(pch);
	}

	return 1;
}

int EmonSerial::ParseTemperaturePayload(char* str, PayloadTemperature *pPayloadTemperature)
{
	memset(pPayloadTemperature, 0, sizeof(PayloadTemperature));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 == strcmp(pch, "temp"))
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadTemperature->numSensors = atoi(pch);
		if (pPayloadTemperature->numSensors > MAX_TEMPERATURE_SENSORS)
			return 0;  //don't support more than ten sensors!
		if (pPayloadTemperature->numSensors == 2)
			pPayloadTemperature->subnode = 1; // garage temperature prob
		else if (pPayloadTemperature->numSensors == 4)
			pPayloadTemperature->subnode = 0;	// room sensors
		else
			pPayloadTemperature->subnode = 2; //unknown
		for (int i = 0; i < pPayloadTemperature->numSensors; i++)
		{
			if (NULL == (pch = strtok(NULL, tok)))
				return 0;
			pPayloadTemperature->temperature[i] = atoi(pch);
		}
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadTemperature->supplyV = atoi(pch);	// the last reading+1 is the supplyV
	}
	else if (0 == strcmp(pch, "temp1"))	//version 2
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadTemperature->subnode = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadTemperature->supplyV = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadTemperature->numSensors = atoi(pch);
		if (pPayloadTemperature->numSensors > MAX_TEMPERATURE_SENSORS)
			return 0;  //don't support more than ten sensors!

		for (int i = 0; i < pPayloadTemperature->numSensors; i++)
		{
			if (NULL == (pch = strtok(NULL, tok)))
				return 0;
			pPayloadTemperature->temperature[i] = atoi(pch);
		}

		if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
		{
			ParseRelay(pPayloadTemperature, pch);
		}
	}
	else
		return 0;	//can't find "temp" as first token


	return 1;
}

int EmonSerial::ParseHWSPayload(char* str, PayloadHWS *pPayloadHWS)
{
	memset(pPayloadHWS, 0, sizeof(PayloadHWS));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "hws"))
		return 0;	//can't find "hws:" as first token

	for (int i = 0; i < HWS_TEMPERATURES; i++)
	{
		if (NULL == (pch = strtok(NULL, tok))) 
			return 0;
		pPayloadHWS->temperature[i] = (byte) atoi(pch);
	}
	for (int i = 0; i < HWS_PUMPS; i++)
	{
		if (NULL == (pch = strtok(NULL, tok)))
			return 0;
		pPayloadHWS->pump[i] = (0!=atoi(pch));
	}
	
	if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
	{
		ParseRelay(pPayloadHWS, pch);
	}

	return 1;
}

int EmonSerial::ParseWaterPayload(char* str, PayloadWater* pPayloadWater)
{
	memset(pPayloadWater, 0, sizeof(PayloadWater));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 == strcmp(pch, "wtr"))
	{
		if (NULL == (pch = strtok(NULL, tok)))
			return 0;
		pPayloadWater->waterHeight = (int)atoi(pch);

		//pPayloadWater->sensorReading = 0;
		for (int i = 0; i < 4; i++)
		{
			if (NULL == (pch = strtok(NULL, tok)))
				return 0;
			//pPayloadWater->sensorReading = pPayloadWater->sensorReading << 8 & (byte)atoi(pch);
		}
	}
	else if (0 == strcmp(pch, "wtr1") || 0 == strcmp(pch, "wtr2"))
	{
		if (0 == strcmp(pch, "wtr2"))
		{
			if (NULL == (pch = strtok(NULL, tok)))	return 0;
			pPayloadWater->subnode = atoi(pch);
		}
		if (NULL == (pch = strtok(NULL, tok)))
			return 0;
		pPayloadWater->waterHeight = (int)atoi(pch);

		if (NULL != (pch = strtok(NULL, tok)))
		{
			pPayloadWater->flowRate = (int)atoi(pch);

			if (NULL != (pch = strtok(NULL, tok)))
				pPayloadWater->flowCount = (int)atoi(pch);
		}

		if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
		{
			ParseRelay(pPayloadWater, pch);
		}
	}
	else
		return 0; //couldn't find wtr, wtr1 or wtr2
	
	return 1;
}

int EmonSerial::ParseScalePayload(char* str, PayloadScale* pPayloadScale)
{
	memset(pPayloadScale, 0, sizeof(PayloadScale));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 == strcmp(pch, "scl"))
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadScale->subnode = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadScale->grams = atol(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadScale->supplyV = atol(pch);

		if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
		{
			ParseRelay(pPayloadScale, pch);
		}
	}
	else 
		return 0;

	return 1;
}

