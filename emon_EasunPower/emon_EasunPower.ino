//Emon_EasunPower for Easun Power SMT-12KW-48V hybrid inverter
//Communicates via Modbus RTU over RS232 at 9600 baud
//
//Modbus register map based on esphome-smg-ii project (github.com/syssi/esphome-smg-ii)
//Registers read (function 0x03 - Read Holding Registers):
//  213: Output active power (W)           -> activePower
//  214: Output apparent power (VA)        -> apparentPower
//  215: Battery average voltage (0.1V)    -> batteryVoltage
//  216: Battery average current (0.1A)    -> batteryCharging / batteryDischarge
//  223: PV average power (W)             -> pvInputPower
//  229: Battery state of charge (%)       -> batteryCapacity
//
//Hardware connection via RJ45 on inverter:
//  Pin 1 = TX, Pin 2 = RX, Pin 8 = GND
//  Use MAX3232 module for RS232 to TTL conversion
//  DO NOT connect Pin 4 (V+)

#include <SPI.h>
#include <RH_RF69.h>
#include <EEPROM.h>
#include <SoftwareSerial.h>
#include <EmonShared.h>

#define SW_SERIAL_RX_PIN 3
#define SW_SERIAL_TX_PIN 4
#define LED_PIN 9

RH_RF69 g_rf69;

#define INVERTER_SUBNODE 2

#define EEPROM_BASE 0x10

//Modbus configuration
#define MODBUS_SLAVE_ID       1       //Default slave ID. Some Easun models use 5
#define MODBUS_BAUD           2400    //Easun SMT uses 9600 baud
#define MODBUS_FUNC_READ      0x03    //Read Holding Registers. Try 0x04 (Read Input Registers) if 0x03 fails

//Register addresses for status data
#define REG_OUTPUT_ACTIVE_POWER     213
#define REG_OUTPUT_APPARENT_POWER   214
#define REG_BATTERY_VOLTAGE         215   //0.1V
#define REG_BATTERY_CURRENT         216   //0.1A signed: +charging, -discharging
#define REG_PV_POWER                223   //W
#define REG_BATTERY_SOC             229   //%

//Read registers 213-229 in one block (17 registers)
#define REG_START       213
#define REG_COUNT       17

double g_mWH_produced;
unsigned long g_lastMillis;

PayloadInverter g_payloadInverter;

//SoftwareSerial g_serialInverter(SW_SERIAL_RX_PIN, SW_SERIAL_TX_PIN);


//Modbus CRC-16 calculation (CRC-16/MODBUS polynomial 0xA001)
uint16_t modbusCRC16(uint8_t *buf, uint16_t len)
{
  uint16_t crc = 0xFFFF;
  for (uint16_t pos = 0; pos < len; pos++)
  {
    crc ^= (uint16_t)buf[pos];
    for (int i = 8; i != 0; i--)
    {
      if ((crc & 0x0001) != 0)
      {
        crc >>= 1;
        crc ^= 0xA001;
      }
      else
      {
        crc >>= 1;
      }
    }
  }
  return crc;
}


double readEEPROM(int offset)
{
  double value = 0;
  char* pc = (char*)& value;

  for (long l = 0; l < sizeof(double); l++)
  {
    *(pc + l) = EEPROM.read(EEPROM_BASE + offset * sizeof(double) + l);
  }

  return value;
}

void writeEEPROM(int offset, double value)
{
  char* pc = (char*)& value;

  for (long l = 0; l < sizeof(double); l++)
  {
    EEPROM.write(EEPROM_BASE + offset * sizeof(double) + l, *(pc + l));
  }
}


