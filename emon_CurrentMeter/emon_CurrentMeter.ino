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
#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h> // include i/o class header
#include <PinChangeInt.h>				//Library to provide additional interrupts on the Arduino Uno328


RF12Init g_rf12Init = { EMON_LOGGER, RF12_915MHZ, FEWINGS_MONITOR_GROUP, RF69_COMPAT };

hd44780_I2Cexp lcd; // declare lcd object: auto locate & config display for hd44780 chip

Adafruit_ADS1115 ads1115;

bool		refreshScreen = false;	//set true when time to completely redraw the screen
volatile unsigned long	g_RGlastTick = 0;


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
	}
}

void setup()
{
	// Print a message to the LCD
	lcd.print("Hello, World!");

	Serial.begin(9600);

	// initialize LCD with number of columns and rows:
	lcd.begin(16, 2);

	Serial.println(F("Current meter sensor start"));

	Serial.println("rf12_initialize");
	rf12_initialize(g_rf12Init.node, g_rf12Init.freq, g_rf12Init.group);
	EmonSerial::PrintRF12Init(g_rf12Init);


	Serial.println("Getting single-ended readings from AIN0..3");
	Serial.println("ADC Range: +/- 6.144V (1 bit = 3mV)");
	ads1115.begin();

	//pushbutton configuration
	pinMode(A3, INPUT_PULLUP);
	attachPinChangeInterrupt(A3, interruptHandlerPushButton, RISING);

	delay(1000);

}

#define PRINT_AND_LOG(NAME, PAYLOAD)\
		Payload##NAME* pPayload = (Payload##NAME*)rf12_data; \
		EmonSerial::Print##NAME##PAYLOAD(pPayload);\

int16_t Reading(uint8_t channel)
{
	const int32_t SAMPLES = 50;
	int32_t s = 0;
	for (int i = 0; i < SAMPLES; i++)
	{
		int16_t r = ads1115.readADC_SingleEnded(channel);
		s += r;
		//Serial.print(r);
		//Serial.print(", ");
		//Serial.println(s);
	}
	return (int16_t) (s / SAMPLES);
}

void loop()
{
	int16_t adc0, adc1, adc2, adc3;
	String str;

	adc0 = Reading(0);
	int16_t voltage = (int16_t)((adc0 * 0.187) *(100000+6800)/6800); // 6.144v range

	adc1 = Reading(1); // ads1115.readADC_SingleEnded(1);
	int16_t v_current = (int16_t)((double)(adc1 - 11870) * 0.187); // 6.144v range

	adc2 = ads1115.readADC_SingleEnded(2);
	uint16_t vcc_from_arduino = (int16_t)((adc2 * 0.187) ); // 6.144v range

	//double current = (double)(v_current - (vcc_from_arduino / 2.0)) / 6144 * 100.0;
	double current = (double)(v_current) / 40;

	long vcc = readVcc();
	//Serial.println("v external,v current,arduino voltage, current");
	//Serial.print(voltage); Serial.print(",");
	//Serial.print(vcc_from_arduino); Serial.print(",");
	//Serial.print(v_current); Serial.print(",");
	//Serial.print(current,3); Serial.print(",");
	//Serial.println();

	lcd.clear();
	if (refreshScreen)
	{
		lcd.clear();
		refreshScreen = false;
		Serial.println("Refresh screen");
	}
	lcd.setCursor(0, 0);
	lcd.print("V");
	lcd.setCursor(2, 0);
	lcd.print(DoubleString(str, voltage));

	//lcd.setCursor(0, 1);
	//lcd.print(DoubleString(str, vcc_from_arduino/2));
	//lcd.setCursor(6, 1);
	//lcd.print(DoubleString(str, v_current));

	lcd.setCursor(0, 1);
	lcd.print("A");
	lcd.setCursor(2, 1);
	lcd.print(DoubleString(str, current*1000));


	adc3 = ads1115.readADC_SingleEnded(3);
	Serial.print("AIN0: v external    "); Serial.print(adc0); Serial.print(","); Serial.println(voltage);
	Serial.print("AIN1: current sense "); Serial.print(adc1); Serial.print(","); Serial.println(v_current);
	Serial.print("AIN2: v arduino     "); Serial.print(adc2); Serial.print(","); Serial.println(vcc_from_arduino);
	Serial.print("AIN3: "); Serial.println(adc3);
	Serial.println(" ");

	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
/*	if (rf12_recvDone())
	{
		//digitalWrite(RED_LED, HIGH);

		if (rf12_crc)
		{
			Serial.print(F("rcv crc err:"));
			Serial.print(rf12_crc);
			Serial.print(F(",len:"));
			Serial.println(rf12_hdr);
		}

		if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)	// and no rf errors
		{
			int node_id = (rf12_hdr & 0x1F);
			int subnode = 0;


			if (node_id == BASE_JEENODE)						// jeenode base Receives the time
			{
				PRINT_AND_LOG(Base, Payload);
				setTime(pPayload->time);
			}

			if (node_id == PULSE_JEENODE)						// === PULSE NODE ====
			{
				PRINT_AND_LOG(Pulse, Payload);
			}
			if (node_id == TEMPERATURE_JEENODE)
			{
				PRINT_AND_LOG(Temperature, Payload);
			}
			if (node_id == HWS_JEENODE)
			{
				PRINT_AND_LOG(HWS, Payload);
			}

			if (node_id == RAIN_NODE)
			{
				PRINT_AND_LOG(Rain, Payload);
			}

			if (node_id == DISPLAY_NODE)
			{
				PRINT_AND_LOG(Disp, Payload);
			}

			if (node_id == WATERLEVEL_NODE)
			{
				PayloadWater* pPayload = (PayloadWater*)rf12_data;
				EmonSerial::UnpackWaterPayload((byte*)pPayload, pPayload);
				EmonSerial::PrintWaterPayload(pPayload);
			}

			if (node_id == SCALE_NODE)
			{
				PRINT_AND_LOG(Scale, Payload);
			}
		}


		//digitalWrite(GREEN_LED, LOW);
		//digitalWrite(RED_LED, LOW);
	}
	*/
	delay(1000);
}

