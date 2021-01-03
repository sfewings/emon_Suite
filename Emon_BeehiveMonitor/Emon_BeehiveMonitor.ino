//------------------------------------------------------------------------------------------------------------------------------------------------
// Emon_BeehiveMonitor
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <EmonShared.h>
#include <EmonEEPROM.h>

//Radiohead RF_69 support
#include <SPI.h>
#include <RH_RF69.h>
//load cell support
#include <hx711.h>
//Dallas temperature support
#include <OneWire.h>
#include <DallasTemperature.h>

#define LED 13
#define VBATPIN A7  //A7 is also D9
   

RH_RF69 g_rf69(8,3);      // pins for Adafruit Feather M0 board
Hx711 g_scale(20, 21);  // SDA, SCL on Feaather M0 board
OneWire oneWire(10);     // pin 10 for DS18b20 temperature sensors
DallasTemperature g_dallasOneWire(&oneWire);

PayloadBeehive g_payload;

void printAddress(uint8_t deviceAddress[8])
{
	Serial.print("{ ");
	for (uint8_t i = 0; i < 8; i++)
	{
		// zero pad the address if necessary
		Serial.print("0x");
		if (deviceAddress[i] < 16) Serial.print("0");
		Serial.print(deviceAddress[i], HEX);
		if (i < 7) Serial.print(", ");

	}
	Serial.print(" }");
}


void Blink(byte PIN, byte DELAY_MS, byte loops) 
{
  for (byte i=0; i<loops; i++)  
  {
    digitalWrite(PIN,HIGH);
    delay(DELAY_MS);
    digitalWrite(PIN,LOW);
    delay(DELAY_MS);
  }
}


void setup() 
{
  Blink(LED, 50, 3);
  Serial.begin(9600);
 // while (!Serial) 
 //   ;
  delay(500);
  Blink(LED, 50, 3);

 	EmonSerial::PrintBeehivePayload(NULL);

  pinMode(LED, OUTPUT);     

  if (!g_rf69.init())
    Serial.println("g_rf69 init failed");
  // Defaults after init are 434.0MHz, modulation GFSK_Rb250Fd250, +13dbM (for low power module)
  // No encryption
  if (!g_rf69.setFrequency(915.0))
    Serial.println("setFrequency failed");
  g_rf69.setHeaderId(BEEHIVEMONITOR_NODE);

  // If you are using a high power g_rf69 eg RFM69HW, you *must* set a Tx power with the
  // ishighpowermodule flag set like this:
  g_rf69.setTxPower(14, true);

  // The encryption key has to be the same as the one in the client
  uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
  g_rf69.setEncryptionKey(key);
  

	g_scale.setScale(-22.43f);		//calibration_factor = 19.55 for 4 load-cell 200kg rating
  
	g_dallasOneWire.begin();
	long 	numberOfSensors = g_dallasOneWire.getDeviceCount();
  for(int i =0; i < numberOfSensors;i++)
  {
    uint8_t tmp_address[8];
    g_dallasOneWire.getAddress(tmp_address, i);
    Serial.print(F("Sensor address "));
    Serial.print(i + 1);
    Serial.print(F(": "));
    printAddress(tmp_address);
    Serial.println();
	}
}

void loop()
{
  //Serial.print("Value: ");Serial.println(g_scale.getValue());
  //Serial.print("grams: ");Serial.println(g_scale.getGram());

   g_payload.grams = g_scale.getGram();

  g_dallasOneWire.requestTemperatures();
  g_payload.temperatureIn = g_dallasOneWire.getTempCByIndex(0)*100;
  g_payload.temperatureOut = g_dallasOneWire.getTempCByIndex(1)*100;

  g_payload.beeInRate=10;
  g_payload.beeOutRate=20;
  g_payload.beesIn ++;
  g_payload.beesOut ++;

  float measuredvbat = analogRead(VBATPIN);
  measuredvbat *= 2;    // we divided by 2, so multiply back
  measuredvbat *= 3.3;  // Multiply by 3.3V, our reference voltage
  measuredvbat /= 1024; // convert to voltage
  Serial.print("VBat: " ); Serial.println(measuredvbat);
  g_payload.supplyV = (unsigned long) (measuredvbat*1000);  //transmit as mV

  g_rf69.send((const uint8_t*) &g_payload, sizeof(g_payload));
  Blink(LED, 50, 1);
  g_rf69.waitPacketSent();

  EmonSerial::PrintBeehivePayload(&g_payload);

  delay(100);
}
