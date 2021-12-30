//emon_Leaf node for reading the details of the Nissan Leaf ZE0 Dashboard CAN bus and transmitting to emon_Suite
//Dec 2021
#include <CanBusMCP2515_asukiaaa.h>   //See https://github.com/asukiaaa/CanBusMCP2515-arduino
#include <EmonShared.h>
#include <RH_RF69.h>

static const auto QUARTZ_FREQUENCY  = CanBusMCP2515_asukiaaa::QuartzFrequency::MHz8;
static const auto BITRATE           = CanBusMCP2515_asukiaaa::BitRate::Kbps500;
static const auto CS_PIN            = 8;
static const auto SEND_PERIOD       = 1000*5; //5 minutes if no data updates otherwise.
static const auto LED_ACTION_PIN    = 6;

CanBusMCP2515_asukiaaa::Driver canCar(CS_PIN);

CanBusData_asukiaaa::Frame last_0x5B3, last_0x5C5, last_0x5A9;
RH_RF69 g_rf69;

PayloadLeaf payloadLeaf;

void flashError(int error)
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
  CanBusMCP2515_asukiaaa::Settings settings(QUARTZ_FREQUENCY, BITRATE);
  Serial.print("settings for :");Serial.println(can.CS());
  Serial.println(settings.toString());

  while (true) 
  {
    uint16_t errorCode = can.begin(settings);
    if (errorCode == 0) 
    {
      Serial.println("can.begin() success");
      return true;
    } 
    else 
    {
      Serial.print("can.begin() failed: ");
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
  EmonSerial::PrintLeafPayload(NULL);
  if(!initCAN( canCar ))
  {
      flashError(1); //will never return!
  }

	if (!g_rf69.init())
  {
		Serial.println("rf69 init failed");
    flashError(2); //will never return!
  }
	if (!g_rf69.setFrequency(915.0))
  {
    Serial.println("rf69 setFrequency failed");
    flashError(3); //will never return!
  }
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(LEAF_NODE);

	Serial.print("RF69 initialise node: ");
	Serial.print(LEAF_NODE);
	Serial.println(" Freq: 915MHz");
  digitalWrite(LED_ACTION_PIN, LOW);
}

void loop() 
{
  static uint32_t waitingStart = millis();
  bool dataToSend = false;
  
  if (canCar.available()) 
  {
    CanBusData_asukiaaa::Frame frame;
    canCar.receive(&frame);
    if(frame.id == 0x5B3 )        //1459, VCM relayed and processed data to instrument cluster
    {
      payloadLeaf.batteryTemperature = frame.data[0] / 4;   //in 0.25c units
      payloadLeaf.batterySOH = frame.data[1] >> 1;          
      payloadLeaf.batteryWH = (((unsigned long)(frame.data[4] & 0x1))*256  + frame.data[5])*80;   // from GID *80
      payloadLeaf.batteryChargeBars = frame.data[6] >>3;
      if( last_0x5B3.data64 != frame.data64)
      {
        Serial.println(frame.toString());
        dataToSend = true;
        last_0x5B3 = frame;
      }
    }
    else if (frame.id == 0x5C5)   //1477, Instrument cluster -> BCM / AV / VCM
    {
      payloadLeaf.odometer = ((unsigned long)frame.data[1]) *256*256 +  ((unsigned long)frame.data[2]) *256 + frame.data[3];
      if( last_0x5C5.data64 != frame.data64)
      {
        Serial.println(frame.toString());
        dataToSend = true;
        last_0x5C5 = frame;
      }
    }
    else if (frame.id == 0x5A9)   //1449, VCM to instrument cluster
    {
      payloadLeaf.range = (((unsigned long)frame.data[1]) << 4 | frame.data[2] >> 4)/5;
      if( last_0x5A9.data64 != frame.data64)
      {
        Serial.println(frame.toString());
        dataToSend = true;
        last_0x5A9 = frame;
      }      
    }
  }
  
  if( dataToSend || millis() - waitingStart > SEND_PERIOD )
  {   
    waitingStart = millis();

    if( last_0x5A9.data64 != 0 && last_0x5C5.data64 != 0 && last_0x5B3.data64 != 0)
    {
      digitalWrite(LED_ACTION_PIN, HIGH);
      g_rf69.send((const uint8_t*) &payloadLeaf, sizeof (PayloadLeaf));
      if( g_rf69.waitPacketSent() )
      {
        EmonSerial::PrintLeafPayload(&payloadLeaf);
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