/*
#include <DS1603L.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <SoftwareSerial.h>

#define GREEN_LED 9			// Green LED on emonTx
bool g_toggleLED = false;


SoftwareSerial g_sensorSerial(A1, A0);	//A1=rx, A0=tx


// If your sensor is connected to Serial, Serial1, Serial2, AltSoftSerial, etc. pass that object to the sensor constructor.
DS1603L g_waterHeightSensor(g_sensorSerial);

#define EEPROM_BASE 0x10			//where the water count is stored
#define TIMEOUT_PERIOD 2000		//10 seconds in ms. don't report litres/min if no tick recieved in this period
#define PULSES_PER_DECILITRE  100

volatile unsigned long	g_flowCount = 0;		//number of pulses in total since installation
volatile unsigned long	g_period = 0;				//ms between last two pulses

RF12Init g_rf12Init = { WATERLEVEL_NODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP, RF69_COMPAT };

PayloadWater g_waterPayload;
bool				 g_previousActivity = false;	//true if the last loop had activity. Allow transmit 1 second after flow activity has stopped

unsigned long readEEPROM(int offset)
{
	unsigned long value = 0;
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(unsigned long); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_BASE + offset + l);
	}

	return value;
}

void writeEEPROM(int offset, unsigned long value)
{
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(unsigned long); l++)
	{
		EEPROM.write(EEPROM_BASE + offset + l, *(pc + l));
	}
}


void interruptHandlerWaterFlow()
{
	digitalWrite(GREEN_LED, g_toggleLED?HIGH:LOW);		//LED has inverted logic. LOW is on, HIGH is off!
	g_toggleLED = !g_toggleLED;

	g_flowCount++;								//Update number of pulses, 1 pulse = 1 watt
}


//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup()
{
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, HIGH);		//LED has inverted logic. LOW is on, HIGH is off!

	Serial.begin(9600);

	Serial.println(F("Water sensor start"));

	Serial.println("rf12_initialize");
	rf12_initialize(g_rf12Init.node, g_rf12Init.freq, g_rf12Init.group);
	EmonSerial::PrintRF12Init(g_rf12Init);


	g_sensorSerial.begin(9600);     // Sensor transmits its data at 9600 bps.
	g_waterHeightSensor.begin();               // Initialise the sensor library.


	//initialise the EEPROMSettings for relay and node number
	EEPROMSettings eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);

	g_waterPayload.subnode = eepromSettings.subnode;


	//water flow rate setup
	//writeEEPROM(0, 0);					//reset the flash
	g_flowCount = readEEPROM(0);	//read last reading from flash

	//g_waterPayload.flowRate = 0;
	g_waterPayload.numSensors = 0x11; //one pulse counter and one height sensor 00010001;
	g_waterPayload.flowCount[0] = (unsigned long) ( g_flowCount/PULSES_PER_DECILITRE);

	pinMode(3, INPUT_PULLUP);
	attachInterrupt(digitalPinToInterrupt(3), interruptHandlerWaterFlow, CHANGE);

	delay(100);
	
	digitalWrite(GREEN_LED, LOW);		//LED has inverted logic. LOW is on, HIGH is off!
}

//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	char s[16];

	unsigned long flowCount = (unsigned long)(g_flowCount / PULSES_PER_DECILITRE);
	uint16_t	waterHeight = g_waterHeightSensor.readSensor();

	bool activity = ( g_waterPayload.flowCount[0]   != flowCount || 
										g_waterPayload.waterHeight[0] != waterHeight   );

	if(activity)
	{
		writeEEPROM(0, g_flowCount);
	}

	g_waterPayload.flowCount[0] = flowCount;
	g_waterPayload.waterHeight[0] = waterHeight;

	switch (g_waterHeightSensor.getStatus())
	{
	case DS1603L_NO_SENSOR_DETECTED:                // No sensor detected: no valid transmission received for >10 seconds.
		strncpy(s,"No sensor",16);
		break;

	case DS1603L_READING_CHECKSUM_FAIL:             // Checksum of the latest transmission failed.
		snprintf(s, 16, "CRC %d mm       ", waterHeight);
		break;

	case DS1603L_READING_SUCCESS:                   // Latest reading was valid and received successfully.
		snprintf(s, 16, "Water %d mm     ", waterHeight);
		break;
	}
		
	Serial.println(s);

	rf12_sleep(RF12_WAKEUP);

	int wait = 1000;
	while (!rf12_canSend() && wait--)
		rf12_recvDone();
	if (wait)
	{
    PayloadWater packed;
    int size = EmonSerial::PackWaterPayload(&g_waterPayload, (byte*) &packed);
    rf12_sendStart(0, &packed, size);
    rf12_sendWait(0);
    memset(&g_waterPayload, 0, sizeof(g_waterPayload));
    EmonSerial::UnpackWaterPayload((byte*) &packed, &g_waterPayload);
		EmonSerial::PrintWaterPayload(&g_waterPayload);
	}
	else
	{
		Serial.println(F("RF12 waiting. No packet sent"));
	}
	rf12_sleep(RF12_SLEEP);

	if (activity || g_previousActivity)
		delay(1000);
	else
		delay(30000);
	g_previousActivity = activity;
}
*/