//Send Modbus RTU read request and receive response
//Returns number of data bytes in response, or 0 on error
int modbusReadRegisters(Stream& stream, uint8_t slaveId, uint16_t startReg, uint16_t numRegs, uint8_t* responseBuf, uint16_t responseBufSize)
{
  uint8_t request[8];
  request[0] = slaveId;
  request[1] = MODBUS_FUNC_READ;
  request[2] = (startReg >> 8) & 0xFF;
  request[3] = startReg & 0xFF;
  request[4] = (numRegs >> 8) & 0xFF;
  request[5] = numRegs & 0xFF;
  uint16_t crc = modbusCRC16(request, 6);
  request[6] = crc & 0xFF;         //CRC low byte first (Modbus convention)
  request[7] = (crc >> 8) & 0xFF;  //CRC high byte second

  //Flush input buffer
  while (stream.available() > 0)
    stream.read();

  //Send request
  stream.write(request, 8);

  //Expected response: SlaveID(1) + FuncCode(1) + ByteCount(1) + Data(numRegs*2) + CRC(2)
  uint16_t expectedLen = 3 + numRegs * 2 + 2;
  if (expectedLen > responseBufSize)
  {
    Serial.println(F("Response buffer too small"));
    return 0;
  }

  uint16_t pos = 0;
  unsigned long start = millis();
  while (millis() - start < 2000 && pos < expectedLen)
  {
    if (stream.available() > 0)
    {
      responseBuf[pos++] = stream.read();
    }
  }

  if (pos < 5) //minimum valid response is 5 bytes (error response)
  {
    Serial.print(F("Modbus timeout, received "));
    Serial.print(pos);
    Serial.print(F(" of "));
    Serial.println(expectedLen);
    return 0;
  }

  //Check for Modbus error response
  if (responseBuf[1] & 0x80)
  {
    Serial.print(F("Modbus error, function=0x"));
    Serial.print(responseBuf[1], HEX);
    Serial.print(F(" exception=0x"));
    Serial.println(responseBuf[2], HEX);
    return 0;
  }

  if (pos < expectedLen)
  {
    Serial.print(F("Modbus short response, received "));
    Serial.print(pos);
    Serial.print(F(" of "));
    Serial.println(expectedLen);
    return 0;
  }

  //Verify CRC
  uint16_t recvCrc = modbusCRC16(responseBuf, pos - 2);
  uint16_t checkCrc = (uint16_t)responseBuf[pos - 2] | ((uint16_t)responseBuf[pos - 1] << 8);
  if (recvCrc != checkCrc)
  {
    Serial.print(F("Modbus CRC error: calc=0x"));
    Serial.print(recvCrc, HEX);
    Serial.print(F(" recv=0x"));
    Serial.println(checkCrc, HEX);
    return 0;
  }

  return responseBuf[2]; //byte count
}


//Read a signed 16-bit register value from Modbus response buffer
//regOffset is the register offset from the start of the read block (0-based)
int16_t getRegisterSigned(uint8_t* data, uint16_t regOffset)
{
  uint16_t idx = 3 + regOffset * 2;  //Skip SlaveID(1), FuncCode(1), ByteCount(1)
  return (int16_t)((data[idx] << 8) | data[idx + 1]);
}

//Read an unsigned 16-bit register value from Modbus response buffer
uint16_t getRegisterUnsigned(uint8_t* data, uint16_t regOffset)
{
  uint16_t idx = 3 + regOffset * 2;
  return (uint16_t)((data[idx] << 8) | data[idx + 1]);
}


