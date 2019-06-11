//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------

#define RF69_COMPAT 1

#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <eeprom.h>
#include <DS1603L.h>
#include <EmonShared.h>
#include <SoftwareSerial.h>

SoftwareSerial sensorSerial(A1, A0);	//A1=rx, A0=tx

#define EEPROM_BASE 0x10	//where the water count is stored

// If your sensor is connected to Serial, Serial1, Serial2, AltSoftSerial, etc. pass that object to the sensor constructor.
DS1603L waterHeightSensor(sensorSerial);

#define TIMEOUT_PERIOD 2000		//10 seconds in ms. don't report litres/min if no tick recieved in this period
#define PULSES_PER_LITRE  1000

volatile unsigned short	g_flowCount = 0;		//pulses since last call to MeterPulseLog()
volatile unsigned long	g_lastTick = 0; 		//millis() value at last pulse
volatile unsigned long	g_period = 0;				//ms between last two pulses

RF12Init rf12Init = { WATERLEVEL_NODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

PayloadWater payloadWater;

ISR(WDT_vect) { Sleepy::watchdogEvent(); }


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
	Serial.begin(9600);

	Serial.println(F("Water sensor start"));

	Serial.println("rf12_initialize");
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);


	sensorSerial.begin(9600);     // Sensor transmits its data at 9600 bps.
	waterHeightSensor.begin();               // Initialise the sensor library.


	//water flow rate setup

	//writeEEPROM(0, 0);					//reset the flash
	g_flowCount = readEEPROM(0);	//read last reading from flash

	g_period = millis() - TIMEOUT_PERIOD;
	payloadWater.flowRate = 0;
	payloadWater.flowCount = g_flowCount;

	pinMode(3, INPUT_PULLUP);
	attachInterrupt(digitalPinToInterrupt(3), interruptHandlerWaterFlow, CHANGE);

	delay(100);
}

//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	char s[16];
	int activity = payloadWater.flowCount != g_flowCount;

	if(activity)
	{
		writeEEPROM(0, g_flowCount);
	}

	payloadWater.flowRate = FlowRateInLitresPerMinute();
	payloadWater.flowCount = g_flowCount;
	payloadWater.waterHeight = waterHeightSensor.readSensor();

	switch (waterHeightSensor.getStatus())
	{
	case DS1603L_NO_SENSOR_DETECTED:                // No sensor detected: no valid transmission received for >10 seconds.
		strncpy(s,"No sensor",16);
		break;

	case DS1603L_READING_CHECKSUM_FAIL:             // Checksum of the latest transmission failed.
		snprintf(s, 16, "CRC %d mm       ", payloadWater.waterHeight);
		break;

	case DS1603L_READING_SUCCESS:                   // Latest reading was valid and received successfully.
		snprintf(s, 16, "Water %d mm     ", payloadWater.waterHeight);
		break;
	}
		
	Serial.println(s);

	rf12_sleep(RF12_WAKEUP);

	int wait = 1000;
	while (!rf12_canSend() && wait--)
		rf12_recvDone();
	if (wait)
	{
		rf12_sendStart(0, &payloadWater, sizeof payloadWater);
		rf12_sendWait(0);
		EmonSerial::PrintWaterPayload(&payloadWater);
	}
	else
	{
		Serial.println(F("RF12 waiting. No packet sent"));
	}
	rf12_sleep(RF12_SLEEP);
	delay(1000);

	if(!activity)
		Sleepy::loseSomeTime(10000); // go to sleep for longer if nothing is happening
}
