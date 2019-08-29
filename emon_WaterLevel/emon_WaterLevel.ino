//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------

#define RF69_COMPAT 1

#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <eeprom.h>
#include <DS1603L.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <SoftwareSerial.h>

#define GREEN_LED 9			// Green LED on emonTx
bool g_toggleLED = false;

#define ENABLE_LCD 0
#if ENABLE_LCD
#include <PortsLCD.h>

LiquidCrystal lcd(A2, 4, 8, 7, 6, 5);

static void lcdSerialReading(uint32_t reading)
{
	lcd.setCursor(0, 1);
	for (int i = 3; i >= 0; i--)
	{
		lcd.print((reading >> (8 * i)) & 0xFF);
		if (i)
			lcd.print(",");
	}
}

#endif

SoftwareSerial g_sensorSerial(A1, A0);	//A1=rx, A0=tx


// If your sensor is connected to Serial, Serial1, Serial2, AltSoftSerial, etc. pass that object to the sensor constructor.
DS1603L g_waterHeightSensor(g_sensorSerial);

#define EEPROM_BASE 0x10	//where the water count is stored
#define TIMEOUT_PERIOD 2000		//10 seconds in ms. don't report litres/min if no tick recieved in this period
#define PULSES_PER_LITRE  1000

volatile unsigned long	g_flowCount = 0;		//number of pulses in total since installation
volatile unsigned long	g_lastTick = 0; 		//millis() value at last pulse
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
	unsigned long tick = millis();
	if (tick < g_lastTick)
		g_period = tick + (g_lastTick - 0xFFFFFFFF);	//rollover occured
	else
		g_period = tick - g_lastTick;
	g_lastTick = tick;
}

unsigned short FlowRateInLitresPerMinute()
{
	unsigned long lastPeriod;
	unsigned long thisPeriod;
	unsigned long lastTick;
	unsigned long tick = millis();
	double periodfor1LitrePerMinute;	//ms petween puses that represent 1 litre/minute
	double litresPerMinute;

	uint8_t oldSREG = SREG;			// save interrupt register
	cli();							// prevent interrupts while accessing the count	

	lastPeriod = g_period;
	lastTick = g_lastTick;

	SREG = oldSREG;					// restore interrupts

	if (tick < lastTick)
		thisPeriod = tick + (lastTick - 0xFFFFFFFF);	//rollover occured
	else
		thisPeriod = tick - lastTick;

	periodfor1LitrePerMinute = 1000.0 * 60.0 / PULSES_PER_LITRE;

	if (thisPeriod < lastPeriod)
		litresPerMinute = periodfor1LitrePerMinute / lastPeriod;		//report the watts for the last tick period
	else if (thisPeriod >= TIMEOUT_PERIOD)
		litresPerMinute = 0;									// report 0 instead of tappering off slowly towards 0 over time.
	else
		litresPerMinute = periodfor1LitrePerMinute / thisPeriod;		//report the litres as if the tick occured now 


	return (unsigned short)litresPerMinute;
}


//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup()
{
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, HIGH);		//LED has inverted logic. LOW is on, HIGH is off!

	Serial.begin(9600);

#if ENABLE_LCD
	lcd.begin(16, 2);
	lcd.setCursor(0, 0);

	lcd.print(F("Water sensor"));
	lcd.setCursor(0, 1);
	lcd.print(F("Monitor 3.0"));
	delay(1000);
	lcd.clear();
#endif

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

	g_period = millis() - TIMEOUT_PERIOD;
	g_waterPayload.flowRate = 0;
	g_waterPayload.flowCount = g_flowCount;

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

	unsigned long flowCount = g_flowCount;
	uint16_t	waterHeight = g_waterHeightSensor.readSensor();

	bool activity = ( g_waterPayload.flowCount   != flowCount || 
										g_waterPayload.waterHeight != waterHeight   );

	if(activity)
	{
		writeEEPROM(0, flowCount);
	}

	g_waterPayload.flowCount = flowCount;
	g_waterPayload.flowRate = FlowRateInLitresPerMinute();
	g_waterPayload.waterHeight = waterHeight;

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

#if ENABLE_LCD
	//toggle a "*" every read
	static bool toggle = true;
	lcd.setCursor(15, 1);
	lcd.print((toggle = !toggle) ? "*" : " ");

	lcd.setCursor(0, 0);
	lcd.print(s);
	lcd.setCursor(0, 1);
	lcdSerialReading(waterHeightSensor.SerialData());
	activity = true;	//loop every second
#endif

	rf12_sleep(RF12_WAKEUP);

	int wait = 1000;
	while (!rf12_canSend() && wait--)
		rf12_recvDone();
	if (wait)
	{
		rf12_sendStart(0, &g_waterPayload, sizeof g_waterPayload);
		rf12_sendWait(0);
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
