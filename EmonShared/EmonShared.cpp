#include "EmonShared.h"
#ifdef __linux__
	#include <cstring>
	#include <cstdlib>
	#include <stddef.h>	 //offsetof()
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
		stream.print((unsigned long)pPayloadBase->time);

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
		//stream.println(F("pulse2,power[0..3],pulse[0..3],supplyV|ms_since_last_pkt"));
		stream.println(F("pulse3,subnode,power[0..5],pulse[0..5],supplyV|ms_since_last_pkt"));
	}
	else
	{
		stream.print(F("pulse3,"));
		stream.print(pPayloadPulse->subnode);
		stream.print(F(","));
			
		for(int i=0; i< PULSE_MAX_SENSORS;i++)
		{
			stream.print(pPayloadPulse->power[i]);
			stream.print(F(","));
		}
		for (int i = 0; i < PULSE_MAX_SENSORS; i++)
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
		stream.print(F("wtr3,subnode,supplyV, numSensors, flowCount[0..numSensors&0xF], waterHeight(mm)[0..numSensors&0xF0>>4]|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("wtr3,"));
		stream.print(pPayloadWater->subnode);
		stream.print(F(","));
		stream.print(pPayloadWater->supplyV);
		stream.print(F(","));
		stream.print(pPayloadWater->numSensors);
		for (int i = 0; i < (pPayloadWater->numSensors & 0xF); i++)
		{
			stream.print(F(","));
			stream.print(pPayloadWater->flowCount[i]);
		}
		for (int i = 0; i < (pPayloadWater->numSensors & 0xF0) >> 4; i++)
		{
			stream.print(F(","));
			stream.print(pPayloadWater->waterHeight[i]);
		}

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

void EmonSerial::PrintBatteryPayload(PayloadBattery* pPayloadBattery, unsigned long timeSinceLast)
{
	PrintBatteryPayload(Serial, pPayloadBattery, timeSinceLast);
}

void EmonSerial::PrintBatteryPayload(Stream& stream, PayloadBattery* pPayloadBattery, unsigned long timeSinceLast)
{
	if (pPayloadBattery == NULL)
	{
		stream.print(F("bat2,subnode,power[0..2],pulseIn[0..2],pulseOut[0..2],voltage[0..8]|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("bat2,"));
		stream.print(pPayloadBattery->subnode);
		for (int i = 0; i < BATTERY_SHUNTS; i++)
		{
			stream.print(F(","));
			stream.print(pPayloadBattery->power[i]);
		}
		for (int i = 0; i < BATTERY_SHUNTS; i++)
		{
			stream.print(F(","));
			stream.print(pPayloadBattery->pulseIn[i]);
		}
		for (int i = 0; i < BATTERY_SHUNTS; i++)
		{
			stream.print(F(","));
			stream.print(pPayloadBattery->pulseOut[i]);
		}
		for (int i = 0; i < MAX_VOLTAGES; i++)
		{
			stream.print(F(","));
			stream.print(pPayloadBattery->voltage[i]);
		}
		PrintRelay(stream, pPayloadBattery);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

void EmonSerial::PrintInverterPayload(PayloadInverter* pPayloadInverter, unsigned long timeSinceLast)
{
	PrintInverterPayload(Serial, pPayloadInverter, timeSinceLast);
}

void EmonSerial::PrintInverterPayload(Stream& stream, PayloadInverter* pPayloadInverter, unsigned long timeSinceLast)
{
	if (pPayloadInverter == NULL)
	{
		stream.print(F("inv2,subnode,activePower,apparentPower,batteryVoltage,batteryDischargeCurrent,batteryChargingCurrent,pvInputPower,batteryCapacity|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("inv2,"));
		stream.print(pPayloadInverter->subnode);
		stream.print(F(","));
		stream.print(pPayloadInverter->activePower);
		stream.print(F(","));
		stream.print(pPayloadInverter->apparentPower);
		stream.print(F(","));
		stream.print(pPayloadInverter->batteryVoltage);
		stream.print(F(","));
		stream.print(pPayloadInverter->batteryDischarge);
		stream.print(F(","));
		stream.print(pPayloadInverter->batteryCharging);
		stream.print(F(","));
		stream.print(pPayloadInverter->pvInputPower);
		stream.print(F(","));
		stream.print(pPayloadInverter->batteryCapacity);

		PrintRelay(stream, pPayloadInverter);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}


void EmonSerial::PrintBeehivePayload(PayloadBeehive* pPayloadBeehive, unsigned long timeSinceLast)
{
	PrintBeehivePayload(Serial, pPayloadBeehive, timeSinceLast);
}

void EmonSerial::PrintBeehivePayload(Stream& stream, PayloadBeehive* pPayloadBeehive, unsigned long timeSinceLast)
{
	if (pPayloadBeehive == NULL)
	{
		stream.print(F("bee,subnode,beeInRate,beeOutRate,beesIn,beesOut,tempIn,tempOut,hiveWeight,supplyV|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("bee,"));
		stream.print(pPayloadBeehive->subnode);
		stream.print(F(","));
		stream.print(pPayloadBeehive->beeInRate);
		stream.print(F(","));
		stream.print(pPayloadBeehive->beeOutRate);
		stream.print(F(","));
		stream.print(pPayloadBeehive->beesIn);
		stream.print(F(","));
		stream.print(pPayloadBeehive->beesOut);
		stream.print(F(","));
		stream.print(pPayloadBeehive->temperatureIn);
		stream.print(F(","));
		stream.print(pPayloadBeehive->temperatureOut);
		stream.print(F(","));
		stream.print(pPayloadBeehive->grams);
		stream.print(F(","));
		stream.print(pPayloadBeehive->supplyV);

		PrintRelay(stream, pPayloadBeehive);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}


void EmonSerial::PrintAirQualityPayload(PayloadAirQuality* pPayloadAirQuality, unsigned long timeSinceLast)
{
	PrintAirQualityPayload(Serial, pPayloadAirQuality, timeSinceLast);
}

void EmonSerial::PrintAirQualityPayload(Stream& stream, PayloadAirQuality* pPayloadAirQuality, unsigned long timeSinceLast)
{
	if (pPayloadAirQuality == NULL)
	{
		stream.print(F("air,subnode,particlePerDecilitre-pm0.3,pm0.5,pm1.0,pm2.5,pm5.0,pm10.0|ms_since_last_packet"));
	}
	else
	{
		stream.print(F("air,"));
		stream.print(pPayloadAirQuality->subnode);
		stream.print(F(","));
		stream.print(pPayloadAirQuality->pm0p3);
		stream.print(F(","));
		stream.print(pPayloadAirQuality->pm0p5);
		stream.print(F(","));
		stream.print(pPayloadAirQuality->pm1p0);
		stream.print(F(","));
		stream.print(pPayloadAirQuality->pm2p5);
		stream.print(F(","));
		stream.print(pPayloadAirQuality->pm5p0);
		stream.print(F(","));
		stream.print(pPayloadAirQuality->pm10p0);

		PrintRelay(stream, pPayloadAirQuality);

		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

void EmonSerial::PrintLeafPayload(PayloadLeaf* pPayloadLeaf, unsigned long timeSinceLast)
{
	PrintLeafPayload(Serial, pPayloadLeaf, timeSinceLast);
}

void EmonSerial::PrintLeafPayload(Stream& stream, PayloadLeaf* pPayloadLeaf, unsigned long timeSinceLast)
{
	if (pPayloadLeaf == NULL)
	{
		stream.print(F("leaf2,subnode,odometer,range,batteryTemperature,batterySOH,batteryWH,batteryChargeBars,chargeTimeRemaining"));
	}
	else
	{
		stream.print(F("leaf2,"));
		stream.print(pPayloadLeaf->subnode);
		stream.print(F(","));
		stream.print(pPayloadLeaf->odometer);
		stream.print(F(","));
		stream.print(pPayloadLeaf->range);
		stream.print(F(","));    
		stream.print(pPayloadLeaf->batteryTemperature);
		stream.print(F(","));
		stream.print(pPayloadLeaf->batterySOH);
		stream.print(F(","));
		stream.print(pPayloadLeaf->batteryWH);
		stream.print(F(","));
		stream.print(pPayloadLeaf->batteryChargeBars);
		stream.print(F(","));
		stream.print(pPayloadLeaf->chargeTimeRemaining);
		PrintRelay(stream, pPayloadLeaf);
		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

void EmonSerial::PrintGPSPayload(PayloadGPS* pPayloadGPS, unsigned long timeSinceLast)
{
	PrintGPSPayload(Serial, pPayloadGPS, timeSinceLast);
}

void EmonSerial::PrintGPSPayload(Stream& stream, PayloadGPS* pPayloadGPS, unsigned long timeSinceLast)
{
	if (pPayloadGPS == NULL)
	{
		stream.print(F("gps,subnode,latitude,longitude,course,speed"));
	}
	else
	{
		stream.print(F("gps,"));
		stream.print(pPayloadGPS->subnode);
		stream.print(F(","));
		stream.print(pPayloadGPS->latitude,9);
		stream.print(F(","));
		stream.print(pPayloadGPS->longitude,9);
		stream.print(F(","));    
		stream.print(pPayloadGPS->course);
		stream.print(F(","));
		stream.print(pPayloadGPS->speed);
		PrintRelay(stream, pPayloadGPS);
		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

void EmonSerial::PrintPressurePayload(PayloadPressure* pPayloadPressure, unsigned long timeSinceLast)
{
	PrintPressurePayload(Serial, pPayloadPressure, timeSinceLast);
}

void EmonSerial::PrintPressurePayload(Stream& stream, PayloadPressure* pPayloadPressure, unsigned long timeSinceLast)
{
	if (pPayloadPressure == NULL)
	{
		stream.print(F("pth,subnode,pressure,temperature,humidity"));
	}
	else
	{
		stream.print(F("pth,"));
		stream.print(pPayloadPressure->subnode);
		stream.print(F(","));
		stream.print(pPayloadPressure->pressure,2);
		stream.print(F(","));
		stream.print(pPayloadPressure->temperature,2);
		stream.print(F(","));    
		stream.print(pPayloadPressure->humidity,2);
		PrintRelay(stream, pPayloadPressure);
		if (timeSinceLast != 0)
		{
			stream.print(F("|"));
			stream.print(timeSinceLast);
		}
	}
	stream.println();
}

#endif


int EmonSerial::PackWaterPayload(PayloadWater* pPayloadWater, byte* ptr)
{
//See https://stackoverflow.com/questions/177885/looking-for-something-similar-to-offsetof-for-non-pod-types
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Winvalid-offsetof"

	//pack the two arrays of readings into the end of the structure to save on bytes transmitted. if only 1 of each sensor, this saves 3*8 +3*4 bytes = 36bytes. We will only transmit 5+8+4=17bytes. 
	byte* ptr2 = ptr;
	memcpy(ptr, pPayloadWater, sizeof(PayloadWater));
	int numFlowCount = pPayloadWater->numSensors & 0xF;
	int numHeight = (pPayloadWater->numSensors & 0xF0) >> 4;
	if( numFlowCount > MAX_WATER_SENSORS || numHeight > MAX_WATER_SENSORS)
		return 0;	//not permitted!
	ptr2 += offsetof(PayloadWater, flowCount);
	ptr2 += sizeof(unsigned long) * numFlowCount;
	for (int i = 0; i < numHeight; i++)
	{
		int height = pPayloadWater->waterHeight[i];
		memcpy(ptr2, &height, sizeof(int));
		ptr2 += sizeof(int);
	}
	//return size of packed payload
	return (int)(ptr2 - ptr);
#pragma GCC diagnostic pop
}

int EmonSerial::UnpackWaterPayload(byte* ptr, PayloadWater* pPayloadWater)
{
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Winvalid-offsetof"

	byte* ptr2 = ptr;
	memcpy(pPayloadWater, ptr, sizeof(PayloadWater));
	int numFlowCount = pPayloadWater->numSensors & 0xF;
	int numHeight = (pPayloadWater->numSensors & 0xF0) >> 4;
	if( numFlowCount > MAX_WATER_SENSORS || numHeight > MAX_WATER_SENSORS)
		return 0;
	ptr2 += offsetof(PayloadWater, flowCount);
	ptr2 += sizeof(unsigned long) * (numFlowCount);
	for (int i = 0; i < numHeight; i++)
	{
		int height;
		memcpy(&height, ptr2, sizeof(int));
		pPayloadWater->waterHeight[i] = height;
		ptr2 += sizeof(int);
	}
	//return size of packed payload
	return sizeof(PayloadWater) - sizeof(int)*(MAX_WATER_SENSORS-numHeight) - sizeof(unsigned long)*(MAX_WATER_SENSORS-numFlowCount);

#pragma GCC diagnostic pop
}



//---------------Parse routines -------------------

//returns if the string is a digit
// only check the first expected value of each pack to dicern value packet from description packet
// e.g  pulse2,877,0,1658,185,900480,7721220,11533622,4599059,3236  
// from pulse2,power[0..3],pulse[0..3],supplyV|ms_since_last_pkt
bool isDigit(char* pch)
{
	char* p;
	double converted = strtod(pch, &p);
	return !(*p); // *p should be NULL if entire string was a number
}

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

	if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
	pPayloadRain->rainCount = atol(pch);

	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->transmitCount = atol(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->temperature = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadRain->supplyV = atol(pch);

	if( pPayloadRain->rainCount > 300000 || 	// only 24000 after 6+ years of rainfall!
		pPayloadRain->temperature > 20000 || 	// temperature > 200c
		pPayloadRain->supplyV > 100000)			// supply voltage > 100v
	{
		//rain often gets very bad values. Filter them out here
		return 0;
	}


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

	if (NULL == (pch = strtok(NULL, tok))) 
		return 0;
	pPayloadBase->time = (time_t)strtoul(pch, NULL, 10);

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
		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
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
	//version 1 stored pulse as int. version2 stored as unsigned long. version3 added subnode and increased numsensor from 4 to 6
	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything
	int version;
	int numSensors = 0;
	pPayloadPulse->subnode = 0;
	if (0 == strcmp(pch, "pulse") )
	{
		version = 1;
		numSensors = 4;
		pPayloadPulse->subnode = 0;
	}
	else if(0 == strcmp(pch, "pulse2"))
	{
		version = 2;
		numSensors = 4;
		pPayloadPulse->subnode = 0;
	}
	else if(0 == strcmp(pch, "pulse3"))
	{
		version = 3;
		numSensors = PULSE_MAX_SENSORS;	//6
		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
		pPayloadPulse->subnode = atoi(pch);
	}
	else
		return 0;	//can't find "pulse" or "pulse2" as first token

	for (int i = 0; i < numSensors; i++)
	{
		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
		pPayloadPulse->power[i] = atoi(pch);
	}
	for (int i = 0; i < numSensors; i++)
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

	return version;
}

int EmonSerial::ParseTemperaturePayload(char* str, PayloadTemperature *pPayloadTemperature)
{
	memset(pPayloadTemperature, 0, sizeof(PayloadTemperature));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 == strcmp(pch, "temp"))
	{
		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
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
		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
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
		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) 
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
	int returnVal = 0;
	memset(pPayloadWater, 0, sizeof(PayloadWater));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 == strcmp(pch, "wtr"))
	{
		if (NULL == (pch = strtok(NULL, tok)))
			return 0;
		pPayloadWater->numSensors = 0x1 << 4;
		pPayloadWater->waterHeight[0] = (int)atoi(pch);

		//pPayloadWater->sensorReading = 0;
		for (int i = 0; i < 4; i++)
		{
			if (NULL == (pch = strtok(NULL, tok)))
				return 0;
			//pPayloadWater->sensorReading = pPayloadWater->sensorReading << 8 & (byte)atoi(pch);
		}
		returnVal = 1;
	}
	else if (0 == strcmp(pch, "wtr1") || 0 == strcmp(pch, "wtr2"))
	{
		if (0 == strcmp(pch, "wtr2"))
		{
			if (NULL == (pch = strtok(NULL, tok)))	return 0;
			pPayloadWater->subnode = atoi(pch);
		}
		pPayloadWater->numSensors = 0x11; //1 height and one flow meter in versions 1&2

		if (NULL == (pch = strtok(NULL, tok)))
			return 0;
		pPayloadWater->waterHeight[0] = (int)atoi(pch);

		if (NULL != (pch = strtok(NULL, tok)))
		{
			//pPayloadWater->flowRate = (int)atoi(pch);  //we no longer transmit flowrate

			if (NULL != (pch = strtok(NULL, tok)))
				pPayloadWater->flowCount[0] = (int)atoi(pch);
		}

		if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
		{
			ParseRelay(pPayloadWater, pch);
		}
		returnVal = 2;
	}
	else if (0 == strcmp(pch, "wtr3"))
	{
		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
		pPayloadWater->subnode = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok)))	return 0;
		pPayloadWater->supplyV = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok)))	return 0;
		pPayloadWater->numSensors = atoi(pch);
		for (int i = 0; i < (pPayloadWater->numSensors & 0xF); i++)
		{
			if (NULL == (pch = strtok(NULL, tok)))	return 0;
			pPayloadWater->flowCount[i] = atol(pch);
		}
		for (int i = 0; i < (pPayloadWater->numSensors & 0xF0) >> 4; i++)
		{
			if (NULL == (pch = strtok(NULL, tok)))	return 0;
			pPayloadWater->waterHeight[i] = atoi(pch);
		}
		returnVal = 3;
	}
	
	return returnVal;
}

int EmonSerial::ParseScalePayload(char* str, PayloadScale* pPayloadScale)
{
	memset(pPayloadScale, 0, sizeof(PayloadScale));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 == strcmp(pch, "scl"))
	{
		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
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

int EmonSerial::ParseBatteryPayload(char* str, PayloadBattery* pPayloadBattery)
{
	memset(pPayloadBattery, 0, sizeof(PayloadBattery));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	if (0 == strcmp(pch, "bat") || 0 == strcmp(pch, "bat2"))
	{
		int maxVoltages = 8;
		if( 0 == strcmp(pch, "bat2"))
			maxVoltages = 9; //MAX_VOLTAGES;

		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
		pPayloadBattery->subnode = atoi(pch);
		for (int i = 0; i < BATTERY_SHUNTS; i++)
		{
			if (NULL == (pch = strtok(NULL, tok))) return 0;
			pPayloadBattery->power[i] = atoi(pch);
		}
		for (int i = 0; i < BATTERY_SHUNTS; i++)
		{
			if (NULL == (pch = strtok(NULL, tok))) return 0;
			pPayloadBattery->pulseIn[i] = atol(pch);
		}
		for (int i = 0; i < BATTERY_SHUNTS; i++)
		{
			if (NULL == (pch = strtok(NULL, tok))) return 0;
			pPayloadBattery->pulseOut[i] = atol(pch);
		}
		for (int i = 0; i < maxVoltages; i++)
		{
			if (NULL == (pch = strtok(NULL, tok))) return 0;
			pPayloadBattery->voltage[i] = atoi(pch);
		}
		if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
		{
			ParseRelay(pPayloadBattery, pch);
		}

		return maxVoltages-7;	//version 1 had 8 voltages, version 2 had 9. Return 1 or 2 for version number
	}
	else
		return 0;

}


int EmonSerial::ParseInverterPayload(char* str, PayloadInverter* pPayloadInverter)
{
	memset(pPayloadInverter, 0, sizeof(PayloadInverter));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	int version = 0;
	if (0 == strcmp(pch, "inv"))
		version = 1;
	else if (0 == strcmp(pch, "inv2"))
		version = 2;
	if (version )
	{
		if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
		pPayloadInverter->subnode = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadInverter->activePower = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadInverter->apparentPower = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadInverter->batteryVoltage = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadInverter->batteryDischarge = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadInverter->batteryCharging = atoi(pch);
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadInverter->pvInputPower = atoi(pch);
		if (version == 2)
		{
			if (NULL == (pch = strtok(NULL, tok))) return 0;
			pPayloadInverter->batteryCapacity = atoi(pch);
		}

		if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
		{
			ParseRelay(pPayloadInverter, pch);
		}
	}
	else
		return 0;

	return version;
}


int EmonSerial::ParseBeehivePayload(char* str, PayloadBeehive* pPayloadBeehive)
{
	memset(pPayloadBeehive, 0, sizeof(PayloadBeehive));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	int version = 0;
	if (0 == strcmp(pch, "bee"))
		version = 1;
	if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
	pPayloadBeehive->subnode = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadBeehive->beeInRate = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadBeehive->beeOutRate = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadBeehive->beesIn = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadBeehive->beesOut = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadBeehive->temperatureIn = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadBeehive->temperatureOut = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadBeehive->grams = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadBeehive->supplyV = atoi(pch);

	if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
	{
		ParseRelay(pPayloadBeehive, pch);
	}
	return version;
}


int EmonSerial::ParseAirQualityPayload(char* str, PayloadAirQuality* pPayloadAirQuality)
{
	memset(pPayloadAirQuality, 0, sizeof(PayloadAirQuality));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	int version = 0;
	if (0 == strcmp(pch, "air"))
		version = 1;
	if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
	pPayloadAirQuality->subnode = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadAirQuality->pm0p3 = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadAirQuality->pm0p5 = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadAirQuality->pm1p0 = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadAirQuality->pm2p5 = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadAirQuality->pm5p0 = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadAirQuality->pm10p0 = atoi(pch);

	if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
	{
		ParseRelay(pPayloadAirQuality, pch);
	}
	return version;
}

int EmonSerial::ParseLeafPayload(char* str, PayloadLeaf* pPayloadLeaf)
{
	memset(pPayloadLeaf, 0, sizeof(PayloadLeaf));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	int version = 0;
	if (0 == strcmp(pch, "leaf"))
		version = 1;
	else if (0 == strcmp(pch, "leaf2"))
		version = 2;

	if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
	pPayloadLeaf->subnode = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadLeaf->odometer = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadLeaf->range = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadLeaf->batteryTemperature = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadLeaf->batterySOH = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadLeaf->batteryWH = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadLeaf->batteryChargeBars = atoi(pch);
	if(version >= 2)
	{
		if (NULL == (pch = strtok(NULL, tok))) return 0;
		pPayloadLeaf->chargeTimeRemaining = atoi(pch);
	}
	if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
	{
		ParseRelay(pPayloadLeaf, pch);
	}
	return version;
}


int EmonSerial::ParseGPSPayload(char* str, PayloadGPS* pPayloadGPS)
{
	memset(pPayloadGPS, 0, sizeof(PayloadGPS));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	int version = 0;
	if (0 == strcmp(pch, "gps"))
		version = 1;

	if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
	pPayloadGPS->subnode = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadGPS->latitude = (float) atof(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadGPS->longitude = atof(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadGPS->course = atof(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadGPS->speed = atof(pch);
	if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
	{
		ParseRelay(pPayloadGPS, pch);
	}
	return version;
}


int EmonSerial::ParsePressurePayload(char* str, PayloadPressure* pPayloadPressure)
{
	memset(pPayloadPressure, 0, sizeof(PayloadPressure));

	char* pch = strtok(str, tok);
	if (pch == NULL)
		return 0;	//can't find anything

	int version = 0;
	if (0 == strcmp(pch, "pth"))
		version = 1;

	if (NULL == (pch = strtok(NULL, tok)) || !isDigit(pch) ) return 0;
	pPayloadPressure->subnode = atoi(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadPressure->pressure = (float) atof(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadPressure->temperature = atof(pch);
	if (NULL == (pch = strtok(NULL, tok))) return 0;
	pPayloadPressure->humidity = atof(pch);
	if (NULL != (pch = strtok(NULL, tok)) && strlen(pch) == 8) //8 differentiates timeSinceLast from relay
	{
		ParseRelay(pPayloadPressure, pch);
	}
	return version;
}
