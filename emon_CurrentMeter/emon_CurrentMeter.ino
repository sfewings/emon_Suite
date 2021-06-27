//------------------------------------------------------------------------------------------------------------------------------------------------
// emon Currenet Meter
//-------------------------------------------------------------------------------------------------------------------------------------------------
#undef  USE_JEELIB
#ifdef USE_JEELIB
  	#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
  	#include <RF69_avr.h>  // for SPI_SCK, SPI_SS, SPI_MOSI & SPI_MISO

  	#define RF69_COMPAT 1
	RF12Init g_rf12Init = { BATTERY_NODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP, RF69_COMPAT };
#else
	#include <SPI.h>
	#include <RH_RF69.h>
	// Singleton instance of the radio driver
	RH_RF69 g_rf69;
#endif

#include <EEPROM.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>

#include <Adafruit_ADS1015.h>
#include <Time.h>
#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h> // include i/o class header
#include <PinChangeInt.h>				//Library to provide additional interrupts on the Arduino Uno328

const double FACTOR[6] = { 0.1875, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125 };
const int GAIN_VALUE[6] = { GAIN_TWOTHIRDS, GAIN_ONE, GAIN_TWO, GAIN_FOUR, GAIN_EIGHT, GAIN_SIXTEEN };
const int32_t SAMPLES = 30;
const uint8_t LED_PIN = 9;
const unsigned long SEND_PERIOD = 15000;  //ms

hd44780_I2Cexp lcd; // declare lcd object: auto locate & config display for hd44780 chip

Adafruit_ADS1115 ads1115;

bool		refreshScreen = false;	//set true when time to completely redraw the screen
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
		refreshScreen = true;
		g_mWH_In = 0.0;
		g_mWH_Out = 0.0;
	}
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

	// initialize LCD with number of columns and rows:
	lcd.begin(16, 2);
	lcd.print("Current meter");

	Serial.println(F("Current meter sensor start"));

#ifdef USE_JLIB
	Serial.println("rf12_initialize");
	rf12_initialize(g_rf12Init.node, g_rf12Init.freq, g_rf12Init.group);
	EmonSerial::PrintRF12Init(g_rf12Init);
#else
	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(BATTERY_NODE);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	Serial.print("RF69 initialise node: ");
	Serial.print(BATTERY_NODE);
	Serial.println(" Freq: 915MHz");
#endif

	Serial.println("Getting single-ended readings from AIN0..3");
	Serial.println("ADC Range: +/- 6.144V (1 bit = 3mV)");
	ads1115.begin();

	//pushbutton configuration
	pinMode(A3, INPUT_PULLUP);
	attachPinChangeInterrupt(A3, interruptHandlerPushButton, RISING);
	
	refreshScreen = true;
	g_lastMillis = millis();
	g_mWH_In = 0.0;
	g_mWH_Out = 0.0;
	g_lastSendTime = millis();

	memset(&g_payloadBattery, 0, sizeof(g_payloadBattery));
	g_payloadBattery.subnode = 1;

	delay(1000);
	digitalWrite(LED_PIN, LOW);
}


void loop()
{
	int16_t adc0, adc1, adc2, adc3;
	String str;
	char floatStr[16];

	//reset to default
	ads1115.setGain(GAIN_TWOTHIRDS);

	adc0 = Reading(0);
	int16_t mVolts = (int16_t)((adc0 * 0.1875) *(100000+6800)/6800); // 6.144v range using a100K and 6.8K voltage divider on 12v source
	g_payloadBattery.voltage[0] = mVolts/10;  //convert mV to 100ths V

	adc1 = Reading(1);
	int16_t vcc_from_arduino = (int16_t)((adc1 * 0.1875) ); // 6.144v range
	g_payloadBattery.voltage[MAX_VOLTAGES-1] = vcc_from_arduino/10;	//we put the MCU voltage in teh last slot. In 100ths of volts

	double v_current = ReadingDifferential(1);
	double amps = v_current * 90.0 / 100.0; //shunt is 90Amps for 100mV;
	//double watts = voltage * amps/1000.0;

	unsigned long now = millis();
	unsigned long period = now - g_lastMillis;
	g_lastMillis = now;

//	g_payloadBattery.power[0] = mVolts * amps / 100.0;  //convert mV to mW
	g_payloadBattery.power[0] = mVolts * amps / 1000.0 * 4;//convert mV* amps to W . *4 for 4 12v batteries in series tests.
	if (g_payloadBattery.power[0] < 0)
		g_mWH_Out += -1.0 * g_payloadBattery.power[0] * period / (60 * 60 * 1000.0); //convert to wH
	else
		g_mWH_In += g_payloadBattery.power[0] * period / (60 * 60 * 1000.0);
	//this will do the rounding to units of pulses
	g_payloadBattery.pulseIn[0] = g_mWH_In;
	g_payloadBattery.pulseOut[0] = g_mWH_Out;


	if (refreshScreen)
	{
		lcd.clear();
		refreshScreen = false;
		Serial.println("Refresh screen");
	}
	lcd.setCursor(0, 0);
	lcd.print("V");
	lcd.setCursor(2, 0);
	lcd.print(DoubleString(str, mVolts));

	lcd.setCursor(8, 0);
	lcd.print("A");
	lcd.setCursor(10, 0);
	lcd.print(amps, 3);

	lcd.setCursor(0, 1);
	lcd.print("In");
	lcd.setCursor(2, 1);
	lcd.print(g_mWH_In, 3);

	lcd.setCursor(8, 1);
	lcd.print("Ot");
	lcd.setCursor(10, 1);
	lcd.print(g_mWH_Out, 3);


	adc3 = ads1115.readADC_SingleEnded(3);
	Serial.print("AIN0: v external    "); Serial.print(adc0); Serial.print(","); Serial.println(mVolts);
	Serial.print("AIN1: v arduino     "); Serial.print(adc1); Serial.print(","); Serial.println(vcc_from_arduino);
	Serial.print("AIN2: v shunt       "); Serial.print("----" ); Serial.print(","); Serial.println(v_current,5);
	Serial.println(" ");


	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	if(millis() - g_lastSendTime > SEND_PERIOD)
	{
		g_lastSendTime = millis();
		digitalWrite(LED_PIN, HIGH);

#ifdef USE_JEELIB
		rf12_sleep(RF12_WAKEUP);
		int wait = 1000;
		while (!rf12_canSend() && wait--)
			rf12_recvDone();
		if (wait)
		{
			rf12_sendStart(0, &g_payloadBattery, sizeof g_payloadBattery);
			rf12_sendWait(0);
			EmonSerial::PrintBatteryPayload(&g_payloadBattery);
			Serial.println(F("Sent"));
		}
		else
		{
			Serial.println(F("RF12 waiting. No packet sent"));
		}
		rf12_sleep(RF12_SLEEP);
#else
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
#endif
		digitalWrite(LED_PIN, LOW);
	}
	delay(1000);
}
