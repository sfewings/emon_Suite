//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_ADS1115_current_voltage_monitor.ino
//-------------------------------------------------------------------------------------------------------------------------------------------------


#include <SPI.h>
#include <RH_RF69.h>
// Singleton instance of the radio driver
RH_RF69 g_rf69;

#include <avr/wdt.h>    //watchdog timer

#include <EEPROM.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>

#include <Adafruit_ADS1015.h>
#include <Time.h>
#include <PinChangeInterrupt.h>
//#include <PinChangeInt.h>

#define EEPROM_BASE 0x10	//where the wH readings are stored in EEPROM
#define CALIBRATION_BUTTON_PIN A3
const double FACTOR[6] = { 0.1875, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125 };
const int GAIN_VALUE[6] = { GAIN_TWOTHIRDS, GAIN_ONE, GAIN_TWO, GAIN_FOUR, GAIN_EIGHT, GAIN_SIXTEEN };
const int32_t SAMPLES = 30;
const uint8_t LED_PIN = 9;
const unsigned long SEND_PERIOD = 2000;//10000;  //ms

Adafruit_ADS1115 ads1115[4] { Adafruit_ADS1115(0x48), Adafruit_ADS1115(0x49), Adafruit_ADS1115(0x4A), Adafruit_ADS1115(0x4B) };

volatile unsigned long	g_RGlastTick = 0;
volatile bool g_buttonPressed = false;

double g_mvOffset[BATTERY_SHUNTS*2] = { 0.0, 0.0, 0.0, 0.0, 0.0, 0.0 };	//offset of the shunt with no current flowing.
double g_mWH_In[BATTERY_SHUNTS*2] = { 0.0, 0.0, 0.0, 0.0, 0.0, 0.0 };
double g_mWH_Out[BATTERY_SHUNTS*2] = { 0.0, 0.0, 0.0, 0.0, 0.0, 0.0 };
unsigned long  g_lastMillis;
PayloadBattery g_payloadBattery;

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

