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
const unsigned long SEND_PERIOD = 5000;  //ms

Adafruit_ADS1115 ads1115[4] { Adafruit_ADS1115(0x48), Adafruit_ADS1115(0x49), Adafruit_ADS1115(0x4A), Adafruit_ADS1115(0x4B) };

volatile unsigned long	g_RGlastTick = 0;
double g_mWH_In[BATTERY_SHUNTS] = { 0.0, 0.0, 0.0 };
double g_mWH_Out[BATTERY_SHUNTS] = { 0.0, 0.0, 0.0 };
unsigned long  g_lastMillis;
PayloadBattery g_payloadBattery;
//unsigned long g_lastSendTime;

typedef struct {
	double mean;
	double median;
	double stdDev;
} stats_t;

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

stats_t GetStats(double* samples, int nSamples)
{
	const int SKIP_READINGS = 3;		//skip the first and last of the sorted sampels as these appear to be noisy!
	stats_t stats;
	double sum = 0;
	double sumOfSquares = 0;

	//sort the samples
	for (int i = 0; i < nSamples-1; i++) 
	{ 
		bool swapped = false; 
		for (int j = 0; j < nSamples-i-1; j++) 
		{ 
			if (samples[j] > samples[j+1]) 
			{ 
				double temp = samples[j];
				samples[j]=samples[j+1];
				samples[j+1] = temp;
				swapped = true; 
			} 
		} 

		// IF no two elements were swapped by inner loop, then break 
		if (swapped == false) 
			break; 
	} 

	//skip the top and bottom readings as there is quite a bit of noise
	for (int i = SKIP_READINGS; i < nSamples-SKIP_READINGS; ++i)
	{
		sum += samples[i];
	}

	stats.mean = sum/(nSamples-2*SKIP_READINGS);
	stats.median = samples[nSamples/2];

	for(int i=SKIP_READINGS; i< nSamples-SKIP_READINGS;i++)
	{
		sumOfSquares += (samples[i] - stats.mean) * (samples[i] - stats.mean);
	}
	stats.stdDev = sqrt( sumOfSquares/(nSamples-2*SKIP_READINGS));

	return stats;
}

double Reading(uint8_t readingNum, uint8_t ads, uint8_t channel, double scaleFactor, bool &noisyData )
{
	ads1115[ads].setGain(GAIN_TWOTHIRDS); //shouldn't be required!
	double samples[SAMPLES];

	for (int i = 0; i < SAMPLES; i++)
	{
		samples[i] = ads1115[ads].readADC_SingleEnded(channel)*scaleFactor; 
	}
	stats_t stats = GetStats(samples, SAMPLES);

	Serial.print(F("reading,"));
	Serial.print( readingNum);		Serial.print(F(","));
	Serial.print( stats.median,0 );	Serial.print(F(",")); 
	Serial.print( stats.mean,0 );		Serial.print(F(",")); 
	Serial.print( stats.stdDev );
	Serial.println();

	if(stats.stdDev > 7.0) 
	{
		noisyData = true;

		Serial.print(F("voltage vals,"));
		for (int i = 0; i < SAMPLES; i++)
		{
			Serial.print(samples[i]);
			Serial.print(",");
		}
		Serial.println();
	}

	return stats.median;  //median removes chance of spike reading influencing the tallies
}

