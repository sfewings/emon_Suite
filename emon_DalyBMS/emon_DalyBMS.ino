//------------------------------------------------------------------------------------------------------------------------------------------------
// emon DalyBMS for communication witht eh Daly BMS via RS485
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <EEPROM.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <SoftwareSerial.h>
#include <RH_RF69.h>
#include <avr/wdt.h>    //watchdog timer
#include <daly-bms-uart.h>			//https://github.com/sfewings/daly-bms-uart

#include <Ports.h>
ISR(WDT_vect) { Sleepy::watchdogEvent(); }

#define BOAT_NETWORK
#ifdef BOAT_NETWORK
	#define NETWORK_FREQUENCY 915.0
#else
	#define NETWORK_FREQUENCY 914.0
#endif

#define GREEN_LED 9			// Green LED on emonTx
bool g_toggleLED = false;

//Pinout for MAX485
//DI = TXD = 3
//RO = RXD = 4
//DE = A4
//RE = A5


SoftwareSerial g_sensorSerial(3,4 );	//A1=rx, A0=tx
Daly_BMS_UART g_daly_bms(g_sensorSerial); //if using RS485 board directly  , A4, A5);

PayloadDalyBMS g_payloadDalyBMS;

#define EEPROM_BASE 0x10			//where the water count is stored

RH_RF69 g_rf69;

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

//--------------------------------------------------------------------------------------------------
// Read Arduino voltage - not main supplyV!
//--------------------------------------------------------------------------------------------------
// long readVcc() {
// 	long result;
// 	// Read 1.1V reference against AVcc
// 	ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
// 	delay(2); // Wait for Vref to settle
// 	ADCSRA |= _BV(ADSC); // Convert
// 	while (bit_is_set(ADCSRA, ADSC));
// 	result = ADCL;
// 	result |= ADCH << 8;
// 	result = 1126400L / result; // Back-calculate AVcc in mV
// 	return result;
// }
//--------------------------------------------------------------------------------------------------


