#include "EmonShared.h"

char tok[] = ":, | \r\r&";  //tokens used to separate 


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
	PrintEmonPayload(Serial, pPayloadEmon, timeSinceLast);
}

void EmonSerial::PrintEmonPayload(Stream& stream, PayloadEmon* pPayloadEmon, unsigned long timeSinceLast)
{
	if (pPayloadEmon == NULL)
	{
		stream.println(F("emon: power,pulse,ct1,supplyV,temperature,raingauge|ms_since_last_pkt"));
	}
	else
	{
		stream.print(F("emon: "));
		stream.print(pPayloadEmon->power);
		stream.print(F(","));
		stream.print(pPayloadEmon->pulse);
		stream.print(F(","));
		stream.print(pPayloadEmon->ct1);
		stream.print(F(","));
		stream.print(pPayloadEmon->supplyV);
		stream.print(F(","));
		stream.print(pPayloadEmon->temperature);
		stream.print(F(","));
		stream.print(pPayloadEmon->rainGauge);
		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
		stream.println();
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
		stream.println(F("rain: rain,txCount,temperature,supplyV|ms_since_last_pkt"));
	}
	else
	{
		stream.print(F("rain: "));
		stream.print(pPayloadRain->rainCount);
		stream.print(F(","));
		stream.print(pPayloadRain->transmitCount);
		stream.print(F(","));
		stream.print(pPayloadRain->temperature);
		stream.print(F(","));
		stream.print(pPayloadRain->supplyV);
		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
		stream.println();
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
	PrintBasePayload(Serial, pPayloadBase, timeSinceLast);
}

void EmonSerial::PrintBasePayload(Stream& stream, PayloadBase *pPayloadBase, unsigned long timeSinceLast)
{
	if (pPayloadBase == NULL)
	{
		stream.print(F("base: time|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("base: "));
		stream.print(pPayloadBase->time);
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
		stream.print(F("disp: temperature|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("disp: "));
		stream.print(pPayloadDisp->temperature);
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
		stream.println(F("pulse: power[0..3],pulse[0..3],supplyV|ms_since_last_pkt"));
	}
	else
	{
		stream.print(F("pulse: "));
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
		stream.print(F("temp: numSensors,temperature[0..numSensors],supplyV|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("temp: "));
		stream.print(pPayloadTemperature->numSensors);
		int nSensors = (pPayloadTemperature->numSensors < MAX_TEMPERATURE_SENSORS ? pPayloadTemperature->numSensors : MAX_TEMPERATURE_SENSORS);
		for (int i = 0; i < nSensors; i++)
		{
			stream.print(F(","));
			stream.print(pPayloadTemperature->temperature[i]);
		}
		//the battery power is in the last element of the array!
		stream.print(F(","));
		stream.print(pPayloadTemperature->temperature[pPayloadTemperature->numSensors]);

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
		stream.print(F("hws: temperature[0..7],pump[0..2]|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("hws: "));
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
		stream.print(F("wtr: waterHeight(mm), rawReading(header,mm<<8,mm,chksum)|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("wtr: "));

		stream.print(pPayloadWater->waterHeight);

		for (int i = 3; i >= 0; i--)
		{
			stream.print(F(","));
			stream.print((pPayloadWater->sensorReading >> (8 * i)) & 0xFF);
		}

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}


//---------------Parse routines -------------------


int EmonSerial::ParseEmonPayload(char* str, PayloadEmon *pPayloadEmon)
{
	//char tok[] = ":, | \r\r&";
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
	//char tok[] = ":, | \r\r&";
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

	if (NULL != (pch = strtok(NULL, tok)))
	{
		unsigned long timeSinceLast = atol(pch);
	}

	return 1;
}


int EmonSerial::ParseBasePayload(char* str, PayloadBase *pPayloadBase)
{
	//char tok[] = ":, | \r\r&";
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
	//char tok[] = ":, | \r\r&";
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


int EmonSerial::ParsePulsePayload(char* str, PayloadPulse *pPayloadPulse)
{
	//char tok[] = ":, | \r\r&";
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "pulse"))
		return 0;	//can't find "pulse:" as first token
	
	for (int i = 0; i < PULSE_NUM_PINS; i++)
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadPulse->power[i] = atoi(pch);
	}
	for (int i = 0; i < PULSE_NUM_PINS; i++)
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadPulse->pulse[i] = atoi(pch);
	}

	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadPulse->supplyV = atol(pch);


	if (NULL != (pch = strtok(NULL, tok)))
	{
		unsigned long timeSinceLast = atol(pch);
	}

	return 1;
}

int EmonSerial::ParseTemperaturePayload(char* str, PayloadTemperature *pPayloadTemperature)
{
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "temp"))
		return 0;	//can't find "disp:" as first token

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
	if (NULL != (pch = strtok(NULL, tok)))
	{
		unsigned long timeSinceLast = atol(pch);
	}

	return 1;
}

int EmonSerial::ParseHWSPayload(char* str, PayloadHWS *pPayloadHWS)
{
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "hws"))
		return 0;	//can't find "disp:" as first token

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

	return 1;
}

int EmonSerial::ParseWaterPayload(char* str, PayloadWater* pPayloadWater)
{
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 != strcmp(pch, "wtr"))
		return 0;	//can't find "wtr:" as first token
	pPayloadWater->waterHeight = (int)atoi(pch);

	pPayloadWater->sensorReading = 0;
	for (int i = 0; i < 4; i++)
	{
		if (NULL == (pch = strtok(NULL, tok)))
			return 0;
		pPayloadWater->sensorReading = pPayloadWater->sensorReading << 8 & (byte)atoi(pch);
	}
	
	return 1;
}
