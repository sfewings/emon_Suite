#include <Ports.h>	//Jeelib SLeepy routine
#include <avr/eeprom.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <EEPROM.h>
#include <Time.h>			// needed for EmonShared
#include <EmonShared.h>
#include <SPI.h>


#define INTERRUPT_IR				1	// ATmega 168 and 328 - interrupt 0 = pin 2, 1 = pin 3
#define RAIN_GAUGE_PIN				3
#define TEMPERATURE_PIN				5
#define MINUTES_BETWEEN_TRANSMIT  	5
#define VOLTAGE_MEASURE_PIN 		A0	// Original Jeenode used A2. Temperature uses A0
#define EEPROM_BASE 				0x10

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

volatile unsigned long	g_rainCount;			//The count from the rain gauge
volatile unsigned long	g_transmitCount;		//Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
volatile unsigned long	g_minuteCount = 0;		//How many minutes since the last transmit
volatile unsigned long	g_RGlastTick = 0;		//Clock count of last interrupt

//---------------------------------------------------------------------------------------------------
// Dallas temperature sensor	on pin 5, Jeenode port 2
//---------------------------------------------------------------------------------------------------
OneWire oneWire(TEMPERATURE_PIN);
DallasTemperature temperatureSensor(&oneWire);

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

	if (!g_rfRadio.init())
		Serial.println("rf69 init failed");
	if (!g_rfRadio.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	
#ifndef LORA_RF95
	g_rfRadio.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rfRadio.setEncryptionKey(key);
#endif
	g_rfRadio.setHeaderId(RAIN_NODE);

	Serial.print(NODE_INITIALISED_STRING);
	Serial.print(RAIN_NODE);
	Serial.println(" Freq: 915MHz");


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
	Serial.print(F("Rain count=")); 
	Serial.println(g_rainCount);
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
	memset(&rainPayload, 0, sizeof(PayloadRain));

	//transfer all the data from the interrupt values with interrupts disabled
	uint8_t oldSREG = SREG;			// save interrupt register
	cli();							// prevent interrupts while accessing the count	

	bool doTransmit = g_transmitCount < 5 || (++g_minuteCount == MINUTES_BETWEEN_TRANSMIT);

	if (doTransmit)
	{
		if( g_transmitCount == 0)
		{
		writeEEPROM(0, g_rainCount);    //update eeprom
		}
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

		//voltage divider is 60k and 100k. Jeenode reference voltage is 3.3v. AD range is 1024
		//voltage divider current draw is 29 uA
		float measuredvbat = analogRead(VOLTAGE_MEASURE_PIN);
		measuredvbat = (measuredvbat/1024.0 * 3.3) * (1000000.0+1000000.0)/1000000.0;
		rainPayload.supplyV =(unsigned long) (measuredvbat*1000);//sent in mV

#ifndef LORA_RF95
		g_rfRadio.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
#endif
		g_rfRadio.send((const uint8_t*) &rainPayload, sizeof(PayloadRain));
		if( g_rfRadio.waitPacketSent() )
		{
			EmonSerial::PrintRainPayload(&rainPayload);
		}
		else
		{
			Serial.println(F("No packet sent"));
		}
#ifdef LORA_RF95
		g_rfRadio.sleep();
#else
		g_rfRadio.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
#endif

		g_minuteCount = 0;

		//let serial buffer empty
		//see http://www.gammon.com.au/forum/?id=11428
		while (!(UCSR0A & (1 << UDRE0)))  // Wait for empty transmit buffer
			UCSR0A |= 1 << TXC0;  // mark transmission not complete
		while (!(UCSR0A & (1 << TXC0)));   // Wait for the transmission to complete
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