bool ReadFromInverter(Stream& stream)
{
  //Read registers 213-229 (17 registers) in one Modbus request
  //Response buffer: 3 header + 17*2 data + 2 CRC = 39 bytes
  uint8_t response[48];

  int byteCount = modbusReadRegisters(stream, MODBUS_SLAVE_ID, REG_START, REG_COUNT, response, sizeof(response));

  if (byteCount == 0)
    return false;

  //Register offsets within our read block (relative to REG_START=213):
  // Offset 0  (reg 213): Output active power (W)
  // Offset 1  (reg 214): Output apparent power (VA)
  // Offset 2  (reg 215): Battery voltage (0.1V)
  // Offset 3  (reg 216): Battery current (0.1A, signed: +charge/-discharge)
  // Offset 4  (reg 217): Battery power (W) - not used
  // Offset 5  (reg 218): unknown
  // Offset 6  (reg 219): PV voltage (0.1V) - not used
  // Offset 7  (reg 220): PV current (0.1A) - not used
  // Offset 8  (reg 221): unknown
  // Offset 9  (reg 222): unknown
  // Offset 10 (reg 223): PV power (W)
  // Offset 11 (reg 224): PV charging power (W) - not used
  // Offset 12 (reg 225): Load percentage (%) - not used
  // Offset 13 (reg 226): DCDC temperature (C) - not used
  // Offset 14 (reg 227): Inverter temperature (C) - not used
  // Offset 15 (reg 228): unknown
  // Offset 16 (reg 229): Battery SOC (%)

  g_payloadInverter.activePower    = getRegisterUnsigned(response, 0);   //reg 213: W
  g_payloadInverter.apparentPower  = getRegisterUnsigned(response, 1);   //reg 214: VA
  g_payloadInverter.batteryVoltage = getRegisterUnsigned(response, 2);   //reg 215: 0.1V (matches PayloadInverter units)
  g_payloadInverter.pvInputPower   = getRegisterUnsigned(response, 10);  //reg 223: W
  g_payloadInverter.batteryCapacity = (uint8_t)getRegisterUnsigned(response, 16); //reg 229: %

  //Battery current (reg 216): 0.1A signed. Positive=charging, Negative=discharging
  //PayloadInverter expects separate charge/discharge in whole Amps
  int16_t battCurrent = getRegisterSigned(response, 3);
  if (battCurrent >= 0)
  {
    g_payloadInverter.batteryCharging = battCurrent / 10;   //convert 0.1A to A
    g_payloadInverter.batteryDischarge = 0;
  }
  else
  {
    g_payloadInverter.batteryCharging = 0;
    g_payloadInverter.batteryDischarge = (-battCurrent) / 10; //convert 0.1A to A
  }

  return true;
}


//calculate the number of watt hours and then store to EEPROM, if changed!
void calculateWattHoursAndStore()
{
  double mWH_produced = g_mWH_produced;
  unsigned long now = millis();
  unsigned long period = now - g_lastMillis;

  g_lastMillis = now;
  g_mWH_produced += g_payloadInverter.pvInputPower * period / (60.0 * 60.0 * 1000.0);

  //this will do the rounding to units of pulses
  g_payloadInverter.pulse = g_mWH_produced;

  //write g_mWH_produced to eeprom, if changed
  if (mWH_produced != g_mWH_produced)
  {
    writeEEPROM(0, g_mWH_produced);
  }
}


void FlashLEDError()
{
  for(int i=0; i<3; i++)
  {
    digitalWrite(LED_PIN, HIGH);
    delay(100);
    digitalWrite(LED_PIN, LOW);
    delay(100);
  }
}


void setup()
{
  Serial.begin(9600);
  Serial1.begin(MODBUS_BAUD);

  pinMode(LED_PIN, OUTPUT);

  Serial.println(F("Easun Power SMT-12KW inverter sensor node start"));

  if (!g_rf69.init())
    Serial.println(F("rf69 init failed"));
  if (!g_rf69.setFrequency(915.0))
    Serial.println(F("rf69 setFrequency failed"));
  Serial.println(F("RF69 initialise node: 21 Freq: 915MHz"));

  uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
  g_rf69.setEncryptionKey(key);
  g_rf69.setHeaderId(INVERTER_NODE);
  g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

  g_mWH_produced = readEEPROM(0);
  g_lastMillis = millis();
  Serial.print(F("Total pulse (wh): "));
  Serial.println(g_mWH_produced, 1);

  memset(&g_payloadInverter, 0, sizeof(g_payloadInverter));

  EmonSerial::PrintInverterPayload(NULL);

  delay(1000);
}


void SendPacket()
{
  g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
  g_rf69.send((const uint8_t*) &g_payloadInverter, sizeof(g_payloadInverter));
  g_rf69.waitPacketSent();
  g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
  EmonSerial::PrintInverterPayload(&g_payloadInverter);
}


void loop()
{
  digitalWrite(LED_PIN, HIGH);

  if (ReadFromInverter(Serial1))
  {
    calculateWattHoursAndStore();
    g_payloadInverter.subnode = INVERTER_SUBNODE;
    SendPacket();
  }
  else
  {
    Serial.println(F("Failed to communicate with inverter"));
    FlashLEDError();
  }

  digitalWrite(LED_PIN, LOW);

  delay(13000);
}