// Push button interrupt routine
void interruptHandlerPushButton()
{
	unsigned long tick = millis();
	unsigned long period;
	if (tick < g_RGlastTick)
		period = tick + (g_RGlastTick - 0xFFFFFFFF);	//rollover occured
	else
		period = tick - g_RGlastTick;
	g_RGlastTick = tick;

	if (period > 200)	//more than 50 ms to avoid switch bounce
	{
		g_buttonPressed = true;
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
	const int SKIP_READINGS = 5;		//skip the first and last of the sorted sampels as these appear to be noisy!
	stats_t stats;
	double sum = 0;
	double sumOfSquares = 0;
	double samplesCopy[SAMPLES];

	for(int i=0;i<nSamples;i++)
    	samplesCopy[i] = samples[i];

	//sort the samples
	for (int i = 0; i < nSamples-1; i++) 
	{ 
		bool swapped = false; 
		for (int j = 0; j < nSamples-i-1; j++) 
		{ 
			if (samplesCopy[j] > samplesCopy[j+1]) 
			{ 
				double temp = samplesCopy[j];
				samplesCopy[j]=samplesCopy[j+1];
				samplesCopy[j+1] = temp;
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
		sum += samplesCopy[i];
	}

	stats.mean = sum/(nSamples-2*SKIP_READINGS);
	stats.median = samplesCopy[nSamples/2];

	for(int i=SKIP_READINGS; i< nSamples-SKIP_READINGS;i++)
	{
		sumOfSquares += (samplesCopy[i] - stats.mean) * (samplesCopy[i] - stats.mean);
	}
	stats.stdDev = sqrt( sumOfSquares/(nSamples-2*SKIP_READINGS));

	return stats;
}

double Reading(uint8_t readingNum, uint8_t ads, uint8_t channel, double scaleFactor, bool &noisyData )
{
	ads1115[ads].setGain(GAIN_TWOTHIRDS); //shouldn't be required!
	double samples[SAMPLES];

	if( ads1115[ads].readADC_SingleEnded(channel) == 0xffff)
	{
		//0xffff is no ADS115 connected or not voltage reading. Return 0 instead
		Serial.print(F("reading,"));
		Serial.print( readingNum);
		Serial.println(F(",no ADS115 connected or not voltage reading. Return 0 instead"));
		return 0.0;
	}

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

	if(stats.stdDev > 30.0) //30 = 0.3v
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

double ReadingDifferential(const char* shuntName, uint8_t ads, uint8_t channel, double offset, bool &noisyData)
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

	ads1115[ads].setGain((adsGain_t)GAIN_VALUE[gain]);

	for (int i = 0; i < SAMPLES; i++)
	{
		if (channel == 0)
			samples[i] = ads1115[ads].readADC_Differential_0_1()*FACTOR[gain] - offset;
		else
			samples[i] = ads1115[ads].readADC_Differential_2_3()*FACTOR[gain] - offset;
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
	Serial.print(shuntName);	Serial.print(F(",")); 
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

	if(stats.stdDev > 30.0)
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


void SendPacket(PayloadBattery &payloadBattery)
{
		//Send packet 
	digitalWrite(LED_PIN, HIGH);

	payloadBattery.crc = EmonSerial::CalcCrc((const void*) &g_payloadBattery, sizeof(PayloadBattery)-2);

	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
	g_rf69.send((const uint8_t*) &payloadBattery, sizeof(PayloadBattery));
	if( g_rf69.waitPacketSent() )
	{
		EmonSerial::PrintBatteryPayload(&payloadBattery);
	}
	else
	{
		Serial.println(F("No packet sent"));
	}
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
	
	digitalWrite(LED_PIN, LOW);
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
	g_payloadBattery.subnode = 4; //eepromSettings.subnode;


	if (!g_rf69.init())
		Serial.println(F("rf69 init failed"));
	if (!g_rf69.setFrequency(915.0))
		Serial.println(F("rf69 setFrequency failed"));
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(BATTERY_NODE);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	Serial.print(F("RF69 initialise node: "));
	Serial.print(BATTERY_NODE);
	Serial.println(F(" Freq: 915MHz"));


	EmonSerial::PrintBatteryPayload(NULL);

	Serial.println(F("reading,readingNum,median,mean,stdDev"));
	Serial.println(F("current,shuntNum,gain,factor,median,mean,stdDev"));
	Serial.println(F("shunt,#,railv,amps,power,totalOut,totalIn,pulseOut,pulseIn"));

	for(int ads=0; ads<4;ads++)
		ads1115[ads].begin();

	//reset the counters
	// for (int i = 0; i < BATTERY_SHUNTS*2; i++)
	// {
	// 	g_mWH_In[i] = 0.0; 
	//  	writeEEPROM(i, 0.0);
	//  	g_mWH_Out[i] = 0.0;
	//  	writeEEPROM(i + BATTERY_SHUNTS*2, 0.0);
	// 	g_mvOffset[i] = 0.0;
	//  	writeEEPROM(i + BATTERY_SHUNTS*2*2, 0.0);
	// }

	//Get double g_mWH_In and g_mWH_Out from eeprom
	for (int i = 0; i < BATTERY_SHUNTS*2; i++)
	{
		g_mWH_In[i] = readEEPROM(i);
		g_mWH_Out[i] = readEEPROM(i + BATTERY_SHUNTS*2);
		g_mvOffset[i] = readEEPROM(i + BATTERY_SHUNTS*2*2);
	}

	Serial.print(F("pulseIn[]"));
	for (int i = 0; i < BATTERY_SHUNTS*2; i++)
	{
		Serial.print(F(","));Serial.print(g_mWH_In[i]); 
	}
	Serial.println();
	Serial.print(F("pulseOut[]"));
	for (int i = 0; i < BATTERY_SHUNTS*2; i++)
	{
		Serial.print(F(","));Serial.print(g_mWH_Out[i]); 
	}
	Serial.println();
	Serial.print(F("offset[]"));
	for (int i = 0; i < BATTERY_SHUNTS*2; i++)
	{
		Serial.print(F(","));Serial.print(g_mvOffset[i]); 
	}
	Serial.println();

	g_lastMillis = millis();

	//reset payload contents 
	for (int i = 0; i < BATTERY_SHUNTS*2; i++)
	{
		g_payloadBattery.power[i] = 0;
		g_payloadBattery.pulseIn[i] = 0;
		g_payloadBattery.pulseOut[i] = 0;
	}
	for (int i = 0; i < MAX_VOLTAGES; i++)
	{
		g_payloadBattery.voltage[i] = 0;
	}

	//pushbutton configuration
	pinMode(CALIBRATION_BUTTON_PIN, INPUT);
	//attachPinChangeInterrupt(A3, interruptHandlerPushButton, RISING);
  	attachPCINT(digitalPinToPCINT(CALIBRATION_BUTTON_PIN),interruptHandlerPushButton, RISING);

  	Serial.println(F("Watchdog timer set for 8 seconds"));
  	wdt_enable(WDTO_8S);
  
	delay(1000);
	digitalWrite(LED_PIN, LOW);
}


void loop()
{
	bool noisyData = false;

	wdt_reset();
	if(g_buttonPressed)
	{
		digitalWrite(LED_PIN, HIGH);
		g_mvOffset[0] = ReadingDifferential("0x49", 1, 0, 0, noisyData );
		wdt_reset();
		g_mvOffset[1] = ReadingDifferential("0x49", 1, 1, 0, noisyData );
		wdt_reset();
		g_mvOffset[2] = ReadingDifferential("0x4A", 2, 0, 0, noisyData );
		wdt_reset();
		g_mvOffset[3] = ReadingDifferential("0x4A", 2, 1, 0, noisyData );
		wdt_reset();
		g_mvOffset[4] = ReadingDifferential("0x4B", 3, 0, 0, noisyData );
		wdt_reset();
		g_mvOffset[5] = ReadingDifferential("0x4B", 3, 1, 0, noisyData );
		wdt_reset();
		Serial.print(F("Resetting current offsets."));
		for (int i = 0; i < BATTERY_SHUNTS*2; i++)
		{
			Serial.print(F(","));Serial.print(g_mvOffset[i]); 
			writeEEPROM(i+BATTERY_SHUNTS*2*2, g_mvOffset[i]);
		}
		Serial.println();
		digitalWrite(LED_PIN, LOW);
		g_buttonPressed = false;
	}

	uint32_t millisStart = millis();

	//main rail voltage, should be around 52v. Voltage divider is 10k/510 ohms. railVoltage is in 100ths of volts, not mV
	//double railVoltage = Reading(0, 0, 0, 0.1875 * (10000 + 510) / 510 / 10, noisyData );
	double railVoltage = ReadingDifferential("Rail", 0, 0, 0.0, noisyData ) * (2000000.0 +81000.0)/81000.0;
	// if (railVoltage == 0.0 || noisyData)
	// {
	// 	railVoltage = 5000.0;
	// 	noisyData = false;
	// }

	g_payloadBattery.voltage[0] = (short) railVoltage;



	railVoltage = 5000.0;



   	wdt_reset();
  
	double amps[BATTERY_SHUNTS*2];
	amps[0] = ReadingDifferential("0x49", 1, 0, g_mvOffset[0], noisyData )*500.0/75.0; // * 150.0 / 50.0;// * 0.197; //shunt is 150Amps for 50mV. 0.197 is the circuit scale factor!
  	wdt_reset();
	amps[1] = ReadingDifferential("0x49", 1, 1, g_mvOffset[1], noisyData )*500.0/75.0; // * 90.0 / 150.0;// * 0.197; //shunt is 90Amps for 150mV;
  	wdt_reset();
	amps[2] = ReadingDifferential("0x4A", 2, 0, g_mvOffset[2], noisyData )*500.0/75.0; // * 90.0 / 150.0;// * 0.197; //shunt is 90Amps for 150mV;
  	wdt_reset();
	amps[3] = ReadingDifferential("0x4A", 2, 1, g_mvOffset[3], noisyData )*500.0/75.0; // * 90.0 / 150.0;// * 0.197; //shunt is 90Amps for 150mV;
  	wdt_reset();
	amps[4] = ReadingDifferential("0x4B", 3, 0, g_mvOffset[4], noisyData )*500.0/75.0; // * 90.0 / 150.0;// * 0.197; //shunt is 90Amps for 150mV;
  	wdt_reset();
	amps[5] = ReadingDifferential("0x4B", 3, 1, g_mvOffset[5], noisyData )*500.0/75.0; // * 90.0 / 150.0;// * 0.197; //shunt is 90Amps for 150mV;
  	wdt_reset();

	for(int i=0;i<BATTERY_SHUNTS*2;i++)
	{
		amps[i] = amps[i]/ 5.0;	//the circuit scalling factor is 5;
	}

	// amps[1] = ReadingDifferential("Diff"  , 0, 0, noisyData ) * 90.0 / 100.0; //shunt is 90Amps for 100mV; Bank 1
  	// wdt_reset();
	// amps[2] = ReadingDifferential("LiFePo1", 1, 1, noisyData ) * 150.0 / 50.0; //shunt is 50Amps for 75mV;  Li ion
 	// wdt_reset();

	if( noisyData ) // || railVoltage > 10000)
	{
		digitalWrite(LED_PIN, HIGH);
		Serial.println("High std dev on a reading. Noisy data. Exiting without sending.");
		while( millis()- millisStart < SEND_PERIOD )
		{
			delay( 100 );
			wdt_reset();
		}
		digitalWrite(LED_PIN,LOW);	//LED will stay on for a few seconds when no data sent
		return;
	}

	unsigned long now = millis();
	unsigned long period = now - g_lastMillis;
	g_lastMillis = now;

	g_payloadBattery.subnode = 4;
	//Serial.println(F("shunt,#,railv,amps,power,totalOut,totalIn,pulseOut,pulseIn"));
	for (uint8_t i = 0; i < BATTERY_SHUNTS; i++)
	{
		g_payloadBattery.power[i] = railVoltage * amps[i] / 100.0;  //convert mV to mW
		//g_payloadBattery.power[i] = amps[i]*10.0;  //convert mV to 10ths of mv

		if(g_payloadBattery.power[i] < 0)
			g_mWH_Out[i] += -1.0 * g_payloadBattery.power[i] * period / (60 * 60 * 1000.0); //convert to wH
		else
			g_mWH_In[i] += 1.0* g_payloadBattery.power[i] * period / (60 * 60 * 1000.0);
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
	SendPacket(g_payloadBattery);

	g_payloadBattery.subnode = 5;

	for (uint8_t i = 0; i < BATTERY_SHUNTS; i++)
	{
		g_payloadBattery.power[i] = railVoltage * amps[i+BATTERY_SHUNTS] / 100.0;  //convert mV to mW
		//g_payloadBattery.power[i] = amps[i+BATTERY_SHUNTS]*10.0;  //convert mV to 10ths of mv

		if(g_payloadBattery.power[i] < 0)
			g_mWH_Out[i+BATTERY_SHUNTS] += -1.0 * g_payloadBattery.power[i] * period / (60 * 60 * 1000.0); //convert to wH
		else
			g_mWH_In[i+BATTERY_SHUNTS] += 1.0* g_payloadBattery.power[i] * period / (60 * 60 * 1000.0);
		//this will do the rounding to units of pulses
		g_payloadBattery.pulseIn[i] = g_mWH_In[i+BATTERY_SHUNTS];
		g_payloadBattery.pulseOut[i] = g_mWH_Out[i+BATTERY_SHUNTS];

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
	SendPacket(g_payloadBattery);
	
	//write g_mWH_In and g_mWH_Out to eeprom
	for (int i = 0; i < BATTERY_SHUNTS*2; i++)
	{
		writeEEPROM(i, g_mWH_In[i]);
		writeEEPROM(i+ BATTERY_SHUNTS*2, g_mWH_Out[i]);
	}
	

	Serial.print( F("loop_ms,") );
	Serial.println( millis()- millisStart );
	while( millis()- millisStart < SEND_PERIOD )
	{
		delay( 100 );
	  	wdt_reset();
	}
}
