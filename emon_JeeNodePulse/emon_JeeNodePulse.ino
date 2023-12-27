//--------------------------------------------------------------------------------------
//Interrupt pulse counting on 4 input pins of a Jeenode
#include <EmonShared.h>
#include <PinChangeInt.h>
#include <EEPROM.h>
#include <SPI.h>

#define HARVEY_FARM

#define LORA_RF95

#ifdef LORA_RF95
	//Note: Use board config Moteino 8MHz for the Lora 8MHz boards
	#include <RH_RF95.h>
	RH_RF95 g_rfRadio;
	#define RADIO_BUF_LEN   RH_RF95_MAX_PAYLOAD_LEN
	#define NODE_INITIALISED_STRING F("RF95 initialise node: ")
#else
	#include <RH_RF69.h>
	RH_RF69 g_rfRadio;
	#define RADIO_BUF_LEN   RH_RF69_MAX_MESSAGE_LEN
	#define GREEN_LED 		9
	#define RFM69_RST     	4
	#define NODE_INITIALISED_STRING F("RF69 initialise node: ")
#endif



//--------------------------------------------------------------------------------------
#define TIMEOUT_PERIOD 420000		//7 minutes in ms. don't report watts if no tick recieved in 2 minutes.
#define EEPROM_BASE 0x10	//where the pulse count is stored


volatile unsigned long 	g_pulseCount[PULSE_MAX_SENSORS]	= { 0,0,0,0,0,0 };			//pulses since recording started
volatile unsigned long	g_lastTick[PULSE_MAX_SENSORS]		= { 0,0,0,0,0,0 };		//millis() value at last pulse
volatile unsigned long	g_period[PULSE_MAX_SENSORS]			= { 0,0,0,0,0,0 };		//ms between last two pulses

#ifdef HARVEY_FARM
const	double		g_pulsePerWH[PULSE_MAX_SENSORS]	= { 0.5,1.0,1.0,1.0,1.0,1.0};	//number of pulses per wH for each input. Some are 2, some are 1, some are 0.4
const	uint8_t		g_pin[PULSE_MAX_SENSORS]		= { 4,3,0,0,0,0 };			//pin number for each input
#else
const	double		g_pulsePerWH[PULSE_MAX_SENSORS]	= { 2.0,2.0,0.4,1.0,2.0,1.0};	//number of pulses per wH for each input. Some are 2, some are 1, some are 0.4
const	uint8_t		g_pin[PULSE_MAX_SENSORS]		= { 4,5,6,7,14,15 };			//pin number for each input
#endif
PayloadPulse g_pulsePayload;

int g_currentHour;


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


// routine called when external interrupt is triggered
void interruptHandlerIR() 
{
	uint8_t sensor = 0;
	while(g_pin[sensor] != PCintPort::arduinoPin)
	{
		if( ++sensor == PULSE_MAX_SENSORS)
			return;		// we only support 6 sensors though we could get an interrupt for sensors 7 and 8!
	}

	g_pulseCount[sensor]++;								//Update number of pulses, 1 pulse = 1 watt
	unsigned long tick = millis();
	if (tick < g_lastTick[sensor])
		g_period[sensor] = tick + (g_lastTick[sensor] - 0xFFFFFFFF);	//rollover occured
	else
		g_period[sensor] = tick - g_lastTick[sensor];
	g_lastTick[sensor] = tick;
}


unsigned short MeterCurrentWatts(int channel)
{
	unsigned long lastPeriod;
	unsigned long thisPeriod;
	unsigned long lastTick;
	unsigned long tick = millis();
	double periodPerWH;	//ms petween puses that represent 1wh
	double watts;

	uint8_t oldSREG = SREG;			// save interrupt register
	cli();							// prevent interrupts while accessing the count	

	lastPeriod = g_period[channel];
	lastTick = g_lastTick[channel];
	
	SREG = oldSREG;					// restore interrupts

	if (tick < lastTick)
		thisPeriod = tick + (lastTick - 0xFFFFFFFF);	//rollover occured
	else
		thisPeriod = tick - lastTick;

	periodPerWH = 1000.0 * 3600.0 / g_pulsePerWH[channel];

	if (thisPeriod < lastPeriod)
		watts = periodPerWH / lastPeriod;		//report the watts for the last tick period
	else if (thisPeriod >= TIMEOUT_PERIOD )
		watts = 0;									// 2 minutes. That is less than 30 watts/hour. report 0 instead of tappering off slowly towards 0 over time.
	else
		watts = periodPerWH / thisPeriod;		//report the wattage as if the tick occured now 


	return (unsigned short)watts;
}


