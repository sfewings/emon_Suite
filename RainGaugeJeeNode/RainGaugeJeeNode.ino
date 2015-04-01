//JeeLabs libraries 
#include <Ports.h>
#include <RF12.h>
#include <avr/eeprom.h>
#include <util/crc16.h>	//cyclic redundancy check
#include <OneWire.h>
#include <DallasTemperature.h>
#include <eeprom.h>
#include <Time.h>			// needed for EmonShared
#include <EmonShared.h>


//---------------------------------------------------------------------------------------------------
// Serial print settings - disable all serial prints if SERIAL 0 - increases long term stability 
//---------------------------------------------------------------------------------------------------
#define ENABLE_SERIAL 1
//---------------------------------------------------------------------------------------------------

//---------------------------------------------------------------------------------------------------
// Dallas temperature sensor	on pin 5, Jeenode port 2
//---------------------------------------------------------------------------------------------------
OneWire oneWire(5);
DallasTemperature temperatureSensor(&oneWire);

//---------------------------------------------------------------------------------------------------
// RF12 settings 
//---------------------------------------------------------------------------------------------------

RF12Init rf12Init = { RAIN_NODE, RF12_915MHZ, 210 };

#define INTERRUPT_IR			1	// ATmega 168 and 328 - interrupt 0 = pin 2, 1 = pin 3
#define RAIN_GAUGE_PIN		3

#define EEPROM_BASE 0x10


volatile unsigned long	g_rainCount;			//The count from the rain gauge
volatile unsigned long	g_transmitCount;		//Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
volatile unsigned long	g_minuteCount = 0;		//How many minutes since the last transmit
volatile unsigned long	g_RGlastTick = 0;		//Clock count of last interrupt
//--------------------------------------------------------------------------------------------------


ISR(WDT_vect) { Sleepy::watchdogEvent(); }


// Rain gauge interrupt routine
void interruptHandlerRainGauge()
{
	unsigned long tick = millis();
	unsigned long period = 0;

	if (tick < g_RGlastTick)
		period = tick + (g_RGlastTick - 0xFFFFFFFF);	//rollover occured
	else
		period = tick - g_RGlastTick;
	g_RGlastTick = tick;

	if (period > 1000)	//more than 1000 ms to avoid switch bounce
	{
		g_rainCount++;			//Update number of pulses, 1 pulse = 0.2mm of rain
		g_transmitCount = 0;
		g_minuteCount = 0;			//Reset the minute count
	}
}


//--------------------------------------------------------------------------------------------------

void setup()
{
	Serial.begin(9600);					//fast serial 

	delay(500);

	Serial.println(F("Fewings rain gauge Jeenode Tx"));

	//-----------------------------------------
	// RFM12B Initialize
	//------------------------------------------

	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);	 //Initialize RFM12 with settings defined above, use pin 10 as SSelect
	rf12_sleep(RF12_SLEEP);
	//------------------------------------------

	EmonSerial::PrintRF12Init(rf12Init);

	if (ENABLE_SERIAL == 0)
	{
		Serial.println("serial disabled");
		Serial.end();
	}


	temperatureSensor.begin();
	int numberOfDevices = temperatureSensor.getDeviceCount();
	if (numberOfDevices)
	{
		Serial.print(F("Temperature sensors "));

		for (int i = 0; i<numberOfDevices; i++)
		{
			uint8_t tmp_address[8];
			temperatureSensor.getAddress(tmp_address, i);
			Serial.print(F("Sensor address "));
			Serial.print(i + 1);
			Serial.print(F(": "));
			printAddress(tmp_address);
			Serial.println();
		}
	}


	// Initialise 
	//writeEEPROM(0, 0);					//reset the flash
	g_rainCount = readEEPROM(0);	//read last reading from flash
	g_transmitCount = 1;
	g_RGlastTick = millis();

	//set up the interrupt handler that will count the IR LED watt pulse counts
	pinMode(RAIN_GAUGE_PIN, INPUT);
	digitalWrite(RAIN_GAUGE_PIN, HIGH);
	attachInterrupt(INTERRUPT_IR, interruptHandlerRainGauge, FALLING);

	EmonSerial::PrintRainPayload(NULL);
	delay(100);
}


void loop()
{
	PayloadRain rainPayload;

	//transfer all the data from the interrupt values with interrupts disabled
	uint8_t oldSREG = SREG;			// save interrupt register
	cli();							// prevent interrupts while accessing the count	

	bool doTransmit = g_transmitCount < 5 || (++g_minuteCount == 5);

	if (doTransmit)
	{
		g_transmitCount++;
		rainPayload.rainCount = g_rainCount;
		rainPayload.transmitCount = g_transmitCount;
	}
	SREG = oldSREG;					// restore interrupts


	//transmit data on the first 5 wakups after a rain gauge event and every 30 minutes
	if (doTransmit)
	{
		temperatureSensor.requestTemperatures();
		rainPayload.temperature = temperatureSensor.getTempCByIndex(0) * 100;


		rf12_sleep(RF12_WAKEUP);

		if (rainPayload.transmitCount == 1)
		{
			writeEEPROM(0, rainPayload.rainCount);
		}

		rainPayload.supplyV = readVcc();

		while (!rf12_canSend())
			rf12_recvDone();
		rf12_sendStart(0, &rainPayload, sizeof rainPayload);
		rf12_sendWait(0);
		rf12_sleep(RF12_SLEEP);

		g_minuteCount = 0;

		if (ENABLE_SERIAL == 1)
		{
			EmonSerial::PrintRainPayload(&rainPayload);
			delay(100);		//for the serial buffer to empty
		}
	}
	if (rainPayload.transmitCount < 5)
		Sleepy::loseSomeTime(1000);
	else
		Sleepy::loseSomeTime(60000);
}


void printAddress(uint8_t deviceAddress[8])
{
	Serial.print("{ ");
	for (uint8_t i = 0; i < 8; i++)
	{
		// zero pad the address if necessary
		Serial.print("0x");
		if (deviceAddress[i] < 16) Serial.print("0");
		Serial.print(deviceAddress[i], HEX);
		if (i<7) Serial.print(", ");

	}
	Serial.print(" }");
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