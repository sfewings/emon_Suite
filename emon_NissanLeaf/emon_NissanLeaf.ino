#include <CanBusMCP2515_asukiaaa.h>
//See https://github.com/asukiaaa/CanBusMCP2515-arduino

#include <EmonShared.h>

static const auto QUARTZ_FREQUENCY  = CanBusMCP2515_asukiaaa::QuartzFrequency::MHz8;
static const auto BITRATE           = CanBusMCP2515_asukiaaa::BitRate::Kbps500;
static const auto CS_PIN            = 8;
CanBusMCP2515_asukiaaa::Driver canCar(CS_PIN); //(9);
//CanBusMCP2515_asukiaaa::Driver canEV(8);

CanBusData_asukiaaa::Frame last_0x5B3, last_0x5C5, last_0x5A9;


typedef struct PayloadLeaf : PayloadRelay {
	byte subnode;                           // 
	unsigned long   odometer;
  short  range;                //NL range in 0.2 kilometers
  byte   batteryTemperature;
  byte   batterySOH;           //Battery state of health %
  unsigned long batteryWH;     //WH in battery
  byte   batteryChargeBars;    //Battery available charge bars
} PayloadLeaf;

PayloadLeaf payloadLeaf;

bool initCAN(CanBusMCP2515_asukiaaa::Driver& can)
{
  CanBusMCP2515_asukiaaa::Settings settings(QUARTZ_FREQUENCY, BITRATE);
  Serial.print("settings for :");Serial.println(can.CS());
  Serial.println(settings.toString());

  while (true) 
  {
    uint16_t errorCode = can.begin(settings);
    if (errorCode == 0) {
      Serial.println("can.begin() success");
      return true;
    } 
    else 
    {
      Serial.print("can.begin() failed: ");
      Serial.println(errorCode);
      Serial.println(CanBusMCP2515_asukiaaa::Error::toString(errorCode));
      delay(1000);
      //will never return!
    }
 }
}


void PrintLeafPayload(PayloadLeaf* pPayloadLeaf)
{
	PrintLeafPayload(Serial, pPayloadLeaf);
}

void PrintLeafPayload(Stream& stream, PayloadLeaf* pPayloadLeaf)
{
	if (pPayloadLeaf == NULL)
	{
		stream.print(F("leaf,subnode,odometer,range,batteryTemperature,batterySOH,batteryWH,batteryChargeBars"));
	}
	else
	{
		stream.print(F("leaf,"));
		stream.print(pPayloadLeaf->subnode);
		stream.print(F(","));
		stream.print(pPayloadLeaf->odometer);
		stream.print(F(","));
		stream.print(pPayloadLeaf->range);
		stream.print(F(","));    
		stream.print(pPayloadLeaf->batteryTemperature);
		stream.print(F(","));
		stream.print(pPayloadLeaf->batterySOH);
		stream.print(F(","));
		stream.print(pPayloadLeaf->batteryWH);
		stream.print(F(","));
		stream.print(pPayloadLeaf->batteryChargeBars);

		//PrintRelay(stream, pPayloadBeehive);
	}
	stream.println();
}

void setup() 
{
  Serial.begin(115200);

  initCAN( canCar );
  PrintLeafPayload(NULL);
 // initCAN( canEV );
}

void loop() 
{
  static uint32_t waitingStart = millis();
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
        PrintLeafPayload(Serial, &payloadLeaf);
        last_0x5B3 = frame;
      }
    }
    else if (frame.id == 0x5C5)   //1477, Instrument cluster -> BCM / AV / VCM
    {
      payloadLeaf.odometer = ((unsigned long)frame.data[1]) *256*256 +  ((unsigned long)frame.data[2]) *256 + frame.data[3];
      if( last_0x5C5.data64 != frame.data64)
      {
        Serial.println(frame.toString());
        PrintLeafPayload(Serial, &payloadLeaf);
        last_0x5C5 = frame;
      }
    }
    else if (frame.id == 0x5A9)   //1449, VCM to instrument cluster
    {
      payloadLeaf.range = (((unsigned long)frame.data[1]) << 4 | frame.data[2] >> 4)/5;
      if( last_0x5A9.data64 != frame.data64)
      {
        Serial.println(frame.toString());
        PrintLeafPayload(Serial, &payloadLeaf);
        last_0x5A9 = frame;
      }      
    }
    // else
    // {
    //   Serial.print("canCar:");
    //   Serial.print(frame.id,HEX);
    //   Serial.print(",");
    //   Serial.println(frame.toString());
    // }
  }

  if(millis() - waitingStart > 1000)
  {
    //PrintLeafPayload(Serial, &payloadLeaf);
    waitingStart = millis();
  }
  delay(1);
}