unsigned long MeterTotalWatts(int channel)
{
	unsigned long pulseCount;	// number of watts during this logging interval 
	
	uint8_t oldSREG = SREG;						// save interrupt register
	cli();														// prevent interrupts while accessing the count	
	pulseCount = g_pulseCount[channel];		// get the count from the interrupt handler 
	SREG = oldSREG;										// restore interrupts

	return (unsigned long) (pulseCount/ g_pulsePerWH[channel]);
}


void setup()
{
	Serial.begin(9600);					//fast serial 
	delay(1000);
	Serial.println(F("Fewings emon Pulse"));
	delay(10);


//for reset to 0.	
	// for (int i = 0; i < PULSE_MAX_SENSORS; i++)
	// {
	// 	writeEEPROM(i * sizeof(unsigned long), 0);
	// }

	if (!g_rfRadio.init())
		Serial.println(	NODE_INITIALISED_STRING );
	if (!g_rfRadio.setFrequency(915.0))
		Serial.println("rfRadio setFrequency failed");
	g_rfRadio.setHeaderId(PULSE_JEENODE);

#ifndef LORA_RF95
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rfRadio.setEncryptionKey(key);
#endif

	Serial.print("Node: ");
	Serial.print(PULSE_JEENODE);
	Serial.println(" Freq: 915MHz");

	//initialise
	for (int i = 0; i < PULSE_MAX_SENSORS; i++)
	{
		g_period[i] = millis() - TIMEOUT_PERIOD;

		g_pulsePayload.power[i] = 0;
		g_pulseCount[i] = readEEPROM(i * sizeof(unsigned long));
		g_pulsePayload.pulse[i] = (unsigned long) (g_pulseCount[i] / g_pulsePerWH[i]); // convert from number of pulses since recoding started to wHrs since start
		pinMode(g_pin[i], INPUT_PULLUP);
		if(g_pin[i] != 0 )
		{
			attachPinChangeInterrupt(g_pin[i], interruptHandlerIR, RISING);
		}
		Serial.print(F("Pulse:"));Serial.print(i);
		Serial.print(F(" Pin:"));Serial.print(g_pin[i]);
		Serial.print(F(" Count:"));Serial.print(g_pulseCount[i]);
		Serial.print(F(" WHrs:"));Serial.print(g_pulsePayload.pulse[i]);
		Serial.println();
	}
	g_pulsePayload.subnode = 0;
	g_pulsePayload.supplyV = 0;

	g_currentHour = hour();

	EmonSerial::PrintPulsePayload(NULL);
	
	Serial.println(F("---------------------------------------"));
}


void loop()
{
	//read values
	for (int i = 0; i < PULSE_MAX_SENSORS; i++)
	{
		g_pulsePayload.power[i] = MeterCurrentWatts(i);
		g_pulsePayload.pulse[i] = MeterTotalWatts(i);
	}
	g_pulsePayload.supplyV = readVcc();

	if (hour() != g_currentHour)
	{
		g_currentHour = hour();

		unsigned long pulse[PULSE_MAX_SENSORS];
		uint8_t oldSREG = SREG;			
		cli();							
		for (int i = 0; i < PULSE_MAX_SENSORS; i++)
		{
			pulse[i] = g_pulseCount[i];
		}
		SREG = oldSREG;					// restore interrupts
		//store to EEPROM every hour
		for (int i = 0; i < PULSE_MAX_SENSORS; i++)
		{
			writeEEPROM(i * sizeof(unsigned long), pulse[i]);
		}
	}

	g_rfRadio.send((const uint8_t*) &g_pulsePayload, sizeof (PayloadPulse));
	if( g_rfRadio.waitPacketSent() )
	{
		EmonSerial::PrintPulsePayload(&g_pulsePayload);
	}
	else
	{
		Serial.println(F("No packet sent"));
	}

	delay(2000);		//2s delay	
}


//--------------------------------------------------------------------------------------------------
// Read current emonTx battery voltage - not main supplyV!
//--------------------------------------------------------------------------------------------------
long readVcc() {
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
//--------------------------------------------------------------------------------------------------
