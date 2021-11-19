//------------------------------------------------------------------------------------------------------------------------------------------------
// emon Currenet Reverse checker
// Uses the two difference voltage elements of the ADS1115 ADC to check for currrent accuracy in two directions
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <SPI.h>
#include <RH_RF69.h>
// Singleton instance of the radio driver
RH_RF69 g_rf69;

#include <EEPROM.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>

#include <Adafruit_ADS1015.h>
#include <Time.h>
#include <Wire.h>

const double FACTOR[6] = { 0.1875, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125 };
const int GAIN_VALUE[6] = { GAIN_TWOTHIRDS, GAIN_ONE, GAIN_TWO, GAIN_FOUR, GAIN_EIGHT, GAIN_SIXTEEN };
const int32_t SAMPLES = 30;
const uint8_t LED_PIN = 9;
const uint8_t SUB_NODE = 2;
const unsigned long SEND_PERIOD = 15000;  //ms
#define VOLTAGE_MEASURE_PIN 		A0

Adafruit_ADS1115 ads1115;

volatile unsigned long	g_RGlastTick = 0;
unsigned long  g_lastMillis;
PayloadBattery  g_payloadBattery;

double g_mWH_In;
double g_mWH_Out;
unsigned long g_lastSendTime;

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

String DoubleString(String& str, int value)
{
	int t = value;
	if (t < 0)
	{
		str = "-";
		t *= -1;
		str += t / 1000;
	}
	else
		str = String(t / 1000);
	str += ".";
	str += (t % 1000);

	return str;
}

