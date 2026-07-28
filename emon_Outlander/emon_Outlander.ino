//emon_Outlander node for reading the Mitsubishi Outlander PHEV (2017-2020) CAN bus
//and transmitting PayloadLeaf to emon_Suite
//July 2026
//
//Single Arduino on the C-CAN bus (500 kbps) via OBD-II connector.
//Uses passive CAN messages for odometer, range, and battery voltage/current,
//plus OBD-II polling (ISO-TP) to the BMU for SOC, capacity, temperature, and SOH.
//
//CAN protocol verified against the OVMS Outlander module:
//  https://github.com/GreyPeter/Open-Vehicle-Monitoring-System-3-Outlander
//
//OBD-II connector pinout (C-CAN bus):
//  Pin 6  -> MCP2515 CAN-H
//  Pin 14 -> MCP2515 CAN-L
//  Pin 4  -> GND
//  Pin 16 -> +12V
//
//Passive CAN messages:
//CAN ID | Field        | Encoding
//-------|--------------|-----------------------------------------------
//0x154  | Odometer     | (d[5]<<16 + d[6]<<8 + d[7]) / 10 km
//0x345  | EV Range     | d[5] km
//0x387  | Battery V/I  | I=(d[2]*256+d[3]-32700)/100 A, V=(d[4]*256+d[5])/10 V
//
//OBD-II polling (BMU 0x761->0x762, service 0x21, PID 1):
//Frame 0 | data[1] | Displayed SOC raw. SOC% = (raw-60)*2/3
//Frame 1 | data[6] | Battery max temperature (Fahrenheit)
//Frame 4 | data[2:3] / 10 | Max capacity (Ah)
//        | data[4:5] / 10 | Remaining capacity (Ah)

#include <CanBusMCP2515_asukiaaa.h>   //See https://github.com/asukiaaa/CanBusMCP2515-arduino
#include <EmonShared.h>
#include <RH_RF69.h>

static const auto CS_PIN                  = 5;
static const auto LED_ACTION_PIN          = 6;
static const uint32_t SEND_PERIOD         = 1000UL*30;  //30 seconds if no data updates
static const uint32_t POLL_PERIOD         = 1000UL*10;  //Poll BMU every 10 seconds
static const uint32_t DEBUG_TIME_INTERVAL = 1000;
static const byte SUBNODE                 = 1;           //Leaf uses subnode 0

static const uint32_t BMU_TX_ID           = 0x761;
static const uint32_t BMU_RX_ID           = 0x762;
// SOH baseline: new car capacity in Ah (40 Ah for both 2017 and 2020 models per OVMS)
static const float NEW_CAR_AH             = 40.0;
// Usable battery capacity for charge time estimate (OVMS uses 12 kWh for all models)
static const float BAT_CAPACITY_KWH       = 12.0;

// Passive CAN IDs we monitor
static const int PASSIVE_IDs[]            = {0x154, 0x345, 0x387};
static const int NUM_PASSIVE              = sizeof(PASSIVE_IDs)/sizeof(PASSIVE_IDs[0]);

static unsigned long        lastDebugTime[NUM_PASSIVE];
CanBusData_asukiaaa::Frame  lastMessage[NUM_PASSIVE];

RH_RF69         g_rf69;
PayloadLeaf     g_payloadLeaf;
CanBusMCP2515_asukiaaa::Driver g_CAN(CS_PIN);

// State from passive messages and BMU polling
float   g_batteryVoltage  = 0;
float   g_batteryCurrent  = 0;
byte    g_soc             = 0;
float   g_maxCapacityAh   = 0;
float   g_remainCapacityAh = 0;

// ISO-TP response assembly
#define MAX_ISOTP_DATA 56
byte    g_isotpBuf[MAX_ISOTP_DATA];


void flashErrorToLED(int error, bool haltExecution = true)
{
  while( haltExecution )
  {
    for( int i = 0; i < error; i++)
    {
      digitalWrite(LED_ACTION_PIN, HIGH);
      delay(100);
      digitalWrite(LED_ACTION_PIN, LOW);
      delay(100);
    }
    delay(1000);
  }
}

