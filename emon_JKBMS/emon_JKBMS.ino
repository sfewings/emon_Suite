//--------------------------------------------------------------------------------
// emon_JKBMS - Communication with JK BMS (PB2A16S30P) via RS485 Modbus RTU
// Reads BMS data and transmits as PayloadDalyBMS over RF95 (with RF69)
//--------------------------------------------------------------------------------
#include <EEPROM.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <SoftwareSerial.h>
#include <RH_RF69.h>
#include <avr/wdt.h>

#include <Ports.h>
ISR(WDT_vect) { Sleepy::watchdogEvent(); }

#define HOME_NETWORK
//#define BOAT_NETWORK
#ifdef BOAT_NETWORK
	#define NETWORK_FREQUENCY 914.0
#elif defined( HOME_NETWORK )
	#define NETWORK_FREQUENCY 915.0
#endif

//--- JK BMS Modbus RTU Configuration ---
// Slave address as configured on the BMS (default 0)
#define JKBMS_SLAVE_ADDR    0x00

// Baud rate must match BMS RS485 setting (configurable via JK BMS app)
// Default BMS baud is 115200, but SoftwareSerial on 8MHz AVR is unreliable
// above 57600. Set the BMS baud rate to 9600 via the app to match this.
#define JKBMS_BAUD_RATE     9600

// JK BMS RS485 Modbus V1.0 Register Addresses
// Cell voltages: UINT16, mV, register addresses step by 2 per cell
#define REG_CELL_V_BASE     0x1200
#define REG_BAT_VOLTAGE     0x1290  // UINT32 (2 regs), mV
#define REG_BAT_CURRENT     0x1298  // INT32  (2 regs), mA
#define REG_BAT_TEMP1       0x129C  // INT16  (1 reg),  0.1 deg C
#define REG_BAT_TEMP2       0x129E  // INT16  (1 reg),  0.1 deg C
#define REG_SOC             0x12A6  // UINT16 (1 reg),  %
#define REG_CAP_REMAIN      0x12A8  // UINT32 (2 regs), mAh
#define REG_CYCLE_COUNT     0x12B0  // UINT32 (2 regs), count

#define NUM_CELLS           12      // PB2A16S30P configured for 12 cells

//--- Pinout ---
// SoftwareSerial: RX=3, TX=4 (Serial to RS485 board)

SoftwareSerial g_sensorSerial(3, 4);

PayloadDalyBMS g_payloadDalyBMS;

#define GREEN_LED 		9

//#define LORA_RF95
#ifdef LORA_RF95
	#include <RH_RF95.h>
	RH_RF95 g_rfRadio;
	#define RADIO_BUF_LEN   RH_RF95_MAX_PAYLOAD_LEN
	#define NODE_INITIALISED_STRING F("RF95 initialise node: ")
#else
	#include <RH_RF69.h>
	RH_RF69 g_rfRadio;
	#define RADIO_BUF_LEN   RH_RF69_MAX_MESSAGE_LEN
	#define RFM69_RST     	4
	#define NODE_INITIALISED_STRING F("RF69 initialise node: ")
#endif


//-------------------------------------------------------------------
// Modbus CRC-16 (CRC-16/MODBUS polynomial 0xA001)
//-------------------------------------------------------------------
uint16_t modbusCRC16(const uint8_t* data, uint16_t len)
{
	uint16_t crc = 0xFFFF;
	for (uint16_t i = 0; i < len; i++)
	{
		crc ^= data[i];
		for (uint8_t j = 0; j < 8; j++)
		{
			if (crc & 0x0001)
				crc = (crc >> 1) ^ 0xA001;
			else
				crc >>= 1;
		}
	}
	return crc;
}

