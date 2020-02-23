//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------

#define RF69_COMPAT 1

#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <EEPROM.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>

#include <Adafruit_ADS1015.h>
#include <Time.h>

#define EEPROM_BASE 0x10	//where the wH readings are stored in EEPROM

RF12Init g_rf12Init = { BATTERY_NODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP, RF69_COMPAT };

const double FACTOR[6] = { 0.1875, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125 };
const int GAIN_VALUE[6] = { GAIN_TWOTHIRDS, GAIN_ONE, GAIN_TWO, GAIN_FOUR, GAIN_EIGHT, GAIN_SIXTEEN };
const int32_t SAMPLES = 30;
const uint8_t LED_PIN = 9;
const unsigned long SEND_PERIOD = 15000;  //ms

Adafruit_ADS1115 ads1115[4] { Adafruit_ADS1115(0x48), Adafruit_ADS1115(0x49), Adafruit_ADS1115(0x4A), Adafruit_ADS1115(0x4B) };

volatile unsigned long	g_RGlastTick = 0;
double g_mWH_In[BATTERY_SHUNTS] = { 0.0, 0.0, 0.0 };
double g_mWH_Out[BATTERY_SHUNTS] = { 0.0, 0.0, 0.0 };
unsigned long  g_lastMillis;
PayloadBattery g_payloadBattery;
unsigned long g_lastSendTime;

double readEEPROM(int offset)
{
	double value = 0;
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(double); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_BASE + offset * sizeof(double) + l);
	}

	return value;
}

void writeEEPROM(int offset, double value)
{
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(double); l++)
	{
		EEPROM.write(EEPROM_BASE + offset * sizeof(double) + l, *(pc + l));
	}
}


long readVcc()
{
	long result;
	// Read 1.1V reference against AVcc
	ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
	delay(2); // Wait for Vref to settle
	ADCSRA |= _BV(ADSC); // Convert
	while (bit_is_set(ADCSRA, ADSC));
	result = ADCL;
	result |= ADCH << 8;
	result = 1126400L / result; // Back-calculate AVcc in mV
	return result;
}

int16_t median(int16_t* samples, int nSamples)
{
	for (int i = 1; i < nSamples; ++i)
	{
		int16_t j = samples[i];
		int16_t k;
		for (k = i - 1; (k >= 0) && (j < samples[k]); k--)
		{
			samples[k + 1] = samples[k];
		}
		samples[k + 1] = j;
	}

	return samples[nSamples / 2];
}


int16_t Reading(uint8_t ads, uint8_t channel)
{
	ads1115[ads].setGain(GAIN_TWOTHIRDS); //shouldn't be required!
	int32_t s = 0;
	for (int i = 0; i < SAMPLES; i++)
	{
		int16_t r = ads1115[ads].readADC_SingleEnded(channel);
		s += r;
//		Serial.print(i); Serial.print(":"); Serial.print(r);Serial.print(",");
	}
//	Serial.println();
//	Serial.print(ads); Serial.print(":"); Serial.print(channel); Serial.print(","); Serial.println( (int16_t)(s/SAMPLES));
	return (int16_t) (s / SAMPLES);
}

double ReadingDifferential(uint8_t ads, uint8_t channel)
{
	double sum = 0;
	int gain;
	int16_t samples[SAMPLES];

	for (int g = 0; g < 6; g++ )
	{
		ads1115[ads].setGain((adsGain_t)GAIN_VALUE[g]);
		int16_t reading;
		if( channel == 0)
			reading = ads1115[ads].readADC_Differential_0_1();
		else
			reading = ads1115[ads].readADC_Differential_2_3();

		gain = g;
		//Serial.print("AIN2: v shunt       "); Serial.print(g); Serial.print(","); Serial.print(adc2); Serial.print(","); Serial.println(adc2 * factor[g], 5);
		if (abs(reading) > 1000)
			break;
	}

	for (int i = 0; i < SAMPLES; i++)
	{
		int16_t reading;
		if (channel == 0)
			samples[i] = ads1115[ads].readADC_Differential_0_1();
		else
			samples[i] = ads1115[ads].readADC_Differential_2_3();
		sum += samples[i];
	}
	
	//reset to default
	ads1115[ads].setGain(GAIN_TWOTHIRDS);


	double _median = median(samples, SAMPLES)*FACTOR[gain];
	double mean = sum/SAMPLES*FACTOR[gain];
	double sumOfSquares = 0.0;
	double stdDev;

	for(int i=0; i< SAMPLES;i++)
	{
		sumOfSquares += (samples[i]*FACTOR[gain] - mean) * (samples[i]*FACTOR[gain] - mean);
	}
	stdDev = sqrt( sumOfSquares/SAMPLES);

	Serial.print("gain="); Serial.print(gain); Serial.print(" factor="); Serial.print(FACTOR[gain]);
	Serial.print(" median=");Serial.print(_median, 5);
	Serial.print(" mean=");Serial.print(mean, 5);
	Serial.print(" stdDev=");Serial.println(stdDev, 5);
	//mean seems to be the best measure. StdDev on the 30 samples is quite high! 
	//typical for 3 banks
	//gain=5 factor=0.01 median=-5.36719 mean=-5.22786 stdDev=0.48221
	//gain=5 factor=0.01 median=-3.88281 mean=-3.51432 stdDev=1.09815
	//gain=5 factor=0.01 median=-0.06250 mean=0.00781 stdDev=0.27687
	return mean;  
}