//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup()
{
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, HIGH);		//LED has inverted logic. LOW is on, HIGH is off!

	Serial.begin(9600);

	Serial.println(F("Daly BMS sensor start"));

	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(DALY_BMS_NODE);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	Serial.print(F("RF69 initialise node: "));
	Serial.print(DALY_BMS_NODE);
	Serial.print(F(" Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println(F("MHz"));

	//initialise the EEPROMSettings for relay and node number
	EEPROMSettings eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	g_payloadDalyBMS.subnode = eepromSettings.subnode;

 	g_daly_bms.Init(); // This call sets up the driver

	EmonSerial::PrintDalyBMSPayload(NULL);

  	// Serial.println(F("Watchdog timer set for 8 seconds"));
  	// wdt_enable(WDTO_8S);
  	delay(2000);	//Give time for the water sensor to fill the serial buffer before the first read
	digitalWrite(GREEN_LED, LOW);		//LED has inverted logic. LOW is on, HIGH is off!
}

//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	uint32_t millisStart = millis();

	digitalWrite(GREEN_LED, HIGH);

	// This .update() call populates the entire get struct. If you only need certain values (like
	// SOC & Voltage) you could use other public APIs, like getPackMeasurements(), which only query
	// specific values from the BMS instead of all.
	if( g_daly_bms.update() )
	{
		g_payloadDalyBMS.batteryVoltage = (unsigned short) (g_daly_bms.get.packVoltage*10.0);
		g_payloadDalyBMS.batterySoC = (short) (g_daly_bms.get.packSOC*10.0);
		g_payloadDalyBMS.current = g_daly_bms.get.packCurrent;
		g_payloadDalyBMS.resCapacity = g_daly_bms.get.resCapacitymAh/1000;
		g_payloadDalyBMS.temperature = g_daly_bms.get.tempAverage;
		g_payloadDalyBMS.lifetimeCycles = g_daly_bms.get.bmsCycles;
		int numberOfCells = min(g_daly_bms.get.numberOfCells, MAX_BMS_CELLS) ;
		for(int i=0; i<numberOfCells;i++)
		{
			g_payloadDalyBMS.cellmv[i] = short(g_daly_bms.get.cellVmV[i]);
		}

		g_payloadDalyBMS.crc = EmonSerial::CalcCrc((const void*) &g_payloadDalyBMS, sizeof(PayloadDalyBMS)-2);

		g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
		g_rf69.send((const uint8_t*) &g_payloadDalyBMS, sizeof(PayloadDalyBMS));
		if( g_rf69.waitPacketSent() )
		{
			EmonSerial::PrintDalyBMSPayload(&g_payloadDalyBMS);
		}
		else
		{
			Serial.println(F("No packet sent"));
		}
		g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

		// And print them out!
		Serial.print(F("Basic BMS Data:              ")); Serial.println((String)g_daly_bms.get.packVoltage + "V " + (String)g_daly_bms.get.packCurrent + "I " + (String)g_daly_bms.get.packSOC + "\% ");
		Serial.print(F("Package Temperature (C):     ")); Serial.println((String)g_daly_bms.get.tempAverage);
		Serial.print(F("Highest Cell Voltage:        #")); Serial.println((String)g_daly_bms.get.maxCellVNum + " with voltage " + (String)(g_daly_bms.get.maxCellmV / 1000));
		Serial.print(F("Lowest Cell Voltage:         #")); Serial.println((String)g_daly_bms.get.minCellVNum + " with voltage " + (String)(g_daly_bms.get.minCellmV / 1000));
		Serial.print(F("Number of Cells:             ")); Serial.println((String)g_daly_bms.get.numberOfCells);
		Serial.print(F("Number of Temp Sensors:      ")); Serial.println((String)g_daly_bms.get.numOfTempSensors);
		Serial.print(F("BMS Chrg / Dischrg Cycles:   ")); Serial.println((String)g_daly_bms.get.bmsCycles);
		Serial.print(F("BMS Heartbeat:               ")); Serial.println((String)g_daly_bms.get.bmsHeartBeat); // cycle 0-255
		Serial.print(F("Discharge MOSFet Status:     ")); Serial.println((String)g_daly_bms.get.disChargeFetState);
		Serial.print(F("Charge MOSFet Status:        ")); Serial.println((String)g_daly_bms.get.chargeFetState);
		Serial.print(F("Remaining Capacity mAh:      ")); Serial.println((String)g_daly_bms.get.resCapacitymAh);
		//... any many many more data

		for (size_t i = 0; i < size_t(g_daly_bms.get.numberOfCells); i++)
		{
			Serial.println("Cell voltage mV:      " + (String)g_daly_bms.get.cellVmV[i]);
		}

		// Alarm flags
		// These are boolean flags that the BMS will set to indicate various issues.
		// For all flags see the alarm struct in daly-bms-uart.h and refer to the datasheet
		//Serial.println("Level one Cell V to High:    " + (String)g_daly_bms.alarm.levelOneCellVoltageTooHigh);

		/**
		 * Advanced functions:
		 * g_daly_bms.setBmsReset(); //Reseting the BMS, after reboot the MOS Gates are enabled!
		 * g_daly_bms.setDischargeMOS(true); Switches on the discharge Gate
		 * g_daly_bms.setDischargeMOS(false); Switches off thedischarge Gate
		 * g_daly_bms.setChargeMOS(true); Switches on the charge Gate
		 * g_daly_bms.setChargeMOS(false); Switches off the charge Gate
		 */
	
	}
	else
	{
		Serial.println(F("No comms from BMS"));
		for(int i=0;i<3;i++)
		{
			digitalWrite(GREEN_LED, LOW);
			delay(100);
			digitalWrite(GREEN_LED, HIGH);
			delay(100);
		}
	}

	digitalWrite(GREEN_LED, LOW);

	const uint32_t SEND_PERIOD = 10000;
	uint32_t millisTaken = millis()- millisStart; 
	if( millisTaken < SEND_PERIOD )
	// 	delay( SEND_PERIOD - millisTaken);
		Sleepy::loseSomeTime(SEND_PERIOD - millisTaken );

}
