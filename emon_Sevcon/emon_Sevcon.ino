//emon_Sevcon node for reading the details of the Thunderstruck sevcon motor controller CAN bus and transmitting to emon_Suite
//Dec 2021
#include <CanBusMCP2515_asukiaaa.h>   //See https://github.com/asukiaaa/CanBusMCP2515-arduino
#include <EmonShared.h>
#include <RH_RF69.h>
#include <SoftwareSerial.h>

static const auto CS_PIN                  = 5;
static const auto LED_ACTION_PIN          = 9;
static const uint32_t SEND_PERIOD         = 1000*30;//30 seconds if no data updates otherwise.
static const uint32_t DEBUG_TIME_INTERVAL = 1000; //Limit the debug print of each message

static const int ALL_MESSAGE_IDs[]        = { 0x411, 0x454, 0x271}; //{0x80 = sync, 0x701 = heartbeat, 0x391 = not used, 0x330 = not used 
static const int NUM_MESSAGES             = sizeof(ALL_MESSAGE_IDs)/sizeof(ALL_MESSAGE_IDs[1]);

static unsigned long        lastDebugTime[NUM_MESSAGES];
CanBusData_asukiaaa::Frame  lastMessage[NUM_MESSAGES];

#define NETWORK_FREQUENCY 914.0   //as used on the boat

RH_RF69         g_rf69;
PayloadSevCon     g_payloadSevCon;
CanBusMCP2515_asukiaaa::Driver g_CAN(CS_PIN);

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
//  Serial.print(F("settings for :"));Serial.println(can.CS());
//  Serial.println(settings.toString());

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

  delay(500);
 	Serial.println(F("SevCon CAN decode"));

  for(int i=0; i<NUM_MESSAGES; i++)
  {
    lastDebugTime[i] = millis();
  }

  memset(&g_payloadSevCon, sizeof(PayloadSevCon), 0);
  if(!initCAN( g_CAN ))
  {
      flashErrorToLED(1); //will never return!
  }

	if (!g_rf69.init())
  {
		Serial.println(F("rf69 init failed"));
    flashErrorToLED(2); //will never return!
  }
	if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
  {
    Serial.println(F("rf69 setFrequency failed"));
    flashErrorToLED(3); //will never return!
  }
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(SEVCON_CAN_NODE);

	Serial.print(F("RF69 initialise node: "));
	Serial.print(SEVCON_CAN_NODE);
	Serial.print(" Freq: ");Serial.print(NETWORK_FREQUENCY,1); Serial.println("MHz");
  digitalWrite(LED_ACTION_PIN, LOW);

  EmonSerial::PrintSevConPayload(NULL);
}


void printFrame(CanBusData_asukiaaa::Frame& frame)
{
  Serial.print(F("id:"));
  Serial.print(frame.id, HEX);
  Serial.print(F(",ext:"));
  Serial.print(frame.ext);
  Serial.print(F(",len:"));
  Serial.print(frame.len);
  Serial.print(F(",data:"));
  for(int i=0; i<frame.len; i++)
  {
    Serial.print(frame.data[i], HEX);
    Serial.print(F(" "));
  }
  Serial.println();
}

//returns true if any of the elements of the payload packet have changed
bool processFrame(CanBusData_asukiaaa::Frame& frame, PayloadSevCon& sevConPayload)
{
  printFrame(frame);

  if(frame.id == 0x411 )        // RxPDO3, device 17
  {
    int8_t motorTemperature = (int8_t) frame.data[6];
    
    Serial.print(motorTemperature); Serial.print(":"); Serial.println(sevConPayload.motorTemperature);
    
    if( motorTemperature != sevConPayload.motorTemperature)
    {
      sevConPayload.motorTemperature = motorTemperature;
      return true;
    }
  }
  else 
  if (frame.id == 0x454)        //Receive PDO 3, device 84
  {
    int16_t rpm = (int16_t)(((uint16_t)(frame.data[2])<<8) | (uint16_t)frame.data[1]);
    rpm *= -1;    //our wag stick is reversed!
    if( rpm != sevConPayload.rpm )
    {
      sevConPayload.rpm = rpm;
      return true;
    }

  }
  else if (frame.id == 0x271 )   //Receive PDO 1, device 113 
  {
    // Serial.println(frame.data[6],16);
    // Serial.println((uint16_t)frame.data[6]);
    // Serial.println(((uint16_t)frame.data[6])<<8);
    // Serial.println((((uint16_t)frame.data[6])<<8) + (uint16_t)frame.data[5]);
    // Serial.println((float)((((uint16_t)frame.data[6])<<8) + (uint16_t)frame.data[5]));
    // Serial.println(((float)((((uint16_t)frame.data[6])<<8) + (uint16_t)frame.data[5]))/16.0);

    float capVoltage = ( (float)((((uint16_t) frame.data[1])<<8) | (uint16_t)frame.data[0]))/16.0; 
    int8_t controllerTemperature = (int8_t) frame.data[2];
    float batteryCurrent = ( (float)((int16_t)((((uint16_t) frame.data[6])<<8) | (uint16_t)frame.data[5])))/16.0;

    // Serial.print(capVoltage); Serial.print(":"); Serial.println(sevConPayload.capVoltage);
    // Serial.print(controllerTemperature); Serial.print(":"); Serial.println(sevConPayload.controllerTemperature);
    // Serial.print(batteryCurrent); Serial.print(":"); Serial.println(sevConPayload.batteryCurrent);
 
    if(capVoltage != sevConPayload.capVoltage || 
       controllerTemperature != sevConPayload.controllerTemperature ||
       batteryCurrent != sevConPayload.batteryCurrent)
    {
        sevConPayload.capVoltage = capVoltage;
        sevConPayload.controllerTemperature = controllerTemperature;
        sevConPayload.batteryCurrent = batteryCurrent;
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
//   digitalWrite(LED_ACTION_PIN, HIGH);
    
    g_CAN.receive(&frame);
    // printFrame(frame);
    // delay(3);



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
      }
    }

    // try processing the frame if it is different from the last received frame
    if(index >= 0 && frame.data64 != lastMessage[index].data64)
    {
      lastMessage[index] = frame;

      if( processFrame(frame, g_payloadSevCon) )
      {
        dataToTransmit = true;
      }
    }
  }

  //are we ready to transmit the packet?
  if( (dataToTransmit || millis() - waitingStart > SEND_PERIOD) )
  {   
    waitingStart = millis();
    digitalWrite(LED_ACTION_PIN, HIGH);

    g_rf69.send((const uint8_t*) &g_payloadSevCon, sizeof (PayloadSevCon));
    if( g_rf69.waitPacketSent() )
    {
      EmonSerial::PrintSevConPayload(&g_payloadSevCon);
    }
    else
    {
      Serial.println(F("No packet sent"));
    }

    delay(10);
  }    

  digitalWrite(LED_ACTION_PIN, LOW);
}

