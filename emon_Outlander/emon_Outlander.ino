//emon_Outlander node for reading the 2020 Mitsubishi Outlander PHEV CAN bus and transmitting PayloadLeaf to emon_Suite
//July 2026
//
//Single Arduino on the EV CAN bus (500 kbps). All required data is available on this bus.
//
//OBD-II connector pinout (EV CAN bus, not the standard diagnostic CAN on pins 6/14):
//  Pin 3  -> MCP2515 CAN-H
//  Pin 11 -> MCP2515 CAN-L
//  Pin 4  -> GND
//  Pin 16 -> +12V
//
//CAN bus mappings sourced from OVMS project and community reverse-engineering.
//Verify byte positions with a CAN bus sniffer on your specific vehicle.
//
//CAN ID | Field                | Bytes      | Encoding
//-------|----------------------|------------|------------------------------------------
//0x412  | Odometer             | [1:3]      | 24-bit big-endian, km
//0x374  | Battery SOC          | [4]        | 0.5% units (divide by 2 for percentage)
//0x384  | Remaining capacity   | [0:1]      | Big-endian, 0.01 kWh units (* 10 = Wh)
//       | Full capacity        | [2:3]      | Big-endian, 0.01 kWh units
//       | Battery SOH          | [4]        | Percentage
//0x377  | Battery temperature  | [1]        | Max cell temp, offset -40 celsius
//0x389  | Charge time remain   | [1:2]      | Big-endian, minutes

#include <CanBusMCP2515_asukiaaa.h>   //See https://github.com/asukiaaa/CanBusMCP2515-arduino
#include <EmonShared.h>
#include <RH_RF69.h>

static const auto CS_PIN                  = 5;
static const auto LED_ACTION_PIN          = 6;
static const uint32_t SEND_PERIOD         = 1000*30; //30 seconds if no data updates
static const uint32_t DEBUG_TIME_INTERVAL = 1000;
static const byte SUBNODE                 = 1;       //Leaf uses subnode 0

// 2020 Outlander PHEV: 13.8 kWh battery, ~50 km EV range = ~276 Wh/km
static const int ENERGY_PER_KM            = 276;

static const int ALL_MESSAGE_IDs[]        = {0x412, 0x374, 0x384, 0x377, 0x389};
static const int NUM_MESSAGES             = sizeof(ALL_MESSAGE_IDs)/sizeof(ALL_MESSAGE_IDs[0]);

static unsigned long        lastDebugTime[NUM_MESSAGES];
CanBusData_asukiaaa::Frame  lastMessage[NUM_MESSAGES];

RH_RF69         g_rf69;
PayloadLeaf     g_payloadLeaf;
CanBusMCP2515_asukiaaa::Driver g_CAN(CS_PIN);

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
  settings.mTransmitBuffer0Size = 0;
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

  for(int i=0; i<NUM_MESSAGES; i++)
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
	// The encryption key has to be the same as the one in the client
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


bool processFrame(CanBusData_asukiaaa::Frame& frame)
{
  if (frame.id == 0x412)
  {
    unsigned long odometer = ((unsigned long)frame.data[1]) *256*256 + ((unsigned long)frame.data[2]) *256 + ((unsigned long)frame.data[3]);
    if( odometer != g_payloadLeaf.odometer )
    {
      g_payloadLeaf.odometer = odometer;
      return true;
    }
  }
  else if (frame.id == 0x374)
  {
    // SOC in 0.5% units, map to 0-12 charge bars for PayloadLeaf compatibility
    byte soc = frame.data[4] / 2;
    byte chargeBars = (byte)((((unsigned int)soc) * 12 + 50) / 100);

    if( g_payloadLeaf.batteryChargeBars != chargeBars )
    {
      g_payloadLeaf.batteryChargeBars = chargeBars;
      return true;
    }
  }
  else if (frame.id == 0x384)
  {
    unsigned long remainingWH = (((unsigned long)frame.data[0]) * 256 + frame.data[1]) * 10UL;
    byte soh = frame.data[4];

    // Estimate EV range from remaining capacity
    short range = 0;
    if( remainingWH > 0 )
    {
      range = (short)(remainingWH / ENERGY_PER_KM);
    }

    bool updateRequired = false;
    if( remainingWH != g_payloadLeaf.batteryWH )
    {
      g_payloadLeaf.batteryWH = remainingWH;
      updateRequired = true;
    }
    if( soh != g_payloadLeaf.batterySOH )
    {
      g_payloadLeaf.batterySOH = soh;
      updateRequired = true;
    }
    if( range != g_payloadLeaf.range )
    {
      g_payloadLeaf.range = range;
      updateRequired = true;
    }
    return updateRequired;
  }
  else if (frame.id == 0x377)
  {
    short temp = (short)frame.data[1] - 40;
    if( temp != g_payloadLeaf.batteryTemperature )
    {
      g_payloadLeaf.batteryTemperature = temp;
      return true;
    }
  }
  else if (frame.id == 0x389)
  {
    short chargeMinutes = (short)(((unsigned int)frame.data[1]) * 256 + frame.data[2]);
    if( chargeMinutes != g_payloadLeaf.chargeTimeRemaining )
    {
      g_payloadLeaf.chargeTimeRemaining = chargeMinutes;
      return true;
    }
  }

  return false;
}

void loop()
{
  static uint32_t waitingStart = millis();
  bool dataToTransmit = false;

  CanBusData_asukiaaa::Frame frame;

  if ( g_CAN.available())
  {
    g_CAN.receive(&frame);
    int index = -1;
    for(int i=0;i < NUM_MESSAGES; i++)
    {
      if(ALL_MESSAGE_IDs[i] == frame.id)
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

    // try processing the frame if it is different from the last received frame
    if(index >= 0 && frame.data64 != lastMessage[index].data64)
    {
      lastMessage[index] = frame;

      if( processFrame(frame) )
      {
        dataToTransmit = true;
      }
    }
  }

  //are we ready to transmit the packet?
  if( (dataToTransmit || millis() - waitingStart > SEND_PERIOD) &&
      g_payloadLeaf.odometer != 0  )  //don't send till we have at least filled the odometer field
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