double ReadingDifferential(uint8_t shuntNum, uint8_t ads, uint8_t channel, bool &noisyData)
{
	int gain;
	double samples[SAMPLES];

	for (int g = 0; g < 6; g++ )
	{
		ads1115[ads].setGain((adsGain_t)GAIN_VALUE[g]);

		for (int i = 0; i < SAMPLES; i++)
		{
			if( channel == 0)
				samples[i] = ads1115[ads].readADC_Differential_0_1();
			else
				samples[i] = ads1115[ads].readADC_Differential_2_3();
		}

		gain = g;

		//appears to be some noisy values resulting in selecting a low gain value.
		//use mean to try and filter out the noise at this stage.
		stats_t stats = GetStats(samples, SAMPLES);
		if (abs(stats.mean) > 1000)
			break;
	}

	for (int i = 0; i < SAMPLES; i++)
	{
		if (channel == 0)
			samples[i] = ads1115[ads].readADC_Differential_0_1()*FACTOR[gain];
		else
			samples[i] = ads1115[ads].readADC_Differential_2_3()*FACTOR[gain];
	}
	
	//reset to default
	ads1115[ads].setGain(GAIN_TWOTHIRDS);

	//print before sorting!
	// Serial.print(F("current vals,"));
	// for (int i = 0; i < SAMPLES; i++)
	// {
	// 	Serial.print(samples[i]);
	// 	Serial.print(",");
	// }
	// Serial.println();


	stats_t stats = GetStats(samples, SAMPLES);

	//Serial.println(F("current,shuntNum,gain,factor,median,mean,stdDev"));
	Serial.print(F("current,"));
	Serial.print(shuntNum);	Serial.print(F(",")); 
	Serial.print(gain);		Serial.print(F(",")); 
	Serial.print(stats.median);	Serial.print(F(",")); 
	Serial.print(stats.mean);		Serial.print(F(",")); 
	Serial.print(stats.stdDev);
	Serial.println();

	//mean seems to be the best measure. StdDev on the 30 samples is quite high! 
	//typical for 3 banks
	//gain=5 factor=0.01 median=-5.36719 mean=-5.22786 stdDev=0.48221
	//gain=5 factor=0.01 median=-3.88281 mean=-3.51432 stdDev=1.09815
	//gain=5 factor=0.01 median=-0.06250 mean=0.00781 stdDev=0.27687

	if(stats.stdDev > 3.0) 
	{
		noisyData = true;
		Serial.print(F("current vals,"));
		for (int i = 0; i < SAMPLES; i++)
		{
			Serial.print(samples[i]);
			Serial.print(",");
		}
		Serial.println();
	}

	return stats.mean;
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

	Serial.println(F("reading,readingNum,median,mean,stdDev"));
	Serial.println(F("current,shuntNum,gain,factor,median,mean,stdDev"));
	Serial.println(F("shunt,#,railv,amps,power,totalOut,totalIn,pulseOut,pulseIn"));

	for(int ads=0; ads<4;ads++)
		ads1115[ads].begin();

	//reset the counters
	// for (int i = 0; i < BATTERY_SHUNTS; i++)
	// {
	// 	g_mWH_In[i] = 0.0; 
	// 	writeEEPROM(i, 0.0);
	// 	g_mWH_Out[i] = 0.0;
	// 	writeEEPROM(i + BATTERY_SHUNTS, 0.0);
	// }

	//Get double g_mWH_In and g_mWH_Out from eeprom
	for (int i = 0; i < BATTERY_SHUNTS; i++)
	{
		g_mWH_In[i] = readEEPROM(i);
		g_mWH_Out[i] = readEEPROM(i + BATTERY_SHUNTS);
	}

	g_lastMillis = millis();
	//g_lastSendTime = millis();

	delay(1000);
	digitalWrite(LED_PIN, LOW);
}


