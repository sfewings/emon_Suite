#define RF69_COMPAT 1
#define WHISPER_NODE 1

#include <JeeLib.h>
//Temperature support - OneWire Dallas temperature sensor

#include <Ports.h>
#include <RF12.h>
#include <avr/eeprom.h>
#include <util/crc16.h>		//cyclic redundancy check
#include <time.h>					//required for EmonShared.h
#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <OneWire.h>
#include <DallasTemperature.h>

#define PORTS 5							//number of ports on the JeeNode

DallasTemperature *pDallasOneWire[PORTS];			// Pass our oneWire reference to Dallas Temperature.
int numberOfSensors[PORTS];										//count of sensors on each device/pin
int sleepDelay;																//sleep delay depends on node. So two nodes don't always transmit together
int numberOfDevices;													//The number of temperature sensors connected to the device
PayloadTemperature temperaturePayload;

//moving average buffer and index
#define READING_HISTORY 4		//number of values to average over
int readings[MAX_TEMPERATURE_SENSORS][READING_HISTORY];
int readingIndex = 0;

#define ENABLE_SERIAL 1

RF12Init rf12Init = { TEMPERATURE_JEENODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };
EEPROMSettings  eepromSettings;


//--------------------------------------------------------------------------------------------
// RFM12B Setup
//--------------------------------------------------------------------------------------------

ISR(WDT_vect) { Sleepy::watchdogEvent(); }


void printAddress(uint8_t deviceAddress[8])
{
	Serial.print("{ ");
	for (uint8_t i = 0; i < 8; i++)
	{
		// zero pad the address if necessary
		Serial.print("0x");
		if (deviceAddress[i] < 16) Serial.print("0");
		Serial.print(deviceAddress[i], HEX);
		if (i < 7) Serial.print(", ");

	}
	Serial.print(" }");
}


void setup()
{
	Serial.begin(9600);

	delay(500);

	Serial.println(F("Fewings Jeenode temperature node for emon network"));

	// Data wire assignements
	//JeeNode port,	Arduino pin
	//		IRQ3			3
	//			1				4			
	//			2				5			
	//			3				6			
	//			4				7			

	sleepDelay = 30000;	//in milliseconds

		//initialise the EEPROMSettings for relay and node number
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	if (eepromSettings.relayNumber)
		temperaturePayload.relay = 1 << (eepromSettings.relayNumber-1);
	else
		temperaturePayload.relay = 0;
	temperaturePayload.subnode = eepromSettings.subnode;


	temperaturePayload.numSensors = 0;
	for (int i = 0; i < MAX_TEMPERATURE_SENSORS + 1; i++)
		temperaturePayload.temperature[i] = 0;

	for (int port = 0; port < PORTS; port++)
	{
		OneWire* pOneWire = new OneWire(port + 3);	//
		pDallasOneWire[port] = new DallasTemperature(pOneWire);
		pDallasOneWire[port]->begin();
		numberOfSensors[port] = pDallasOneWire[port]->getDeviceCount();
		temperaturePayload.numSensors += numberOfSensors[port];
		if (numberOfSensors[port])
		{
			Serial.print(F("Temperature sensors on Jeenode port "));
			Serial.print(port);
			Serial.print(F(", arduino pin "));
			Serial.println(port + 3);

			for (int i = 0; i < numberOfSensors[port]; i++)
			{
				uint8_t tmp_address[8];
				pDallasOneWire[port]->getAddress(tmp_address, i);
				Serial.print(F("Sensor address "));
				Serial.print(i + 1);
				Serial.print(F(": "));
				printAddress(tmp_address);
				Serial.println();
			}
		}
		else
		{
			delete pDallasOneWire[port];
			delete pOneWire;
			pDallasOneWire[port] = NULL;
		}
	}

	if (temperaturePayload.numSensors == 0)
		Serial.println(F("No temperature sensors discovered"));
	pinMode(9, OUTPUT);
	for (int i = 0; i < temperaturePayload.numSensors; i++)
	{
		//turn the led on pin 5 (port 2) on for 1ms
		digitalWrite(9, 1);
		delay(20);
		digitalWrite(9, 0);
		delay(480);
	}


	//initialise the reading history
	int readingNum = 0;
	for (int i = 0; i < PORTS; i++)
	{
		if (numberOfSensors[i])
		{
			pDallasOneWire[i]->requestTemperatures();
			for (int t = 0; t < numberOfSensors[i]; t++)
			{
				int reading = 0;
				for (int j = 0; j < READING_HISTORY; j++)
					readings[readingNum][j] = pDallasOneWire[i]->getTempCByIndex(t) * 100;
				readingNum++;
			}
		}
	}

	EmonSerial::PrintTemperaturePayload(NULL);

	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group, 1600);
	rf12_sleep(RF12_SLEEP);
	EmonSerial::PrintRF12Init(rf12Init);

	Serial.println("Initialisation complete");
	delay(50); 	//time for the serial buffer to empty
}

