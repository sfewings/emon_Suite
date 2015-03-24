//JeeLabs libraries 
#include <Ports.h>
#include <RF12.h>
#include <avr/eeprom.h>
#include <util/crc16.h>  //cyclic redundancy check
#include <eeprom.h>

//---------------------------------------------------------------------------------------------------
// Serial print settings - disable all serial prints if SERIAL 0 - increases long term stability 
//---------------------------------------------------------------------------------------------------
#define SERIAL 1
//---------------------------------------------------------------------------------------------------

//---------------------------------------------------------------------------------------------------
// RF12 settings 
//---------------------------------------------------------------------------------------------------
// fixed RF12 settings

#define myNodeID	11		 //in the range 1-30
#define network     210      //default network group (can be in the range 1-250). All nodes required to communicate together must be on the same network group
#define freq RF12_915MHZ     //Frequency of RF12B module can be RF12_433MHZ, RF12_868MHZ or RF12_915MHZ. You should use the one matching the module you have.

// set the sync mode to 2 if the fuses are still the Arduino default
// mode 3 (full powerdown) can only be used with 258 CK startup fuses
#define RADIO_SYNC_MODE 2

#define INTERRUPT_IR        1    // ATmega 168 and 328 - interrupt 0 = pin 2, 1 = pin 3
#define RAIN_GAUGE_PIN		3

#define EEPROM_BASE 0x10


volatile unsigned long  g_rainCount;			//The count from the rain gauge
volatile unsigned long  g_transmitCount;		//Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
volatile unsigned long	g_minuteCount = 0;		//How many minutes since the last transmit
volatile unsigned long  g_RGlastTick = 0;		//Clock count of last interrupt
//--------------------------------------------------------------------------------------------------


ISR(WDT_vect) { Sleepy::watchdogEvent(); }


// Rain gauge interrupt routine
void interruptHandlerRainGauge()
{
	unsigned long tick = millis();
	unsigned long period = 0;

	if (tick < g_RGlastTick)
		period = tick + (g_RGlastTick - 0xFFFFFFFF);  //rollover occured
	else
		period = tick - g_RGlastTick;
	g_RGlastTick = tick;

	if (period > 1000)  //more than 1000 ms to avoid switch bounce
	{
		g_rainCount++;			//Update number of pulses, 1 pulse = 0.2mm of rain
		g_transmitCount = 0;
		g_minuteCount = 0;			//Reset the minute count
	}
}


//--------------------------------------------------------------------------------------------------

void setup()
{
	Serial.begin(9600);                   //fast serial 

	delay(500);

	Serial.println(F("Fewings rain gauge Jee node Tx"));

	delay(10);
	//-----------------------------------------
	// RFM12B Initialize
	//------------------------------------------

	rf12_initialize(myNodeID, freq, network);     //Initialize RFM12 with settings defined above, use pin 10 as SSelect
	rf12_sleep(RF12_SLEEP);
	//------------------------------------------

	delay(20);

	Serial.print(F("Node: "));
	Serial.print(myNodeID);
	Serial.print(F(" Freq: "));
	if (freq == RF12_433MHZ) Serial.print(F("433Mhz"));
	if (freq == RF12_868MHZ) Serial.print(F("868Mhz"));
	if (freq == RF12_915MHZ) Serial.print(F("915Mhz"));
	Serial.print(F(" Network: "));
	Serial.println(network);
	delay(20);

	if (SERIAL == 0) 
	{
		Serial.println("serial disabled");
		Serial.end();
	}

	// Initialise 
	//g_rainCount = 0;
	g_rainCount = readEEPROM(0);
	g_transmitCount = 1;
	g_RGlastTick = millis();

	//set up the interrupt handler that will count the IR LED watt pulse counts
	pinMode(RAIN_GAUGE_PIN, INPUT);
	digitalWrite(RAIN_GAUGE_PIN, HIGH);
	attachInterrupt(INTERRUPT_IR, interruptHandlerRainGauge, FALLING);


	Serial.println(F("rainTx: RainCount, Transmit, supplyV"));
	delay(200);
}


void loop()
{
	typedef struct 
	{
		unsigned long rainCount;			//The count from the rain gauge
		unsigned long transmitCount;		//Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
		unsigned long supplyV;						// unit supply voltage
	} Payload;

	Payload rainTx;

	//transfer all the data from the interrupt values with interrupts disabled
	uint8_t oldSREG = SREG;          // save interrupt register
	cli();                           // prevent interrupts while accessing the count   

	bool doTransmit = g_transmitCount < 5 || (++g_minuteCount == 30);
	if (doTransmit)
	{
		g_transmitCount++;
		rainTx.rainCount = g_rainCount;
		rainTx.transmitCount = g_transmitCount;
	}
	SREG = oldSREG;                  // restore interrupts


	//transmit data on the first 5 wakups after a rain gauge event and every 30 minutes
	if (doTransmit)
	{
		rf12_sleep(RF12_WAKEUP);

		if (rainTx.transmitCount == 1)
		{
			writeEEPROM(0, rainTx.rainCount);
		}

		rainTx.supplyV = readVcc();

		while (!rf12_canSend())
			rf12_recvDone();
		rf12_sendStart(0, &rainTx, sizeof rainTx);
		rf12_sendWait(0);
		rf12_sleep(RF12_SLEEP);

		g_minuteCount = 0;

		if (SERIAL == 1)
		{
			Serial.print(F("rainTx: "));
			Serial.print(rainTx.rainCount);
			Serial.print(F(","));
			Serial.print(rainTx.transmitCount);
			Serial.print(F(","));
			Serial.println(rainTx.supplyV);
			delay(100);		//for the serial buffer to empty
		}
	}
	if (rainTx.transmitCount < 5)
		Sleepy::loseSomeTime(1000);
	else
		Sleepy::loseSomeTime(60000);
}


//--------------------------------------------------------------------------------------------------
// Read current emonTx battery voltage - not main supplyV!
//--------------------------------------------------------------------------------------------------
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
//--------------------------------------------------------------------------------------------------
unsigned long readEEPROM(int offset)
{
	unsigned long value = 0;
	char* pc = (char*)&value;

	for (long l = 0; l< sizeof(unsigned long); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_BASE + offset + l);
	}

	return value;
}

void writeEEPROM(int offset, unsigned long value)
{
	char* pc = (char*)&value;

	for (long l = 0; l< sizeof(unsigned long); l++)
	{
		EEPROM.write(EEPROM_BASE + offset + l, *(pc + l));
	}
}