//-------------------------------------------------------------------
// Modbus RTU: Read Holding Registers (function code 0x03)
// Sends request, reads response, verifies CRC
// Returns number of data bytes received, or -1 on error
// numRegs: 1 or 2 only (response buffer limited to 16 bytes)
//-------------------------------------------------------------------
int modbusReadRegisters(uint8_t slaveAddr, uint16_t startReg, uint16_t numRegs,
                        uint8_t* dataBuf, uint16_t dataBufLen)
{
	// Build request frame: [addr][0x03][regHi][regLo][countHi][countLo][crcLo][crcHi]
	uint8_t request[8];
	request[0] = slaveAddr;
	request[1] = 0x03;
	request[2] = (startReg >> 8) & 0xFF;
	request[3] = startReg & 0xFF;
	request[4] = (numRegs >> 8) & 0xFF;
	request[5] = numRegs & 0xFF;
	uint16_t crc = modbusCRC16(request, 6);
	request[6] = crc & 0xFF;         // CRC low byte first
	request[7] = (crc >> 8) & 0xFF;  // CRC high byte

	// Modbus RTU inter-frame gap: the BMS needs time to switch its RS485
	// transceiver from transmit back to receive after the previous response.
	// 3.5 char times at 9600 baud = ~4ms, but use 10ms for margin.
	delay(10);

	// Flush any stale data in receive buffer
	while (g_sensorSerial.available())
		g_sensorSerial.read();

	g_sensorSerial.write(request, 8);

	// Read response: [addr][0x03][byteCount][data...][crcLo][crcHi]
	uint16_t expectedDataBytes = numRegs * 2;
	uint16_t totalExpected = 3 + expectedDataBytes + 2;

	uint8_t response[16];
	uint16_t responseLen = 0;

	unsigned long startTime = millis();
	unsigned long lastByteTime = startTime;
	const unsigned long TIMEOUT = 500;
	const unsigned long BYTE_TIMEOUT = 20;
	//Serial.print(F("Start modbus reg 0x")); Serial.print(startReg, HEX); Serial.print(" for "); Serial.println(numRegs);

	while (responseLen < totalExpected && responseLen < sizeof(response) &&
	       (millis() - startTime) < TIMEOUT)
	{
		if (g_sensorSerial.available())
		{
			response[responseLen++] = g_sensorSerial.read();
			//Serial.print("0x");Serial.println(response[responseLen-1],HEX);
			lastByteTime = millis();
		}
		else if (responseLen > 0 && (millis() - lastByteTime) > BYTE_TIMEOUT)
		{
			break;  // End of frame detected
		}
	}

	// Validate response
	if (responseLen < 5)
	{
		Serial.print(F("Modbus reg 0x")); Serial.print(startReg, HEX);
		Serial.print(F(": no response (got ")); Serial.print(responseLen); Serial.println(F(" bytes)"));
		return -1;
	}
	if (response[0] != slaveAddr)
	{
		Serial.print(F("Modbus reg 0x")); Serial.print(startReg, HEX);
		Serial.print(F(": wrong slave addr 0x")); Serial.println(response[0], HEX);
		return -1;
	}
	if (response[1] & 0x80)
	{
		Serial.print(F("Modbus reg 0x")); Serial.print(startReg, HEX);
		Serial.print(F(": exception code 0x")); Serial.println(response[2], HEX);
		return -1;
	}
	if (response[1] != 0x03)
	{
		Serial.print(F("Modbus reg 0x")); Serial.print(startReg, HEX);
		Serial.print(F(": unexpected function 0x")); Serial.println(response[1], HEX);
		return -1;
	}

	uint8_t byteCount = response[2];
	if (byteCount != expectedDataBytes)
	{
		Serial.print(F("Modbus reg 0x")); Serial.print(startReg, HEX);
		Serial.print(F(": expected ")); Serial.print(expectedDataBytes);
		Serial.print(F(" data bytes, got ")); Serial.println(byteCount);
		return -1;
	}
	if (responseLen < (uint16_t)(3 + byteCount + 2))
	{
		Serial.print(F("Modbus reg 0x")); Serial.print(startReg, HEX);
		Serial.println(F(": response truncated"));
		return -1;
	}

	// Verify CRC
	uint16_t rxCRC = response[responseLen - 2] | ((uint16_t)response[responseLen - 1] << 8);
	uint16_t calcCRC = modbusCRC16(response, responseLen - 2);
	if (rxCRC != calcCRC)
	{
		Serial.print(F("Modbus reg 0x")); Serial.print(startReg, HEX);
		Serial.println(F(": CRC mismatch"));
		return -1;
	}

	// Copy data bytes to caller buffer
	uint16_t copyLen = min((uint16_t)byteCount, dataBufLen);
	memcpy(dataBuf, response + 3, copyLen);

	return copyLen;
}