void loop()
{
	int readingNum = 0;
	for (int i = 0; i < PORTS; i++)
	{
		if (numberOfSensors[i])
		{
			pDallasOneWire[i]->requestTemperatures();
			for (int t = 0; t < numberOfSensors[i]; t++)
			{
				readings[readingNum][readingIndex] = pDallasOneWire[i]->getTempCByIndex(t) * 100;
				int reading = 0;
				for (int j = 0; j < READING_HISTORY; j++)
					reading += readings[readingNum][j];
				temperaturePayload.temperature[readingNum] = reading / READING_HISTORY;
				readingNum++;
			}
		}
	}
	readingIndex = (++readingIndex) % READING_HISTORY;


/*	//debug output
	for (int i = 0; i < temperaturePayload.numSensors; i++)
	{
		for (int j = 0; j < READING_HISTORY; j++)
		{
			Serial.print( readings[i][j] );
			if( j < READING_HISTORY-1)
				Serial.print(",");
		}
		Serial.println();
	}
*/

	//add the current supply voltage at the end
#ifdef WHISPER_NODE
	temperaturePayload.supplyV = readVcc_WhisperNode(); 
#else
	temperaturePayload.supplyV =  readVcc();
#endif

	//transmit
	rf12_sleep(RF12_WAKEUP);
	int wait = 1000;
	while (!rf12_canSend() && wait--)
		rf12_recvDone();
	if (wait)
	{
		//only send as many ints as we have temperatures plus numSensors + Vcc
		//rf12_sendStart(0, &temperaturePayload, sizeof(int) * (2 + temperaturePayload.numSensors));
		rf12_sendStart(0, &temperaturePayload, sizeof(temperaturePayload) - sizeof(int)*(MAX_TEMPERATURE_SENSORS- temperaturePayload.numSensors));

		rf12_sendWait(0);
	}
	rf12_sleep(RF12_SLEEP);

	EmonSerial::PrintTemperaturePayload(&temperaturePayload);
	
	//turn the led on pin 5 (port 2) on for 1ms
	pinMode(9, OUTPUT);
	digitalWrite(9, 1);
	delay(1);
	digitalWrite(9, 0);

	//see http://www.gammon.com.au/forum/?id=11428
	while (!(UCSR0A & (1 << UDRE0)))  // Wait for empty transmit buffer
		UCSR0A |= 1 << TXC0;  // mark transmission not complete
	while (!(UCSR0A & (1 << TXC0)));   // Wait for the transmission to complete

	Sleepy::loseSomeTime(sleepDelay);
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

long readVcc_WhisperNode()
{
	//see https://bitbucket.org/talk2/whisper-node-avr/src/master/#markdown-header-buttons-and-leds
	const uint8_t SAMPLES = 5;
	const uint32_t MAX_VOLTAGE = 7282;
	const uint8_t CONTROL_PIN = A0;
	const uint8_t BAT_VOLTAGE_PIN = A6;

	analogReference(INTERNAL);

	// Turn on the MOSFET via control pin
	pinMode(CONTROL_PIN, OUTPUT);
	digitalWrite(CONTROL_PIN, HIGH);

	// Read pin a couple of times and keep adding up.
	uint32_t readings = 0;
	for (uint8_t i = 0; i < SAMPLES; i++)
	{
		readings += analogRead(BAT_VOLTAGE_PIN);
	}

	// Turn off the MOSFET
	digitalWrite(CONTROL_PIN, LOW);

	return (MAX_VOLTAGE * (readings / SAMPLES) / 1023);
}