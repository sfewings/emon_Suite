//emon_Leaf node for reading the details of the Nissan Leaf ZE0 Dashboard CAN bus and transmitting to emon_Suite
//Dec 2021
#include <CanBusMCP2515_asukiaaa.h>   //See https://github.com/asukiaaa/CanBusMCP2515-arduino
#include <EmonShared.h>
#include <RH_RF69.h>
#include <SoftwareSerial.h>

static const auto CS_PIN            = 5;
static const auto LED_ACTION_PIN    = 6;
static const uint32_t SEND_PERIOD         = 1000*30;//30 seconds if no data updates otherwise.
static const uint32_t DEBUG_TIME_INTERVAL = 1000; //Limit the debug print of each message

static const int ALL_MESSAGE_IDs[] = {0x5B3, 0x5C5, 0x5A9, 0x5B9, 0x5BF, 0x5BC};
static const int EV_CAN_IDs[] = {0x5B9, 0x5BF,0x5BC};
static const int NUM_MESSAGES = sizeof(ALL_MESSAGE_IDs)/sizeof(ALL_MESSAGE_IDs[0]);
static const int NUM_EV_MESSAGES = sizeof(EV_CAN_IDs)/sizeof(EV_CAN_IDs[0]);

static unsigned long lastDebugTime[NUM_MESSAGES];
CanBusData_asukiaaa::Frame lastMessage[NUM_MESSAGES];

RH_RF69         g_rf69;
PayloadLeaf     g_payloadLeaf;
SoftwareSerial  g_serial(3, 4);
CanBusMCP2515_asukiaaa::Driver g_canCar(CS_PIN);

