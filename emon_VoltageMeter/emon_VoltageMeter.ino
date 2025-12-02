//------------------------------------------------------------------------------------------------------------------------------------------------
// emon BatteryMonitor
// Built November 2023
// Get the voltages on 4 12v batteries in series
// No Current measurement version
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
#include <ctype.h>
//#include <PinChangeInterrupt.h>

#define EEPROM_BASE 0x10	//where the wH readings are stored in EEPROM


const double FACTOR[6] = { 0.1875, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125 };
const int GAIN_VALUE[6] = { GAIN_TWOTHIRDS, GAIN_ONE, GAIN_TWO, GAIN_FOUR, GAIN_EIGHT, GAIN_SIXTEEN };
const int32_t SAMPLES = 30;
const uint8_t LED_PIN = 9;
const unsigned long SEND_PERIOD = 10000;  //ms
//const uint8_t CALIBRATION_BUTTON_PIN = A3;

Adafruit_ADS1115 ads1115[4] { Adafruit_ADS1115(0x48), Adafruit_ADS1115(0x49), Adafruit_ADS1115(0x4A), Adafruit_ADS1115(0x4B) };

//volatile bool g_buttonPressed = false;
//volatile unsigned long	g_RGlastTick = 0;
unsigned long  g_lastMillis;
PayloadBattery g_payloadBattery;
const uint8_t VOLTAGE_INPUTS = 4;
double g_channelScaleFactor[VOLTAGE_INPUTS] = { 0.0, 0.0, 0.0, 0.0 };	//offset of the 4 voltage readings.

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
// void interruptHandlerPushButton()
// {
// 	unsigned long tick = millis();
// 	unsigned long period;
// 	if (tick < g_RGlastTick)
// 		period = tick + (g_RGlastTick - 0xFFFFFFFF);	//rollover occured
// 	else
// 		period = tick - g_RGlastTick;
// 	g_RGlastTick = tick;

// 	if (period > 200)	//more than 50 ms to avoid switch bounce
// 	{
// 		g_buttonPressed = true;
// 	}
// }

