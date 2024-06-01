//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <EEPROM.h>
#include <DS1603L.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <SoftwareSerial.h>
#include <RH_RF69.h>
#include <avr/wdt.h>    //watchdog timer


#define GREEN_LED 9			// Green LED on emonTx
bool g_toggleLED = false;


SoftwareSerial g_sensorSerial(A1, A0);	//A1=rx, A0=tx


// If your sensor is connected to Serial, Serial1, Serial2, AltSoftSerial, etc. pass that object to the sensor constructor.
DS1603L g_waterHeightSensor(g_sensorSerial);

#define EEPROM_BASE 0x10			//where the water count is stored
#define PULSES_PER_DECILITRE  100

volatile unsigned long	g_flowCount = 0;		//number of pulses in total since installation
volatile unsigned long	g_period = 0;				//ms between last two pulses

RH_RF69 g_rf69;

PayloadWater g_waterPayload;
bool		 g_previousActivity = false;	//true if the last loop had activity. Allow transmit 1 second after flow activity has stopped

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

//--------------------------------------------------------------------------------------------------
// Read Arduino voltage - not main supplyV!
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


//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup()
{
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, HIGH);		//LED has inverted logic. LOW is on, HIGH is off!

	Serial.begin(9600);

	Serial.println(F("Water sensor start"));

	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(WATERLEVEL_NODE);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	Serial.print("RF69 initialise node: ");
	Serial.print(WATERLEVEL_NODE);
	Serial.println(" Freq: 915MHz");


	g_sensorSerial.begin(9600);     // Sensor transmits its data at 9600 bps.
	g_waterHeightSensor.begin();               // Initialise the sensor library.


	//initialise the EEPROMSettings for relay and node number
	EEPROMSettings eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	g_waterPayload.subnode = eepromSettings.subnode;


	EmonSerial::PrintWaterPayload(NULL);

	//water flow rate setup
	//writeEEPROM(0, 0);					//reset the flash
	g_flowCount = readEEPROM(0);	//read last reading from flash

	g_waterPayload.numSensors = 0x11; //one pulse counter and one height sensor 00010001;
	g_waterPayload.flowCount[0] = (unsigned long) ( g_flowCount/PULSES_PER_DECILITRE);

	pinMode(3, INPUT_PULLUP);
	attachInterrupt(digitalPinToInterrupt(3), interruptHandlerWaterFlow, CHANGE);

  	Serial.println(F("Watchdog timer set for 8 seconds"));
  	wdt_enable(WDTO_8S);
  	delay(2000);	//Give time for the water sensor to fill the serial buffer before the first read
	digitalWrite(GREEN_LED, LOW);		//LED has inverted logic. LOW is on, HIGH is off!
}

//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	wdt_reset();

	char s[16];

	unsigned long flowCount = (unsigned long)(g_flowCount / PULSES_PER_DECILITRE);
	uint16_t	waterHeight = g_waterHeightSensor.readSensor();

	bool activity = ( g_waterPayload.flowCount[0]   != flowCount || 
										g_waterPayload.waterHeight[0] != waterHeight   );

	if(activity)
	{
		writeEEPROM(0, g_flowCount);
	}

	g_waterPayload.supplyV = readVcc();
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

	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
	PayloadWater packed;
	int size = EmonSerial::PackWaterPayload(&g_waterPayload, (byte*) &packed);
	//g_rf69.send((const uint8_t*) &packed, size);
	if( g_rf69.waitPacketSent() )
	{
		//unpack and print. To make sure we sent correctly
		memset(&g_waterPayload, 0, sizeof(g_waterPayload));
		EmonSerial::UnpackWaterPayload((byte*) &packed, &g_waterPayload);
		EmonSerial::PrintWaterPayload(&g_waterPayload);
	}
	else
	{
		Serial.println(F("No packet sent"));
	}
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	int waitMS;
	if (activity || g_previousActivity)
		waitMS = 1000;  //keep sending if there is water movement
	else
		waitMS = 30000; //wait 30 seconds before sending a new update
	while(waitMS >= 0)
	{
		delay(1000);
		waitMS = waitMS - 1000;
		wdt_reset();
	}
	g_previousActivity = activity;
}