//-------------------------------------------------------------------
// Helpers: extract values from big-endian Modbus response data
//-------------------------------------------------------------------
uint16_t getUInt16(const uint8_t* d) { return ((uint16_t)d[0] << 8) | d[1]; }
int16_t  getInt16 (const uint8_t* d) { return (int16_t)(((uint16_t)d[0] << 8) | d[1]); }
uint32_t getUInt32(const uint8_t* d) { return ((uint32_t)d[0] << 24) | ((uint32_t)d[1] << 16) | ((uint32_t)d[2] << 8) | d[3]; }
int32_t  getInt32 (const uint8_t* d) { return (int32_t)(((uint32_t)d[0] << 24) | ((uint32_t)d[1] << 16) | ((uint32_t)d[2] << 8) | d[3]); }

//-------------------------------------------------------------------
// Read all required values from JK BMS via Modbus
// Returns true if pack-level reads succeeded 
//-------------------------------------------------------------------
bool readJKBMS()
{
	uint8_t data[4];
	int len;
	bool packSuccess = true;
	int cellFailures = 0;

	// Read cell voltages (each is UINT16 at register REG_CELL_V_BASE + cell*2)
	for (int i = 0; i < NUM_CELLS; i++)
	{
		len = modbusReadRegisters(JKBMS_SLAVE_ADDR, REG_CELL_V_BASE + i * 2, 1, data, sizeof(data));
		if (len >= 2)
		{
			g_payloadDalyBMS.cellmv[i] = (short)getUInt16(data);  // mV
		}
		else
		{
			g_payloadDalyBMS.cellmv[i] = 0;
			cellFailures++;
		}
	}
	if (cellFailures > 0)
	{
		Serial.print(F("Cell read failures: ")); Serial.println(cellFailures);
		packSuccess = false;
	}

	// Battery voltage: UINT32 in mV, convert to 0.1V for payload
	len = modbusReadRegisters(JKBMS_SLAVE_ADDR, REG_BAT_VOLTAGE, 2, data, sizeof(data));
	if (len >= 4)
	{
		uint32_t voltmV = getUInt32(data);
		g_payloadDalyBMS.batteryVoltage = (unsigned short)(voltmV / 100);
	}
	else
		packSuccess = false;

	// Battery current: INT32 in mA, convert to A (float) for payload
	len = modbusReadRegisters(JKBMS_SLAVE_ADDR, REG_BAT_CURRENT, 2, data, sizeof(data));
	if (len >= 4)
	{
		int32_t currentmA = getInt32(data);
		g_payloadDalyBMS.current = -currentmA / 1000.0;
	}
	else
		packSuccess = false;

	// Battery temperature 1: INT16 in 0.1 deg C, convert to deg C (float)
	len = modbusReadRegisters(JKBMS_SLAVE_ADDR, REG_BAT_TEMP1, 1, data, sizeof(data));
	if (len >= 2)
	{
		int16_t temp = getInt16(data);
		g_payloadDalyBMS.temperature = temp / 10.0;
	}
	else
		packSuccess = false;

	// State of charge: UINT16 in %, convert to 0.1% for payload
	len = modbusReadRegisters(JKBMS_SLAVE_ADDR, REG_SOC, 1, data, sizeof(data));
	if (len >= 2)
	{
		uint16_t soc = getUInt16(data);
		g_payloadDalyBMS.batterySoC = (short)(soc * 10);
	}
	else
		packSuccess = false;

	// Remaining capacity: UINT32 in mAh, convert to Ah for payload
	len = modbusReadRegisters(JKBMS_SLAVE_ADDR, REG_CAP_REMAIN, 2, data, sizeof(data));
	if (len >= 4)
	{
		uint32_t capMah = getUInt32(data);
		g_payloadDalyBMS.resCapacity = capMah / 1000;
	}
	else
		packSuccess = false;

	// Cycle count: UINT32
	len = modbusReadRegisters(JKBMS_SLAVE_ADDR, REG_CYCLE_COUNT, 2, data, sizeof(data));
	if (len >= 4)
	{
		uint32_t cycles = getUInt32(data);
		g_payloadDalyBMS.lifetimeCycles = (short)cycles;
	}
	else
		packSuccess = false;

	return packSuccess;
}