bool initCAN(CanBusMCP2515_asukiaaa::Driver& can)
{
  const auto QUARTZ_FREQUENCY  = CanBusMCP2515_asukiaaa::QuartzFrequency::MHz8;
  const auto BITRATE           = CanBusMCP2515_asukiaaa::BitRate::Kbps500;
  CanBusMCP2515_asukiaaa::Settings settings(QUARTZ_FREQUENCY, BITRATE);
  settings.mReceiveBufferSize = 16;
  settings.mTransmitBuffer0Size = 1;  //Need transmit for OBD-II polling
  Serial.print(F("settings for :"));Serial.println(can.CS());
  Serial.println(settings.toString());

  while (true)
  {
    uint16_t errorCode = can.begin(settings);
    if (errorCode == 0)
    {
      Serial.println(F("can.begin() success"));
      return true;
    }
    else
    {
      Serial.print(F("can.begin() failed: "));
      Serial.println(errorCode);
      Serial.println(CanBusMCP2515_asukiaaa::Error::toString(errorCode));
      return false;
    }
  }
}

void setup()
{
  Serial.begin(9600);

  pinMode(LED_ACTION_PIN, OUTPUT);
  digitalWrite(LED_ACTION_PIN, HIGH);

  for(int i=0; i<NUM_PASSIVE; i++)
  {
    lastDebugTime[i] = millis();
  }

  g_payloadLeaf.subnode = SUBNODE;

  if(!initCAN( g_CAN ))
  {
      flashErrorToLED(1); //will never return!
  }

	if (!g_rf69.init())
  {
		Serial.println(F("rf69 init failed"));
    flashErrorToLED(2, false); //will never return!
  }
	if (!g_rf69.setFrequency(915.0))
  {
    Serial.println(F("rf69 setFrequency failed"));
    flashErrorToLED(3, false); //will never return!
  }
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(LEAF_NODE);

	Serial.print(F("RF69 initialise node: "));
	Serial.print(LEAF_NODE);
	Serial.println(F(" Freq: 915MHz"));
  digitalWrite(LED_ACTION_PIN, LOW);

  EmonSerial::PrintLeafPayload(NULL);
}


void printFrame(CanBusData_asukiaaa::Frame& frame)
{
  Serial.print(F("Frame id:0x"));
  Serial.print(frame.id, HEX);
  Serial.print(F(" len:"));
  Serial.print(frame.len);
  Serial.print(F(" data:"));
  for(int i=0; i<frame.len; i++)
  {
    if(frame.data[i] < 0x10) Serial.print('0');
    Serial.print(frame.data[i], HEX);
    Serial.print(F(" "));
  }
  Serial.println();
}


bool processPassiveFrame(CanBusData_asukiaaa::Frame& frame)
{
  if (frame.id == 0x154)
  {
    // Odometer: d[5]<<16 + d[6]<<8 + d[7], in 0.1 km units
    unsigned long odometer = (((unsigned long)frame.data[5]) *256*256
                            + ((unsigned long)frame.data[6]) *256
                            + ((unsigned long)frame.data[7])) / 10;
    if( odometer != g_payloadLeaf.odometer )
    {
      g_payloadLeaf.odometer = odometer;
      return true;
    }
  }
  else if (frame.id == 0x345)
  {
    // EV range in km, direct value
    short range = (short)frame.data[5];
    if( range != g_payloadLeaf.range )
    {
      g_payloadLeaf.range = range;
      return true;
    }
  }
  else if (frame.id == 0x387)
  {
    // Battery current: (d[2]*256+d[3] - 32700) / 100, in Amps (negative = charging)
    g_batteryCurrent = ((float)(frame.data[2] * 256 + frame.data[3]) - 32700.0) / 100.0;
    // Battery voltage: (d[4]*256+d[5]) / 10, in Volts
    g_batteryVoltage = (float)(frame.data[4] * 256 + frame.data[5]) / 10.0;
  }

  return false;
}