void setup()
{
	digitalWrite(LED_PIN, HIGH);

	Serial.begin(9600);

	Serial.println(F("Battery monitor sensor start"));


	//initialise the EEPROMSettings for relay and node number
	EEPROMSettings  eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	g_payloadBattery.subnode = eepromSettings.subnode;

	Serial.println("rf12_initialize");
	rf12_initialize(g_rf12Init.node, g_rf12Init.freq, g_rf12Init.group);
	EmonSerial::PrintRF12Init(g_rf12Init);
	EmonSerial::PrintBatteryPayload(NULL);

	for(int ads=0; ads<4;ads++)
		ads1115[ads].begin();

	//reset the counters
	for (int i = 0; i < BATTERY_SHUNTS; i++)
	{
		g_mWH_In[i] = 0.0; 
		writeEEPROM(i, 0.0);
		g_mWH_Out[i] = 0.0;
		writeEEPROM(i + BATTERY_SHUNTS, 0.0);
	}

	//Get double g_mWH_In and g_mWH_Out from eeprom
	for (int i = 0; i < BATTERY_SHUNTS; i++)
	{
		g_mWH_In[i] = readEEPROM(i);
		g_mWH_Out[i] = readEEPROM(i + BATTERY_SHUNTS);
	}

	g_lastMillis = millis();
	g_lastSendTime = millis();

	delay(1000);
	digitalWrite(LED_PIN, LOW);
}


void loop()
{
	//main rail voltage, should be around 52v. Voltage divider is 10k/500 ohms
	double railVoltage = ((short)(Reading(0, 2) * 0.1875 * (10000 + 500) / 500 / 10 ));

	g_payloadBattery.voltage[0] = (short) railVoltage;
	//battery bank 1, mid point voltage, should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[1] = (short)(Reading(0, 3) * 0.1875 * (10000 + 1000) / 1000 / 10);
	//battery bank 2, mid point voltage, series 1 (top row), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[2] = (short)(Reading(3, 0) * 0.1875 * (10000 + 1000) / 1000 / 10);
	//battery bank 2, mid point voltage, series 2 (second down), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[3] = (short)(Reading(2, 3) * 0.1875 * (10000 + 1000) / 1000 / 10);
	//battery bank 2, mid point voltage, series 3 (third down), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[4] = (short)(Reading(2, 2) * 0.1875 * (10000 + 1000) / 1000 / 10);
	//battery bank 2, mid point voltage, series 4 (forth down), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[5] = (short)(Reading(2, 1) * 0.1875 * (10000 + 1000) / 1000 / 10);
	//battery bank 2, mid point voltage, series 5 (bottom row), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[6] = (short)(Reading(2, 0) * 0.1875 * (10000 + 1000) / 1000 / 10);
	g_payloadBattery.voltage[7] = (short) readVcc();

	unsigned long now = millis();
	unsigned long period = now - g_lastMillis;
	g_lastMillis = now;

	double amps[BATTERY_SHUNTS];
	amps[0] = ReadingDifferential(1, 0) * 150.0 / 50.0; //shunt is 150Amps for 90mV;
	amps[1] = ReadingDifferential(0, 0) * 90.0 / 100.0; //shunt is 90Amps for 100mV;
	amps[2] = ReadingDifferential(1, 1) * 50.0 / 75.0; //shunt is 50Amps for 75mV;

	for (uint8_t i = 0; i < BATTERY_SHUNTS; i++)
	{
		g_payloadBattery.power[i] = railVoltage * amps[i] / 100.0;  //convert mV to mW

		if(g_payloadBattery.power[i] < 0)
			g_mWH_Out[i] += -1.0 * g_payloadBattery.power[i] * period / (60 * 60 * 1000.0); //convert to wH
		else
			g_mWH_In[i] += g_payloadBattery.power[i] * period / (60 * 60 * 1000.0);
		//this will do the rounding to units of pulses
		g_payloadBattery.pulseIn[i] = g_mWH_In[i];
		g_payloadBattery.pulseOut[i] = g_mWH_Out[i];
		Serial.print("shunt "); Serial.print(i); Serial.print(",");
		Serial.print(railVoltage, 2); Serial.print(",");
		Serial.print(amps[i]); Serial.print(",");
		Serial.print(g_payloadBattery.power[i]); Serial.print(",");
		Serial.print(g_mWH_Out[i]); Serial.print(",");
		Serial.print(g_mWH_In[i]); Serial.print(",");
		Serial.print(g_payloadBattery.pulseIn[i]); Serial.print(",");
		Serial.print(g_payloadBattery.pulseOut[i]); Serial.println();
	}
	
	EmonSerial::PrintBatteryPayload(&g_payloadBattery);

	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	if(millis() - g_lastSendTime > SEND_PERIOD)
	{
		g_lastSendTime = millis();
		digitalWrite(LED_PIN, HIGH);


		rf12_sleep(RF12_WAKEUP);
		int wait = 1000;
		while (!rf12_canSend() && wait--)
			rf12_recvDone();
		if (wait)
		{
			rf12_sendStart(0, &g_payloadBattery, sizeof g_payloadBattery);
			rf12_sendWait(0);
			Serial.print(F("Sending:"));
			EmonSerial::PrintBatteryPayload(&g_payloadBattery);
		}
		else
		{
			Serial.println(F("RF12 waiting. No packet sent"));
		}
		rf12_sleep(RF12_SLEEP);

		//write g_mWH_In and g_mWH_Out to eeprom
		for (int i = 0; i < BATTERY_SHUNTS; i++)
		{
			writeEEPROM(i, g_mWH_In[i]);
			writeEEPROM(i, g_mWH_Out[i]);
		}

		digitalWrite(LED_PIN, LOW);
	}
	delay(1000);
}