//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------

#define RF69_COMPAT 1

#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <EEPROM.h>
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