void flashErrorToLED(int error, bool haltExecution = false)
{
  do
  { 
    for( int i = 0; i < error; i++)
    {
      digitalWrite(LED_PIN, HIGH);
      delay(100);
      digitalWrite(LED_PIN, LOW);
      delay(100);
    }
	delay(1000);
  }
  while( haltExecution );
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
	const int SKIP_READINGS = 10;		//skip the first and last of the sorted sampels as these appear to be noisy!
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

	for (int i = 0; i < SAMPLES; i++)
	{
		samples[i] = ads1115[ads].readADC_SingleEnded(channel)*scaleFactor; 
	}
	stats_t stats = GetStats(samples, SAMPLES);

	Serial.print(F("reading,"));
	Serial.print( readingNum);		Serial.print(F(","));
	Serial.print( stats.median,0 );	Serial.print(F(",")); 
	Serial.print( stats.mean,0 );	Serial.print(F(",")); 
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

double ReadingDifferential(const char* shuntName, uint8_t ads, uint8_t channel, bool &noisyData)
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

	if(stats.stdDev > 4.0) //4.0
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

// Read a double from Serial non-blocking.
// Returns true and writes value to 'out' when a full line with a valid number is received.
// Returns false if no complete line is available or the line is not a valid number.
bool readDoubleFromSerial(double &out)
{
    static char buf[32];
    static uint8_t pos = 0;

    while (Serial.available()) {
        char c = (char)Serial.read();
		Serial.print(c); //echo back to serial monitor
        if (c == '\r' || c == '\n' || c == ' ') {
            if (pos == 0) continue; // ignore empty lines / stray line endings
            buf[pos] = '\0';
            char *endptr = nullptr;
            double v = strtod(buf, &endptr);
            // no conversion performed
            if (endptr == buf) {
                pos = 0;
				Serial.println(F("Invalid number format"));
                return false;
            }
            // ensure remaining chars (if any) are whitespace
            while (*endptr && isspace((unsigned char)*endptr)) endptr++;
            if (*endptr != '\0') {
                pos = 0;
				Serial.println(F("Non-numeric characters in input"));
                return false;
            }
            out = v;
            pos = 0;
            return true;
        } else {
            if (pos < sizeof(buf) - 1) buf[pos++] = c;
            // if buffer overflows, keep discarding extra chars until newline
        }
    }
    // no complete line available
    return false;
}

void setup()
{
	pinMode(LED_PIN, OUTPUT);
	digitalWrite(LED_PIN, HIGH);

	Serial.begin(9600);

	Serial.println(F("Battery monitor sensor start"));


	//initialise the EEPROMSettings for relay and node number
	// EEPROMSettings  eepromSettings;
	// EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	// EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	g_payloadBattery.subnode = 6;

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
	Serial.println(F("To calibrate. Connect all inputs to single voltage source and enter voltage in volts via serial monitor followed by a space or newline"));
	EmonSerial::PrintBatteryPayload(NULL);

	Serial.println(F("reading,readingNum,median,mean,stdDev"));

	for(int ads=0; ads<4;ads++)
		ads1115[ads].begin();

	g_lastMillis = millis();

	//reset caliration EEPROM values
	for( int i = 0; i < VOLTAGE_INPUTS; i++)
	{
		g_channelScaleFactor[i] = 1.0;
	 	//writeEEPROM(i, 1.0);
	}

	//Get double g_mWH_In and g_mWH_Out from eeprom
	for (int i = 0; i < VOLTAGE_INPUTS; i++)
	{
		g_channelScaleFactor[i] = readEEPROM(i);
		Serial.print(F("Channel "));
		Serial.print(i);
		Serial.print(F(" scale factor: "));
		Serial.println(g_channelScaleFactor[i], 6);
	}

	//pushbutton configuration
	// pinMode(CALIBRATION_BUTTON_PIN, INPUT);
  	// attachPCINT(digitalPinToPCINT(CALIBRATION_BUTTON_PIN),interruptHandlerPushButton, RISING);

  
  	Serial.println(F("Watchdog timer set for 8 seconds"));
  	wdt_enable(WDTO_8S);
  
	delay(1000);
	digitalWrite(LED_PIN, LOW);
}


void loop()
{
	wdt_reset();

	bool noisyData = false;

	double userEnteredInputvoltage = 0.0;
	if( readDoubleFromSerial(userEnteredInputvoltage) )
	{
		digitalWrite(LED_PIN, HIGH);
		Serial.print(F("User entered voltage: "));
		Serial.println( userEnteredInputvoltage,3 );
		Serial.println(F("Channel, Previous scale factor, New scale factor"));
		for(int i=0; i<VOLTAGE_INPUTS; i++)
		{
			double newScaleFactor = Reading(i, 0, i, 0.1875 * (10000 + 510) / 510 / 10, noisyData )/userEnteredInputvoltage/100.0;
			if( noisyData )
			{
				Serial.println("Noisy data detected during calibration. Aborting calibration.");
				break;
			}
			Serial.print(i);
			Serial.print(F(","));
			Serial.print(g_channelScaleFactor[i], 6);
			g_channelScaleFactor[i] = newScaleFactor;
			Serial.print(F(","));
			Serial.println(g_channelScaleFactor[i], 6);
			writeEEPROM(i, g_channelScaleFactor[i]);
			wdt_reset();
		}
		digitalWrite(LED_PIN, LOW);
	}


	uint32_t millisStart = millis();
	
	// Voltage divider is 10k/510 ohms
	g_payloadBattery.voltage[0] = (short) Reading(0, 0, 0, 0.1875 * (10000 + 510) / 510 / 10/g_channelScaleFactor[0], noisyData );
	g_payloadBattery.voltage[1] = (short) Reading(1, 0, 1, 0.1875 * (10000 + 510) / 510 / 10/g_channelScaleFactor[1], noisyData );
	g_payloadBattery.voltage[2] = (short) Reading(2, 0, 2, 0.1875 * (10000 + 510) / 510 / 10/g_channelScaleFactor[2], noisyData );
	g_payloadBattery.voltage[3] = (short) Reading(3, 0, 3, 0.1875 * (10000 + 510) / 510 / 10/g_channelScaleFactor[3], noisyData );
  	wdt_reset();
  
	if( noisyData || g_payloadBattery.voltage[0] > 10000)
	{
		Serial.println("High std dev on a reading. Noisy data. Exiting without sending.");
		uint32_t millisTaken = millis()- millisStart; 
    	wdt_reset();
		flashErrorToLED(5, false); //flash 5 times for noisy data
		while( millisTaken < SEND_PERIOD )
		{
			delay(100);
			millisTaken = millis()- millisStart; 
			wdt_reset();
		}
		return;
	}

	unsigned long now = millis();
	unsigned long period = now - g_lastMillis;
	g_lastMillis = now;


	//Send packet 
	digitalWrite(LED_PIN, HIGH);


	g_payloadBattery.crc = EmonSerial::CalcCrc((const void*) &g_payloadBattery, sizeof(PayloadBattery)-2);

	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
	
	g_rf69.send((const uint8_t*) &g_payloadBattery, sizeof(g_payloadBattery));
	if( g_rf69.waitPacketSent() )
	{
		EmonSerial::PrintBatteryPayload(&g_payloadBattery);
	}
	else
	{
		Serial.println(F("No packet sent"));
	}
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
	
	digitalWrite(LED_PIN, LOW);

	uint32_t millisTaken = millis()- millisStart; 
	Serial.print( F("loop_ms,") );
	Serial.println( millisTaken );
  	wdt_reset();
	while( millisTaken < SEND_PERIOD )
	{
		delay(100);
		millisTaken = millis()- millisStart; 
		wdt_reset();
	}
}
