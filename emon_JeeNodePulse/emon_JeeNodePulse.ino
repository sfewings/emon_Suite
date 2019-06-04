//--------------------------------------------------------------------------------------
//Interrupt pulse counting on 4 input pins of a Jeenode

#include <Ports.h>
#include <RF12.h>
#include <avr/eeprom.h>
#include <util/crc16.h>		//cyclic redundancy check
#include <time.h>					//required for EmonShared.h
#include <EmonShared.h>
#include <PinChangeInt.h>

#define ENABLE_SERIAL 1
#define NUM_PINS	PULSE_NUM_PINS
#define FIRST_PIN 4
#define TIMEOUT_PERIOD 420000		//7 minutes in ms. don't report watts if no tick recieved in 2 minutes.

RF12Init rf12Init = { PULSE_JEENODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

volatile unsigned short	g_wHrCount[NUM_PINS]		= { 0,0,0,0 };		//pulses since last call to MeterPulseLog()
volatile unsigned long	g_lastTick[NUM_PINS]		= { 0,0,0,0 };		//millis() value at last pulse
volatile unsigned long	g_period[NUM_PINS]			= { 0,0,0,0 };		//ms between last two pulses
const		double					g_pulsePerWH[NUM_PINS]	= { 2.0,2.0,0.4,1.0};		//number of pulses per wH for each input. Some are 2, some are 1, some are 0.4
PayloadPulse pulsePayload;


// routine called when external interrupt is triggered
void interruptHandlerIR() 
{
	uint8_t pin = PCintPort::arduinoPin - FIRST_PIN; //pin number of this interrupt

	g_wHrCount[pin]++;								//Update number of pulses, 1 pulse = 1 watt
	unsigned long tick = millis();
	if (tick < g_lastTick[pin])
		g_period[pin] = tick + (g_lastTick[pin] - 0xFFFFFFFF);	//rollover occured
	else
		g_period[pin] = tick - g_lastTick[pin];
	g_lastTick[pin] = tick;
}

unsigned short MeterCurrentWatts(int pin)
{
	unsigned long lastPeriod;
	unsigned long thisPeriod;
	unsigned long lastTick;
	unsigned long tick = millis();
	double periodPerWH;	//ms petween puses that represent 1wh
	double watts;

	uint8_t oldSREG = SREG;			// save interrupt register
	cli();							// prevent interrupts while accessing the count	

	lastPeriod = g_period[pin - FIRST_PIN];
	lastTick = g_lastTick[pin - FIRST_PIN];
	
	SREG = oldSREG;					// restore interrupts

	if (tick < lastTick)
		thisPeriod = tick + (lastTick - 0xFFFFFFFF);	//rollover occured
	else
		thisPeriod = tick - lastTick;

	periodPerWH = 1000.0 * 3600.0 / g_pulsePerWH[pin - FIRST_PIN];

	if (thisPeriod < lastPeriod)
		watts = periodPerWH / lastPeriod;		//report the watts for the last tick period
	else if (thisPeriod >= TIMEOUT_PERIOD )
		watts = 0;									// 2 minutes. That is less than 30 watts/hour. report 0 instead of tappering off slowly towards 0 over time.
	else
		watts = periodPerWH / thisPeriod;		//report the wattage as if the tick occured now 


	return (unsigned short)watts;
}


unsigned short MeterPulseLog(int pin)
{
	unsigned short wattSensorCountIR;	// number of watts during this logging interval 
	uint8_t oldSREG = SREG;						// save interrupt register
	cli();														// prevent interrupts while accessing the count	
	wattSensorCountIR = g_wHrCount[pin - FIRST_PIN];		// get the count from the interrupt handler 
	g_wHrCount[pin - FIRST_PIN] = 0;										// reset the watts count
	SREG = oldSREG;										// restore interrupts

	return wattSensorCountIR;
}


void setup()
{
	Serial.begin(9600);					//fast serial 
	delay(1000);
	Serial.println(F("Fewings emon Pulse"));
	delay(10);

	// RFM12B Initialize
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group, 1600);	 
	EmonSerial::PrintRF12Init(rf12Init);
	
	delay(20);

	if (ENABLE_SERIAL == 0) 
	{
		Serial.println("serial disabled");
		Serial.end();
	}

	//initialise
	for (int i = 0; i < NUM_PINS; i++)
	{
		g_period[i] = millis() - TIMEOUT_PERIOD;

		pulsePayload.power[i] = 0;
		pulsePayload.pulse[i] = 0;

		pinMode(FIRST_PIN+i, INPUT_PULLUP);
		attachPinChangeInterrupt(FIRST_PIN + i, interruptHandlerIR, RISING);
	}
	pulsePayload.supplyV = 0;


	EmonSerial::PrintPulsePayload(NULL);
	
	Serial.println("---------------------------------------");
}


void loop()
{
	//read values
	for (int i = 0; i < NUM_PINS; i++)
	{
		pulsePayload.power[i] = MeterCurrentWatts(FIRST_PIN + i);
		pulsePayload.pulse[i] = MeterPulseLog(FIRST_PIN + i);
	}
	pulsePayload.supplyV = readVcc();

	// Send data via RF 
	int i = 0;
	while (!rf12_canSend() && i++ < 100)
	{
		rf12_recvDone();
	}
	rf12_sendStart(0, &pulsePayload, sizeof pulsePayload);
	
	//print the results
	EmonSerial::PrintPulsePayload(&pulsePayload);

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