char* ftoa(char* a, double f, int precision)
{
	long p[] = { 0,10,100,1000,10000,100000,1000000,10000000,100000000 };

	char* ret = a;
	long heiltal = (long)f;
	itoa(heiltal, a, 10);
	while (*a != '\0') a++;
	*a++ = '.';
	long desimal = abs((long)((f - heiltal) * p[precision]));
	itoa(desimal, a, 10);
	return ret;
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


int16_t Reading(uint8_t channel)
{
	ads1115.setGain(GAIN_TWOTHIRDS); //shouldn't be required!
	int32_t s = 0;
	for (int i = 0; i < SAMPLES; i++)
	{
		int16_t r = ads1115.readADC_SingleEnded(channel);
		s += r;
		//		Serial.print(i); Serial.print(":"); Serial.print(r);Serial.print(",");
	}
	//	Serial.println();
	//	Serial.print(ads); Serial.print(":"); Serial.print(channel); Serial.print(","); Serial.println( (int16_t)(s/SAMPLES));
	return (int16_t)(s / SAMPLES);
}


double ReadingDifferential(uint8_t channel )
{
	double sum = 0;
	int gain;
	int16_t samples[SAMPLES];

	for (int g = 0; g < 6; g++ )
	{
		ads1115.setGain((adsGain_t)GAIN_VALUE[g]);
		int16_t reading;
		if( channel == 0)
			reading = ads1115.readADC_Differential_0_1();
		else
			reading = ads1115.readADC_Differential_2_3();

		gain = g;
		//Serial.print("AIN2: v shunt       "); Serial.print(g); Serial.print(","); Serial.print(adc2); Serial.print(","); Serial.println(adc2 * factor[g], 5);
		if (abs(reading) > 1000)
			break;
	}

	for (int i = 0; i < SAMPLES; i++)
	{
		int16_t reading;
		if (channel == 0)
			samples[i] = ads1115.readADC_Differential_0_1();
		else
			samples[i] = ads1115.readADC_Differential_2_3();
		sum += samples[i];
	}
	
	//reset to default
	ads1115.setGain(GAIN_TWOTHIRDS);


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

	return _median;
}

void setup()
{
	digitalWrite(LED_PIN, HIGH);

	Serial.begin(9600);

	Serial.println(F("Current reverse checker"));

	// if (!g_rf69.init())
	// 	Serial.println("rf69 init failed");
	// if (!g_rf69.setFrequency(915.0))
	// 	Serial.println("rf69 setFrequency failed");
	// // The encryption key has to be the same as the one in the client
	// uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
	// 				0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	// g_rf69.setEncryptionKey(key);
	// g_rf69.setHeaderId(BATTERY_NODE);
	// g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	// Serial.print("RF69 initialise node: ");
	// Serial.print(BATTERY_NODE);
	// Serial.println(" Freq: 915MHz");

	Serial.println("Getting single-ended readings from AIN0..3");
	Serial.println("ADC Range: +/- 6.144V (1 bit = 3mV)");
	ads1115.begin();

	
	g_lastMillis = millis();
	g_mWH_In = 0.0;
	g_mWH_Out = 0.0;
	g_lastSendTime = millis();

	memset(&g_payloadBattery, 0, sizeof(g_payloadBattery));
	g_payloadBattery.subnode = SUB_NODE;

	delay(1000);
	digitalWrite(LED_PIN, LOW);
}


void loop()
{
	int16_t adc0, adc1, adc2, adc3;
	String str;
	char floatStr[16];

	digitalWrite(LED_PIN, HIGH);

	//reset to default
	ads1115.setGain(GAIN_TWOTHIRDS);

	// adc0 = Reading(0);
	// int16_t mVolts = (int16_t)((adc0 * 0.1875) *(100000+6800)/6800); // 6.144v range using a100K and 6.8K voltage divider on 12v source
	// g_payloadBattery.voltage[0] = mVolts/10;  //convert mV to 100ths V

	// adc1 = Reading(1);
	// int16_t vcc_from_arduino = (int16_t)((adc1 * 0.1875) ); // 6.144v range

	float aRead = analogRead(VOLTAGE_MEASURE_PIN);
	float measuredvbat = (aRead/1024.0 * 3.3) * (100000.0+33000.0)/100000.0;		//voltage divider 100k/330k
	g_payloadBattery.voltage[0] =(unsigned long) (measuredvbat*100);//Send the vIn voltage in 100th v


	unsigned long now = millis();
	unsigned long period = now - g_lastMillis;
	g_lastMillis = now;

	double v_current = ReadingDifferential(0);
	double amps = v_current * 90.0 / 100.0; //shunt is 90Amps for 100mV;
	//double watts = voltage * amps/1000.0;


	g_payloadBattery.power[0] = 12 * amps;  //convert mV to mW
//	g_payloadBattery.power[0] = mVolts * amps / 1000.0;  //convert mV to mW
//	g_payloadBattery.power[0] = mVolts * amps / 1000.0 * 4;//convert mV* amps to W . *4 for 4 12v batteries in series tests.
	if (g_payloadBattery.power[0] < 0)
		g_mWH_Out += -1.0 * g_payloadBattery.power[0] * period / (60 * 60 * 1000.0); //convert to wH
	else
		g_mWH_In += g_payloadBattery.power[0] * period / (60 * 60 * 1000.0);
	//this will do the rounding to units of pulses
	g_payloadBattery.pulseIn[0] = g_mWH_In;
	g_payloadBattery.pulseOut[0] = g_mWH_Out;

	double v_current1 = ReadingDifferential(1);
	double amps1 = v_current1 * 90.0 / 100.0; //shunt is 90Amps for 100mV;

	g_payloadBattery.power[1] = 12 * amps1;  //convert mV to mW
//	g_payloadBattery.power[0] = mVolts * amps / 1000.0;  //convert mV to mW
//	g_payloadBattery.power[0] = mVolts * amps / 1000.0 * 4;//convert mV* amps to W . *4 for 4 12v batteries in series tests.
	if (g_payloadBattery.power[1] < 0)
		g_mWH_Out += -1.0 * g_payloadBattery.power[1] * period / (60 * 60 * 1000.0); //convert to wH
	else
		g_mWH_In += g_payloadBattery.power[1] * period / (60 * 60 * 1000.0);
	//this will do the rounding to units of pulses
	g_payloadBattery.pulseIn[1] = g_mWH_In;
	g_payloadBattery.pulseOut[1] = g_mWH_Out;


	Serial.print("A0: (vIn) "); Serial.print(aRead); Serial.print(","); Serial.println(measuredvbat,3);
	Serial.print("DIFF0:    "); Serial.print(v_current,3); Serial.print(","); Serial.println(amps,3);
	Serial.print("DIFF0:    "); Serial.print(v_current1,3); Serial.print(","); Serial.println(amps1,3);
	Serial.println(" ");

	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	// if(millis() - g_lastSendTime > SEND_PERIOD)
	// {
	// 	g_lastSendTime = millis();
	// 	digitalWrite(LED_PIN, HIGH);

	// 	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
	// 	g_rf69.send((const uint8_t*) &g_payloadBattery, sizeof(g_payloadBattery));
	// 	if( g_rf69.waitPacketSent() )
	// 	{
	// 		EmonSerial::PrintBatteryPayload(&g_payloadBattery);
	// 	}
	// 	else
	// 	{
	// 		Serial.println(F("No packet sent"));
	// 	}
	// 	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	// 	digitalWrite(LED_PIN, LOW);
	// }
	digitalWrite(LED_PIN, LOW);
	delay(1000);
}