void loop()
{
	uint32_t millisStart = millis();
	
	bool noisyData = false;

	//main rail voltage, should be around 52v. Voltage divider is 10k/500 ohms
	double railVoltage = Reading(0, 0, 2, 0.1875 * (10000 + 500) / 500 / 10, noisyData );

	g_payloadBattery.voltage[0] = (short) railVoltage;
	//battery bank 1, mid point voltage, should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[1] = (short) Reading(1, 0, 3, 0.1875 * (10000 + 1000) / 1000 / 10, noisyData );
	//battery bank 2, mid point voltage, series 1 (top row), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[2] = (short) Reading(2, 3, 0, 0.1875 * (10000 + 1000) / 1000 / 10, noisyData );
	//battery bank 2, mid point voltage, series 2 (second down), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[3] = (short) Reading(3, 2, 3, 0.1875 * (10000 + 1000) / 1000 / 10, noisyData );
	//battery bank 2, mid point voltage, series 3 (third down), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[4] = (short) Reading(4, 2, 2, 0.1875 * (10000 + 1000) / 1000 / 10, noisyData );
	//battery bank 2, mid point voltage, series 4 (forth down), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[5] = (short) Reading(5, 2, 1, 0.1875 * (10000 + 1000) / 1000 / 10, noisyData );
	//battery bank 2, mid point voltage, series 5 (bottom row), should be around 24v. Voltage divider is 10k/1k ohms
	g_payloadBattery.voltage[6] = (short) Reading(6, 2, 0, 0.1875 * (10000 + 1000) / 1000 / 10, noisyData );
	g_payloadBattery.voltage[7] = (short) readVcc();

	double amps[BATTERY_SHUNTS];
	amps[0] = ReadingDifferential(0, 1, 0, noisyData ) * 150.0 / 50.0; //shunt is 150Amps for 90mV;
	amps[1] = ReadingDifferential(1, 0, 0, noisyData ) * 90.0 / 100.0; //shunt is 90Amps for 100mV;
	amps[2] = ReadingDifferential(2, 1, 1, noisyData ) * 50.0 / 75.0; //shunt is 50Amps for 75mV;

	if( noisyData)
	{
		digitalWrite(LED_PIN, HIGH);
		Serial.println("High std dev on a reading. Noisy data. Exiting without sending.");
		uint32_t millisTaken = millis()- millisStart; 
		if( millisTaken < SEND_PERIOD )
			delay( SEND_PERIOD - millisTaken);
		digitalWrite(LED_PIN,LOW);	//LED will stay on for a few seconds when no data sent
		return;
	}

	unsigned long now = millis();
	unsigned long period = now - g_lastMillis;
	g_lastMillis = now;

	//Serial.println(F("shunt,#,railv,amps,power,totalOut,totalIn,pulseOut,pulseIn"));
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

		// Serial.print("shunt,"); 
		// Serial.print(i); 							Serial.print(",");
		// Serial.print(railVoltage, 2); 				Serial.print(",");
		// Serial.print(amps[i]); 						Serial.print(",");
		// Serial.print(g_payloadBattery.power[i]); 	Serial.print(",");
		// Serial.print(g_mWH_Out[i]); 				Serial.print(",");
		// Serial.print(g_mWH_In[i]); 					Serial.print(",");
		// Serial.print(g_payloadBattery.pulseOut[i]); Serial.print(",");
		// Serial.print(g_payloadBattery.pulseIn[i]); 
		// Serial.println();
	}

	//write g_mWH_In and g_mWH_Out to eeprom
	for (int i = 0; i < BATTERY_SHUNTS; i++)
	{
		writeEEPROM(i, g_mWH_In[i]);
		writeEEPROM(i+ BATTERY_SHUNTS, g_mWH_Out[i]);
	}
	
	//Send packet 
	EmonSerial::PrintBatteryPayload(&g_payloadBattery);

	digitalWrite(LED_PIN, HIGH);

	rf12_sleep(RF12_WAKEUP);
	int wait = 1000;
	while (!rf12_canSend() && wait--)
		rf12_recvDone();
	if (wait)
	{
		rf12_sendStart(0, &g_payloadBattery, sizeof g_payloadBattery);
		rf12_sendWait(0);
		Serial.println(F("Sent"));
	}
	else
	{
		Serial.println(F("RF12 waiting. No packet sent"));
	}
	rf12_sleep(RF12_SLEEP);

	digitalWrite(LED_PIN, LOW);

	uint32_t millisTaken = millis()- millisStart; 
	Serial.print( F("loop_ms,") );
	Serial.println( millisTaken );
	if( millisTaken < SEND_PERIOD )
		delay( SEND_PERIOD - millisTaken);
}