// Send ISO-TP single-frame OBD-II request and collect multi-frame response.
// Returns number of assembled data bytes (after stripping service+PID), or 0 on timeout.
int pollBMU(byte pid)
{
  CanBusData_asukiaaa::Frame txFrame;
  txFrame.id = BMU_TX_ID;
  txFrame.ext = false;
  txFrame.len = 8;
  txFrame.data[0] = 0x02;  // ISO-TP single frame, 2 payload bytes
  txFrame.data[1] = 0x21;  // OBD service: ReadDataByLocalIdentifier
  txFrame.data[2] = pid;
  for(int i=3; i<8; i++) txFrame.data[i] = 0;

  if( !g_CAN.tryToSend(txFrame) )
  {
    Serial.println(F("BMU request send failed"));
    return 0;
  }

  // Wait for first frame (FF) from BMU
  unsigned long startTime = millis();
  while(millis() - startTime < 1000)
  {
    g_CAN.poll();
    if( !g_CAN.available() ) continue;

    CanBusData_asukiaaa::Frame rxFrame;
    g_CAN.receive(&rxFrame);

    // Route non-BMU frames to passive handler
    if(rxFrame.id != BMU_RX_ID)
    {
      processPassiveFrame(rxFrame);
      continue;
    }

    byte frameType = rxFrame.data[0] & 0xF0;

    if(frameType == 0x10) // First Frame
    {
      int totalLen = ((rxFrame.data[0] & 0x0F) << 8) | rxFrame.data[1];
      int dataLen = totalLen - 2; // Subtract service response byte and PID
      if(dataLen > MAX_ISOTP_DATA) dataLen = MAX_ISOTP_DATA;

      // FF payload: bytes 2-3 are service+PID, bytes 4-7 are first 4 data bytes
      int bufIdx = 0;
      for(int i=4; i<8 && bufIdx<dataLen; i++)
        g_isotpBuf[bufIdx++] = rxFrame.data[i];

      // Send flow control: continue, send all, 10ms separation
      txFrame.data[0] = 0x30;
      txFrame.data[1] = 0x00;
      txFrame.data[2] = 0x0A;
      for(int i=3; i<8; i++) txFrame.data[i] = 0;
      if( !g_CAN.tryToSend(txFrame) )
      {
        Serial.println(F("BMU flow control send failed"));
        return 0;
      }

      // Collect consecutive frames
      unsigned long cfTimeout = millis();
      while(bufIdx < dataLen && millis()-cfTimeout < 1000)
      {
        g_CAN.poll();
        if( !g_CAN.available() ) continue;

        g_CAN.receive(&rxFrame);
        if(rxFrame.id != BMU_RX_ID)
        {
          processPassiveFrame(rxFrame);
          continue;
        }
        if((rxFrame.data[0] & 0xF0) == 0x20) // Consecutive Frame
        {
          for(int i=1; i<8 && bufIdx<dataLen; i++)
            g_isotpBuf[bufIdx++] = rxFrame.data[i];
          cfTimeout = millis();
        }
      }
      return bufIdx;
    }
  }

  Serial.println(F("BMU poll timeout"));
  return 0;
}