//-------------------------------------------------------------------
// Setup
//-------------------------------------------------------------------
void setup()
{
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, HIGH);		// LED inverted logic: LOW=on, HIGH=off

	Serial.begin(9600);

	Serial.println(F("JK BMS sensor start"));

	if (!g_rfRadio.init())
		Serial.println("rf init failed");
	if (!g_rfRadio.setFrequency(NETWORK_FREQUENCY))
		Serial.println("rf setFrequency failed");
	g_rfRadio.setHeaderId(DALY_BMS_NODE);
#ifndef LORA_RF95
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rfRadio.setEncryptionKey(key);
	g_rfRadio.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
#endif

	Serial.print(F("RF initialise node: "));
	Serial.print(DALY_BMS_NODE);
	Serial.print(F(" Freq: ")); Serial.print(NETWORK_FREQUENCY, 1); Serial.println(F("MHz"));

	// Read EEPROM settings for subnode number
	EEPROMSettings eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	g_payloadDalyBMS.subnode = eepromSettings.subnode;

	// Initialise RS485 serial for JK BMS Modbus communication
	g_sensorSerial.begin(JKBMS_BAUD_RATE);

	EmonSerial::PrintDalyBMSPayload(NULL);

	//delay(1000);
	digitalWrite(GREEN_LED, LOW);
	delay(500);
}

//-------------------------------------------------------------------
// Loop
//-------------------------------------------------------------------
void loop()
{
	uint32_t millisStart = millis();

	digitalWrite(GREEN_LED, HIGH);

	if (readJKBMS())
	{
		g_payloadDalyBMS.crc = EmonSerial::CalcCrc((const void*) &g_payloadDalyBMS, sizeof(PayloadDalyBMS) - 2);

#ifndef LORA_RF95
		g_rfRadio.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
#endif
		g_rfRadio.send((const uint8_t*) &g_payloadDalyBMS, sizeof(PayloadDalyBMS));
		if (g_rfRadio.waitPacketSent())
		{
			EmonSerial::PrintDalyBMSPayload(&g_payloadDalyBMS);
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

		// Debug output
		Serial.print(F("Pack Voltage:    ")); Serial.print(g_payloadDalyBMS.batteryVoltage / 10.0, 1); Serial.println(F("V"));
		Serial.print(F("Pack Current:    ")); Serial.print(g_payloadDalyBMS.current, 1); Serial.println(F("A"));
		Serial.print(F("SOC:             ")); Serial.print(g_payloadDalyBMS.batterySoC / 10.0, 1); Serial.println(F("%"));
		Serial.print(F("Temperature:     ")); Serial.print(g_payloadDalyBMS.temperature, 1); Serial.println(F("C"));
		Serial.print(F("Remaining Cap:   ")); Serial.print(g_payloadDalyBMS.resCapacity); Serial.println(F("Ah"));
		Serial.print(F("Cycle Count:     ")); Serial.println(g_payloadDalyBMS.lifetimeCycles);

		for (int i = 0; i < NUM_CELLS; i++)
		{
			Serial.print(F("Cell "));
			Serial.print(i);
			Serial.print(F(" mV:       "));
			Serial.println(g_payloadDalyBMS.cellmv[i]);
		}
		Serial.println();
	}
	else
	{
		Serial.println(F("No comms from BMS"));
		for (int i = 0; i < 3; i++)
		{
			digitalWrite(GREEN_LED, LOW);
			delay(100);
			digitalWrite(GREEN_LED, HIGH);
			delay(100);
		}
	}

	// Wait for serial TX to complete before sleeping
	while (!(UCSR0A & (1 << UDRE0)))
		UCSR0A |= 1 << TXC0;
	while (!(UCSR0A & (1 << TXC0)));

	digitalWrite(GREEN_LED, LOW);

	const uint32_t SEND_PERIOD = 10000;
	uint32_t millisTaken = millis() - millisStart;
	if (millisTaken < SEND_PERIOD)
		Sleepy::loseSomeTime(SEND_PERIOD - millisTaken);
}