void flashErrorToLED(int error)
{
  while( true)
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

  g_serial.begin(115200);
  g_serial.listen();

  for(int i=0; i<NUM_MESSAGES; i++)
  {
    lastDebugTime[i] = millis();
  }

  EmonSerial::PrintLeafPayload(NULL);
  if(!initCAN( g_canCar ))
  {
      flashErrorToLED(1); //will never return!
  }

	if (!g_rf69.init())
  {
		Serial.println(F("rf69 init failed"));
    flashErrorToLED(2); //will never return!
  }
	if (!g_rf69.setFrequency(915.0))
  {
    Serial.println(F("rf69 setFrequency failed"));
    flashErrorToLED(3); //will never return!
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
}


void writeSerial(CanBusData_asukiaaa::Frame& frame)
{
  int frameSize = sizeof(frame);
  char* frameData = (char*)&frame;
  for(int i=0; i<frameSize; i++)
  {
    g_serial.write(frameData[i]);
  }
}

bool readSerial(CanBusData_asukiaaa::Frame& frame)
{
  int frameSize = sizeof(frame);
  int frameIndex = 0;
  char* frameData = (char*)&frame;
  while( g_serial.available() > 0 && frameIndex < frameSize)
  {
    frameData[frameIndex] = g_serial.read();
    frameIndex++;
  }
  return frameSize == frameIndex;
}

void printFrame(CanBusData_asukiaaa::Frame& frame, bool fromCAN)
{
  Serial.print(F("Frame: "));
  Serial.print(fromCAN ? F("CAN   ") : F("Serial"));
  Serial.print(F(" id: "));
  Serial.print(frame.id, HEX);
  Serial.print(F(" ext: "));
  Serial.print(frame.ext);
  Serial.print(F(" len: "));
  Serial.print(frame.len);
  Serial.print(F(" data: "));
  for(int i=0; i<frame.len; i++)
  {
    Serial.print(frame.data[i]);
    Serial.print(F(" "));
  }
  Serial.println();
}

bool isEVmessage(CanBusData_asukiaaa::Frame& frame)
{
  for(int i=0;i < NUM_EV_MESSAGES; i++)
  {
    if(EV_CAN_IDs[i] == frame.id)
    {
      return true;
    }
  }
  return false;
}

//returns true if any of the 
bool processFrame(CanBusData_asukiaaa::Frame& frame)
{
  if(frame.id == 0x5B3 )        //1459, VCM relayed and processed data to instrument cluster
  {
  //  Note: These are all populated from the EV bus from message 0x5BC. Temperature seems different if populated from each.
  //  payloadLeaf.batteryTemperature = frame.data[0] / 4;   //in 0.25c units
  //  payloadLeaf.batterySOH = frame.data[1] >> 1;          
  //  payloadLeaf.batteryWH = (((unsigned long)(frame.data[4] & 0x1))*256  + frame.data[5])*80;   // from GID *80
  //  payloadLeaf.batteryChargeBars = frame.data[6] >>3;
    return true;
  }
  else if (frame.id == 0x5C5)   //1477, Instrument cluster -> BCM / AV / VCM
  {
    unsigned long odometer = ((unsigned long)frame.data[1]) *256*256 +  ((unsigned long)frame.data[2]) *256 + frame.data[3];
    if( odometer != g_payloadLeaf.odometer)
    {
      g_payloadLeaf.odometer = odometer;
      return true;
    }
  }
  else if (frame.id == 0x5A9)   //1449, VCM to instrument cluster
  {
    if(frame.data[0] != 0xFF && frame.data[1] != 0xFF)   // 0xFF while charging
    {
      short range = (((unsigned long)frame.data[1]) << 4 | frame.data[2] >> 4)/5;
      if( g_payloadLeaf.range != range)
      {
        g_payloadLeaf.range = range;
        return true;
      }
    }
  }
  //EV bus
  else if( frame.id == 0x5B9 )
  {
    //EV Bus : charge minutes remaining
    unsigned long chargeMinutesRemaining = (((unsigned long)(frame.data[0] & 0x7))<<8) + (unsigned long)(frame.data[1]);
  }
  else if( frame.id == 0x5BF )
  {
    //EV Bus : Charging status
  }
  else if( frame.id == 0x5BC )
  {
    //EV Bus : remaining capacity, SOH, Charge bars, battery temperature
    unsigned long batteryWH = ((((unsigned long)(frame.data[0]))<<2)  + (((unsigned long)frame.data[1])>>6))*80;   // from GID *80
    unsigned long LB_Remaining_Capaci_Segment_Switch = frame.data[4] & 0x1;
    byte batteryChargeBars = frame.data[2] & 0xf;
    byte batterySOH = frame.data[4] >> 1;
    byte batteryTemperature = frame.data[3]-40;

    if( g_payloadLeaf.batteryWH != batteryWH ||
        (LB_Remaining_Capaci_Segment_Switch == 0 && g_payloadLeaf.batteryChargeBars != batteryChargeBars) ||
        g_payloadLeaf.batterySOH != batterySOH ||
        g_payloadLeaf.batteryTemperature != batteryTemperature)
    {
      g_payloadLeaf.batteryWH = batteryWH;
      if( LB_Remaining_Capaci_Segment_Switch == 0 )
      {
        g_payloadLeaf.batteryChargeBars = batteryChargeBars;
      }
      g_payloadLeaf.batterySOH = batterySOH;
      g_payloadLeaf.batteryTemperature = batteryTemperature;
      return true;
    }
  }

  return false;
}

void loop() 
{
  static uint32_t waitingStart = millis();
  static bool isEV_CAN_unit = false;
  bool dataToTransmit = false;

  CanBusData_asukiaaa::Frame frame;
  
  if ( g_canCar.available()) 
  {
    g_canCar.receive(&frame);
    int index = -1;
    for(int i=0;i < NUM_MESSAGES; i++)
    {
      if(ALL_MESSAGE_IDs[i] == frame.id)
      {
        index = i;
        break;
      }
    }

    //debug print the message
    if(index != -1)
    {
      if( millis() - DEBUG_TIME_INTERVAL > lastDebugTime[index] ) 
      {
        lastDebugTime[index] = millis();
        printFrame(frame, true);
      }
    }

    // try processing the frame if it is different from the last received frame
    if(index >= 0 && frame.data64 != lastMessage[index].data64 )
    {
      lastMessage[index] = frame;

      if( processFrame(frame) )
      {
        dataToTransmit = true;
      }

      if (isEVmessage(frame))
      {
        //only send EV messages to VCM by serial. 
        //Note SoftwareSerial is half duplex! Sending both ways stops the receive buffer!
        isEV_CAN_unit = true;
        writeSerial(frame);
      }
    }
  }

  if( g_serial.available() > 0)
  {
    if( readSerial(frame) && processFrame(frame) )
    {
      printFrame(frame, false);
      dataToTransmit = true;
    }
  }

  //are we ready to transmit the packet?
  if( (dataToTransmit || millis() - waitingStart > SEND_PERIOD) &&
      (g_payloadLeaf.odometer != 0 || isEV_CAN_unit) )  //don't send till we have at least filled the odometer field
  {   
    //Serial.print(F("waitingStart:")); Serial.println(millis()-waitingStart);
    waitingStart = millis();
    digitalWrite(LED_ACTION_PIN, HIGH);

    if(isEV_CAN_unit)
    {
      //We Don't transmit from the EV unit. Only from the VCM unit! EV unit messages are sent to VCM unit by serial.
      EmonSerial::PrintLeafPayload(&g_payloadLeaf);
    }
    else
    {
      g_rf69.send((const uint8_t*) &g_payloadLeaf, sizeof (PayloadLeaf));
      if( g_rf69.waitPacketSent() )
      {
        EmonSerial::PrintLeafPayload(&g_payloadLeaf);
      }
      else
      {
        Serial.println(F("No packet sent"));
      }
    }      

    delay(10);
    digitalWrite(LED_ACTION_PIN, LOW);
  }    
  delay(1);
}