// Parse BMU PID 1 response to update payload fields
bool parseBMUPid1(int dataLen)
{
  if(dataLen < 32) return false;

  bool updateRequired = false;

  // Frame 0, data[1] = buf[1]: Displayed SOC raw. SOC% = (raw-60)*2/3
  byte rawSOC = g_isotpBuf[1];
  byte soc = (byte)(((int)rawSOC - 60) * 2 / 3);
  if(soc > 100) soc = 0;
  if(soc != g_soc)
  {
    g_soc = soc;
    byte chargeBars = (byte)((((unsigned int)soc) * 12 + 50) / 100);
    if(chargeBars != g_payloadLeaf.batteryChargeBars)
    {
      g_payloadLeaf.batteryChargeBars = chargeBars;
      updateRequired = true;
    }
  }

  // Frame 1, data[6] = buf[10]: Battery max temperature in Fahrenheit
  short tempF = (short)g_isotpBuf[10];
  short tempC = (short)((tempF - 32) * 5 / 9);
  if(tempC != g_payloadLeaf.batteryTemperature)
  {
    g_payloadLeaf.batteryTemperature = tempC;
    updateRequired = true;
  }

  // Frame 4, data[2:3] = buf[27:28]: Max capacity / 10 (Ah)
  g_maxCapacityAh = (float)(g_isotpBuf[27] * 256 + g_isotpBuf[28]) / 10.0;
  // Frame 4, data[4:5] = buf[29:30]: Remaining capacity / 10 (Ah)
  g_remainCapacityAh = (float)(g_isotpBuf[29] * 256 + g_isotpBuf[30]) / 10.0;

  // batterySOH = (maxCapacity / newCarCapacity) * 100
  byte soh = (byte)(g_maxCapacityAh / NEW_CAR_AH * 100.0);
  if(soh != g_payloadLeaf.batterySOH)
  {
    g_payloadLeaf.batterySOH = soh;
    updateRequired = true;
  }

  // batteryWH = remaining capacity (Ah) * battery voltage (V)
  if(g_batteryVoltage > 0)
  {
    unsigned long batteryWH = (unsigned long)(g_remainCapacityAh * g_batteryVoltage);
    if(batteryWH != g_payloadLeaf.batteryWH)
    {
      g_payloadLeaf.batteryWH = batteryWH;
      updateRequired = true;
    }
  }

  // chargeTimeRemaining: estimate when charging (current < -0.5A)
  short chargeMinutes = 0;
  if(g_batteryCurrent < -0.5 && g_batteryVoltage > 100)
  {
    float chargePowerW = (-g_batteryCurrent) * g_batteryVoltage;
    if(chargePowerW > 100)
    {
      float remainingWh = BAT_CAPACITY_KWH * 1000.0 * (100.0 - g_soc) / 100.0;
      chargeMinutes = (short)min(1440.0f, remainingWh / chargePowerW * 60.0f);
    }
  }
  if(chargeMinutes != g_payloadLeaf.chargeTimeRemaining)
  {
    g_payloadLeaf.chargeTimeRemaining = chargeMinutes;
    updateRequired = true;
  }

  return updateRequired;
}


void loop()
{
  static uint32_t waitingStart = millis();
  static uint32_t lastPollTime = 0;
  bool dataToTransmit = false;

  CanBusData_asukiaaa::Frame frame;

  g_CAN.poll();

  if ( g_CAN.available())
  {
    g_CAN.receive(&frame);
    int index = -1;
    for(int i=0;i < NUM_PASSIVE; i++)
    {
      if(PASSIVE_IDs[i] == frame.id)
      {
        index = i;
        break;
      }
    }

    if(index != -1)
    {
      if( millis() - DEBUG_TIME_INTERVAL > lastDebugTime[index] )
      {
        lastDebugTime[index] = millis();
        printFrame(frame);
      }
    }

    if(index >= 0 && frame.data64 != lastMessage[index].data64)
    {
      lastMessage[index] = frame;

      if( processPassiveFrame(frame) )
      {
        dataToTransmit = true;
      }
    }
  }

  // Periodic OBD-II poll to BMU for battery data
  if( millis() - lastPollTime > POLL_PERIOD )
  {
    lastPollTime = millis();
    int dataLen = pollBMU(0x01);
    if( dataLen > 0 && parseBMUPid1(dataLen) )
    {
      dataToTransmit = true;
    }
  }

  //are we ready to transmit the packet?
  if( (dataToTransmit || millis() - waitingStart > SEND_PERIOD) &&
      g_payloadLeaf.odometer != 0  )
  {
    waitingStart = millis();
    digitalWrite(LED_ACTION_PIN, HIGH);

    g_rf69.send((const uint8_t*) &g_payloadLeaf, sizeof (PayloadLeaf));
    if( g_rf69.waitPacketSent() )
    {
      EmonSerial::PrintLeafPayload(&g_payloadLeaf);
    }
    else
    {
      Serial.println(F("No packet sent"));
    }

    delay(10);
    digitalWrite(LED_ACTION_PIN, LOW);
  }
  delay(1);
}
