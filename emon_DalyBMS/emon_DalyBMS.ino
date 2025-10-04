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

#define HOME_NETWORK
//#define BOAT_NETWORK
#ifdef BOAT_NETWORK
	#define NETWORK_FREQUENCY 914.0
#elif defined( HOME_NETWORK )
	#define NETWORK_FREQUENCY 915.0
#endif

#define GREEN_LED 9			// Green LED on emonTx

//Pinout for MAX485
//DI = TXD = 3
//RO = RXD = 4
//DE = A4
//RE = A5

//Pinout for Serial or UART board
// RX = 3
// TX = 4

SoftwareSerial g_sensorSerial(3,4 );	//A1=rx, A0=tx
Daly_BMS_UART g_daly_bms(g_sensorSerial); //if using RS485 board directly  , A4, A5);

PayloadDalyBMS g_payloadDalyBMS;

#define EEPROM_BASE 0x10			//where the water

RH_RF69 g_rf69;


bool isRF69HW()
{
	g_rf69.setFrequency(NETWORK_FREQUENCY + 0.5);
	g_rf69.setTxPower(13,false);

	g_rf69.setModeIdle();
	int8_t tempW = g_rf69.temperatureRead();
	Serial.print(F("Temperature W start="));
	Serial.print(tempW);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
	for(int i = 0; i< 300; i++)
	{
		g_rf69.send((const uint8_t*) &g_payloadDalyBMS, sizeof(PayloadDalyBMS));
		g_rf69.waitPacketSent();
	}
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
	g_rf69.setModeIdle();
	int8_t tempWend = g_rf69.temperatureRead();
	tempW =  tempWend - tempW;
	Serial.print(F(", end="));
	Serial.print(tempWend);
	Serial.print(F(", diff="));
	Serial.print(tempW);
	delay(500);

	g_rf69.setTxPower(18,true);
	g_rf69.setModeIdle();
	int8_t tempHW = g_rf69.temperatureRead();
	Serial.print(F("Temperature HW start="));
	Serial.print(tempHW);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
	for(int i = 0; i< 300; i++)
	{
		g_rf69.send((const uint8_t*) &g_payloadDalyBMS, sizeof(PayloadDalyBMS));
		g_rf69.waitPacketSent();
	}
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
	g_rf69.setModeIdle();
	int8_t tempHWend = g_rf69.temperatureRead();
	Serial.print(F(", end="));
	Serial.print(tempHWend);
	tempHW = tempHWend - tempHW;
	Serial.print(F(", diff="));
	Serial.print(tempHW);

	Serial.print( "This is a RFM69" );
	Serial.println( tempHW > tempW ? "HW" : "W" );
	
	g_rf69.setFrequency(NETWORK_FREQUENCY);
	
	return tempHW > tempW;
}
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
	bool isHW = isRF69HW();
	g_rf69.setTxPower(18,isHW);

	Serial.print(F("RF69 initialise node: "));
	Serial.print(DALY_BMS_NODE);
	Serial.print(F(" Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println(F("MHz"));

	//initialise the EEPROMSettings for relay and node number
	EEPROMSettings eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	g_payloadDalyBMS.subnode = eepromSettings.subnode;
	
 	g_daly_bms.Init();

	EmonSerial::PrintDalyBMSPayload(NULL);

  	delay(1000);
	digitalWrite(GREEN_LED, LOW);
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
			Serial.print(F("Cell "));
			Serial.print(i);
			Serial.print(F("voltage mV:      "));
			Serial.println((String)g_daly_bms.get.cellVmV[i]);
		}
		Serial.println();
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

	//see http://www.gammon.com.au/forum/?id=11428
	while (!(UCSR0A & (1 << UDRE0)))  // Wait for empty transmit buffer
		UCSR0A |= 1 << TXC0;  // mark transmission not complete
	while (!(UCSR0A & (1 << TXC0)));   // Wait for the transmission to complete

	digitalWrite(GREEN_LED, LOW);

	const uint32_t SEND_PERIOD = 10000;
	uint32_t millisTaken = millis()- millisStart; 
	if( millisTaken < SEND_PERIOD )
	// 	delay( SEND_PERIOD - millisTaken);
		Sleepy::loseSomeTime(SEND_PERIOD - millisTaken );

}
