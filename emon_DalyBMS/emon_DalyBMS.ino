//------------------------------------------------------------------------------------------------------------------------------------------------
// emon DalyBMS for communication witht eh Daly BMS via RS485
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <EEPROM.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <SoftwareSerial.h>
#include <RH_RF69.h>
#include <avr/wdt.h>    //watchdog timer
#include <daly-bms-uart.h>			//https://github.com/maland16/daly-bms-uart

#define GREEN_LED 9			// Green LED on emonTx
bool g_toggleLED = false;

//Pinout for MAX485
//DI = TXD = 3
//RO = RXD = 4
//DE = A6
//RE = A5


SoftwareSerial g_sensorSerial(4, 3);	//A1=rx, A0=tx
Daly_BMS_UART g_daly_bms(g_sensorSerial, A4, A5);


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

	Serial.println(F("Daly BMS sensor start"));

	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(DALY_BMS_NODE);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	Serial.print("RF69 initialise node: ");
	Serial.print(DALY_BMS_NODE);
	Serial.println(" Freq: 915MHz");

	//initialise the EEPROMSettings for relay and node number
	EEPROMSettings eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
//	g_waterPayload.subnode = eepromSettings.subnode;

 	g_daly_bms.Init(); // This call sets up the driver

//	EmonSerial::PrintWaterPayload(NULL);

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
//	wdt_reset();

	// This .update() call populates the entire get struct. If you only need certain values (like
	// SOC & Voltage) you could use other public APIs, like getPackMeasurements(), which only query
	// specific values from the BMS instead of all.
	g_daly_bms.update();

	// And print them out!
	Serial.println("Basic BMS Data:              " + (String)g_daly_bms.get.packVoltage + "V " + (String)g_daly_bms.get.packCurrent + "I " + (String)g_daly_bms.get.packSOC + "\% ");
	Serial.println("Package Temperature (C):     " + (String)g_daly_bms.get.tempAverage);
	Serial.println("Highest Cell Voltage:        #" + (String)g_daly_bms.get.maxCellVNum + " with voltage " + (String)(g_daly_bms.get.maxCellmV / 1000));
	Serial.println("Lowest Cell Voltage:         #" + (String)g_daly_bms.get.minCellVNum + " with voltage " + (String)(g_daly_bms.get.minCellmV / 1000));
	Serial.println("Number of Cells:             " + (String)g_daly_bms.get.numberOfCells);
	Serial.println("Number of Temp Sensors:      " + (String)g_daly_bms.get.numOfTempSensors);
	Serial.println("BMS Chrg / Dischrg Cycles:   " + (String)g_daly_bms.get.bmsCycles);
	Serial.println("BMS Heartbeat:               " + (String)g_daly_bms.get.bmsHeartBeat); // cycle 0-255
	Serial.println("Discharge MOSFet Status:     " + (String)g_daly_bms.get.disChargeFetState);
	Serial.println("Charge MOSFet Status:        " + (String)g_daly_bms.get.chargeFetState);
	Serial.println("Remaining Capacity mAh:      " + (String)g_daly_bms.get.resCapacitymAh);
	//... any many many more data

	for (size_t i = 0; i < size_t(g_daly_bms.get.numberOfCells); i++)
	{
		Serial.println("Cell voltage mV:      " + (String)g_daly_bms.get.cellVmV[i]);
	}

	// Alarm flags
	// These are boolean flags that the BMS will set to indicate various issues.
	// For all flags see the alarm struct in daly-bms-uart.h and refer to the datasheet
	Serial.println("Level one Cell V to High:    " + (String)g_daly_bms.alarm.levelOneCellVoltageTooHigh);

	/**
	 * Advanced functions:
	 * g_daly_bms.setBmsReset(); //Reseting the BMS, after reboot the MOS Gates are enabled!
	 * g_daly_bms.setDischargeMOS(true); Switches on the discharge Gate
	 * g_daly_bms.setDischargeMOS(false); Switches off thedischarge Gate
	 * g_daly_bms.setChargeMOS(true); Switches on the charge Gate
	 * g_daly_bms.setChargeMOS(false); Switches off the charge Gate
	 */
	
	// g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
	// PayloadWater packed;
	// int size = EmonSerial::PackWaterPayload(&g_waterPayload, (byte*) &packed);
	// //g_rf69.send((const uint8_t*) &packed, size);
	// if( g_rf69.waitPacketSent() )
	// {
	// 	//unpack and print. To make sure we sent correctly
	// 	memset(&g_waterPayload, 0, sizeof(g_waterPayload));
	// 	EmonSerial::UnpackWaterPayload((byte*) &packed, &g_waterPayload);
	// 	EmonSerial::PrintWaterPayload(&g_waterPayload);
	// }
	// else
	// {
	// 	Serial.println(F("No packet sent"));
	// }
	// g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	delay(3000);
}
