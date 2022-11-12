//------------------------------------------------------------------------------------------------------------------------------------------------
// Emon_BeehiveMonitor
// Use Adafruit Feather M0 (Adafruit SAMD boards) board configuration
// Beehive monitor project at https://www.instructables.com/Easy-Bee-Counter/
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <EmonShared.h>

//Radiohead RF_69 support
#include <SPI.h>
//#include <RH_RF69.h>
#include <RH_RF95.h>
//load cell support
#include <hx711.h>
//Dallas temperature support
#include <OneWire.h>
#include <DallasTemperature.h>

#define SDA 20
#define SCL 21
#define LATCH A5
#define LED 13
#define SERIAL_FLASH_RX  A5
#define SERIAL_FLASH_TX  6

//note. Requires 100k divide resistors between GND and PWR to pin A0 
#define VBATPIN A0

#define POWER_GATES_1 9
#define POWER_GATES_2 10

#define CS 8
#define INTERRUPT 3
#define ONE_WIRE 18

RH_RF95 g_rf95(CS,INTERRUPT);      // pins for Adafruit Feather M0 board
Hx711 * g_pScale;
OneWire oneWire(ONE_WIRE);     // pin 10 for DS18b20 temperature sensors
DallasTemperature g_dallasOneWire(&oneWire);

PayloadBeehive g_payload;
long g_scaleOffset = 0;

const int NUMBER_OF_GATES = 24; // 24 gates, 48 sensors
const int START_GATE = 0;  //useful for testing
const int END_GATE = 24;   //useful for testing
const int DEBEE_BOUNCE = 30;
const int SENDING_DELAY = 60000;  //prints bee counts every 60 seconds
const int NUMBER_OF_BANKS = 6;    // number of switch banks
const int STORE_TO_SSD_DELAY = 60; //Store totals to SRAM every 60 SENDING_DELAYs. 

unsigned long lastOutput = 0;
unsigned long currentTime = 0;
unsigned long lastStoreToSRAM = 0;

//boolean 0 or 1 sensor readings, 1 bee is present
boolean inSensorReading[NUMBER_OF_GATES];
boolean outSensorReading[NUMBER_OF_GATES];

boolean lastInSensorReading[NUMBER_OF_GATES];
boolean lastOutSensorReading[NUMBER_OF_GATES];

boolean checkStateIn[NUMBER_OF_GATES];
boolean checkStateOut[NUMBER_OF_GATES];

int inCount[NUMBER_OF_GATES];
int outCount[NUMBER_OF_GATES];
  
unsigned long startInReadingTime[NUMBER_OF_GATES];
unsigned long startOutReadingTime[NUMBER_OF_GATES];

unsigned long inSensorTime[NUMBER_OF_GATES];
unsigned long outSensorTime[NUMBER_OF_GATES];
 
unsigned long lastInFinishedTime[NUMBER_OF_GATES];
unsigned long lastOutFinishedTime[NUMBER_OF_GATES];
  
unsigned long inReadingTimeHigh[NUMBER_OF_GATES];
unsigned long outReadingTimeHigh[NUMBER_OF_GATES];

byte switchBank[NUMBER_OF_BANKS];
byte oldSwitchBank[NUMBER_OF_BANKS];

unsigned long inTotal = 0;
unsigned long outTotal = 0;

///////////////////////////////////////////////////////////
// SAMD UART support
// See https://learn.adafruit.com/using-atsamd21-sercom-to-add-more-spi-i2c-serial-ports/overview
// Note: You need to comment Serial5 definition and SERCOM5_Handler in 
//       AppData\Local\Arduino15\packages\adafruit\hardware\samd\1.7.5\variants\feather_m0\variant.cpp

#include "wiring_private.h" // pinPeripheral() function

Uart Serial5 (&sercom5, SERIAL_FLASH_RX, SERIAL_FLASH_TX, SERCOM_RX_PAD_0, UART_TX_PAD_2);
void SERCOM5_Handler()
{
  Serial5.IrqHandler();
}
///////////////////////////////////////////////////////////


void printAddress(uint8_t deviceAddress[8])
{
	Serial.print("{ ");
	for (uint8_t i = 0; i < 8; i++)
	{
		// zero pad the address if necessary
		Serial.print("0x");
		if (deviceAddress[i] < 16) Serial.print("0");
		Serial.print(deviceAddress[i], HEX);
		if (i < 7) 
      Serial.print(", ");
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


bool ReadSettingsFromFlash(byte &subnode, unsigned long& beesIn, unsigned long& beesOut, long &scaleOffset ) 
{
  uint16_t timeout = millis();
  char currentSetting = '\0';
  bool negative = false;
  bool completed = false;


  Serial5.println("r");   //request saved settings
  while( !completed && millis()-timeout < 2000 )
  {
    if( Serial5.available())
    {
      char c = Serial5.read();
      //Serial.print(c);
      if ('0' <= c && c <= '9') 
      {
          unsigned long digit = c - '0';
          
          switch( currentSetting )
          {
              case 'n':  //subnode
                  subnode = subnode *10 + digit;
                  break;
              case 'i':  //beesIn
                  beesIn = beesIn * 10 + digit;
                  break;
              case 'o':  //beesOut
                  beesOut = beesOut *10 + digit;
                  break;
              case 'g':  //grams Tare
                  scaleOffset = scaleOffset *10 + digit;
                  break;
              default:
                  break;
          }
          continue;
      }
      
      if (c == '-')
      {
          negative = true;
          continue;
      }

      if (c == '\n')
      {
          if( currentSetting == 'g' )
          {
            if( negative )
            {
                scaleOffset = -1*scaleOffset;
            }   
            completed = true;  //g is the last settings sent from flash
          }
          currentSetting == '\0';
          negative = false;
          continue;
      }

      switch(c)
      {
          case 'n':
              subnode = 0;
              currentSetting = c;
              break;
          case 'i':
              beesIn = 0;
              currentSetting = c;
              break;
          case 'o':
              beesOut = 0;
              currentSetting = c;
              break;
          case 'g':
              scaleOffset = 0;
              currentSetting = c;
              break;
          default:
              break;
      }
    }
  }
  
  return completed;
}

void ResetFlashSettings(long scaleOffset)
{
  char sendStr[40];

//Serial5.println("n0");
  Serial5.println("i0");
  Serial5.println("o0");
  sprintf(sendStr, "g%ld", scaleOffset);
  Serial5.println(sendStr);
}


void setup() 
{

  pinMode(LED, OUTPUT);    
  Blink(LED, 100, 10);

  delay(1000);

  Serial.begin(9600);
	EmonSerial::PrintBeehivePayload(NULL);

  //initialise payload fields
  g_payload.relay = 0;
  g_payload.subnode = 0;
  g_payload.beesIn = 0;
  g_payload.beesOut = 0;
  g_payload.grams = 0;
  g_payload.beeInRate = 0;
  g_payload.beeOutRate = 0;
  g_payload.supplyV = 0;

  //Configure UART5 to read from ATTiny85 beehiveState
  Serial5.begin(9600);

  // Assign pins for SERCOM functionality
  pinPeripheral(SERIAL_FLASH_RX, PIO_SERCOM_ALT);
  pinPeripheral(SERIAL_FLASH_TX, PIO_SERCOM);


  //Initialise the ATTiny85 settings. Uncomment to initialise before installation
  //Serial5.println("g8967043");
  //Serial5.println("i0");
  //Serial5.println("o0");
  //Serial5.println("n0");
  //Read the settings from ATTiny flash, if available.
  //Note. Very strang bug where passing g_payload.beesIn as a reference crashes MCU when assigning a value. 
  //Most likely because of pack(1) on PayloadBeehive struct
  unsigned long beesIn, beesOut;
  if( ReadSettingsFromFlash(g_payload.subnode, beesIn, beesOut, g_scaleOffset) )
  {
    g_payload.beesIn = beesIn;
    g_payload.beesOut = beesOut;
    Serial.print("Settings read from flash:");
    Serial.print("Subnode="); Serial.print(g_payload.subnode);
    Serial.print(",BeesIn="); Serial.print(g_payload.beesIn);
    Serial.print(",BeesOut="); Serial.print(g_payload.beesOut);
    Serial.print(",ScaleOffset="); Serial.print(g_scaleOffset);
    Serial.println();
  }
  else
  {
    Serial.println("Failed reading settings from flash");
  }

  g_pScale = new Hx711(SDA, SCL, 22.43f ); // SDA, SCL on Feather M0 board  //calibration_factor = 22.43f for 4 load-cell 200kg rating
  long offset = g_pScale->averageValue();
  Serial.print("Scale offset reading "); Serial.println(offset);

  g_pScale->setOffset(g_scaleOffset);

  currentTime = millis(); 
  float grams = g_pScale->getGram();
  Serial.print("Scales grams,");
  Serial.print( grams );
  Serial.print(",");
  Serial.print("Scales initialisation time (ms),");
  Serial.print( millis()-currentTime );
  Serial.println();

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

  pinMode(CS, OUTPUT);
  digitalWrite(CS, HIGH);

  //Initialise the IR gates
  SPI.begin();
  SPI.beginTransaction(SPISettings(3000000, MSBFIRST, SPI_MODE2));
  
  Serial.println ("Begin bee counter.");
  pinMode (LATCH, OUTPUT);
  digitalWrite (LATCH, HIGH);

  pinMode (POWER_GATES_1, OUTPUT);
  pinMode (POWER_GATES_2, OUTPUT);

  digitalWrite(POWER_GATES_1, HIGH);
  digitalWrite(POWER_GATES_2, HIGH);
  delayMicroseconds(75); //first 24 gates only need 15us while gates closer to the end need ~40us-75us
  
  digitalWrite (LATCH, LOW);    // pulse the parallel load latch
  delayMicroseconds(3);
  digitalWrite (LATCH, HIGH);
  delayMicroseconds(3);
  
  digitalWrite(POWER_GATES_1, LOW);
  digitalWrite(POWER_GATES_2, LOW);

  //initialise the switchbank
  for(int i =0; i < NUMBER_OF_BANKS;i++)
  {
    oldSwitchBank[i] = SPI.transfer (0);
  }

  for (int i = START_GATE; i < END_GATE; i++) 
  { 
    lastInSensorReading[i] = 0;
    lastOutSensorReading[i] = 0;
    inSensorReading[i] = 0;
    outSensorReading[i] = 0;
    lastInSensorReading[i] = 0;
    lastOutSensorReading[i] = 0;
    checkStateIn[i] = 1;
    checkStateOut[i] = 1;    
  }

  if (!g_rf95.init())
    Serial.println("g_rf95 init failed");
  // Defaults after init are 434.0MHz, modulation GFSK_Rb250Fd250, +13dbM (for low power module)
  // No encryption
  if (!g_rf95.setFrequency(915.0))
    Serial.println("setFrequency failed");
  g_rf95.setHeaderId(BEEHIVEMONITOR_NODE);

  // If you are using a high power g_rf69 eg RFM69HW, you *must* set a Tx power with the
  // ishighpowermodule flag set like this:
  //g_rf95.setTxPower(20, true);

  // The encryption key has to be the same as the one in the client
  // uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
  //                   0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
  // g_rf95.setEncryptionKey(key);
  Serial.println("Initialisation complete");
}


void loop ()
{
  currentTime = millis();  
  
  digitalWrite(POWER_GATES_1, HIGH);
  digitalWrite(POWER_GATES_2, HIGH);
  delayMicroseconds(75); //first 24 gates only need 15us while gates closer to the end need ~40us-75us
  
  digitalWrite (LATCH, LOW);    // pulse the parallel load latch
  delayMicroseconds(3);
  digitalWrite (LATCH, HIGH);
  delayMicroseconds(3);
  
  digitalWrite(POWER_GATES_1, LOW);
  digitalWrite(POWER_GATES_2, LOW);

  //Reading 24 bits at 1Mhz should take about 24 microseconds,
  //reading 24 bits at 3Mhz should take about 8us
  //reading 48 bits at 3Mhz should take abotu 16us
  bool change = false;
  for(int i =0; i < NUMBER_OF_BANKS;i++)
  {
    switchBank[i] = SPI.transfer (0);
    if( switchBank[i] != oldSwitchBank[i])
      change = true;
  }

  if( change )
  {
    int gate = 0;
    for(int i =0; i < NUMBER_OF_BANKS;i++)
    {
      for(int j = 0; j < 8; j++)
      {
        if((switchBank[i] >> j) & 1)
          outSensorReading[gate] = HIGH;
        else 
          outSensorReading[gate] = LOW;
        j++;
        if((switchBank[i] >> j) & 1)
          inSensorReading[gate] = HIGH;
        else 
          inSensorReading[gate] = LOW;       
        gate++;  
      }
      oldSwitchBank[i] = switchBank[i];
    }
  }

  for (int i = START_GATE; i < END_GATE; i++) 
  { 
    if(inSensorReading[i] == HIGH || outSensorReading[i] == HIGH) 
    {
      digitalWrite(LED, HIGH);
      break;
    }
    digitalWrite(LED, LOW);
  }

  
  for (int i = START_GATE; i < END_GATE; i++) 
  { 
    if(inSensorReading[i] != lastInSensorReading[i])  //change of state on IN sensor
    { 
      checkStateIn[i] = 0;
      lastInSensorReading[i] = inSensorReading[i];
      inSensorTime[i] = currentTime;
    } 
    if(outSensorReading[i] != lastOutSensorReading[i])  //change of state on OUT sensor
    { 
      checkStateOut[i] = 0;
      lastOutSensorReading[i] = outSensorReading[i];
      outSensorTime[i] = currentTime;
    }       
    if(currentTime - inSensorTime[i] > DEBEE_BOUNCE && checkStateIn[i] == 0)  //debounce IN sensor
    {
      checkStateIn[i] = 1; //passed debounce         
      if(inSensorReading[i] == HIGH) //a bee just entered the sensor
      {
        startInReadingTime[i] = currentTime;
      }
      if(inSensorReading[i] == LOW)  //a bee just exits the sensor; that is, it was HIGH, now it is LOW (empty)
      {  
        lastInFinishedTime[i] = currentTime;            
        inReadingTimeHigh[i] = currentTime - startInReadingTime[i]; //this variable is how long the bee was present for
        Serial.print(i);
        Serial.print(",In ,");
        Serial.print(inReadingTimeHigh[i]);
        if(outReadingTimeHigh[i] < 650 && inReadingTimeHigh[i] < 650)  //should be less than 650ms
        {
          if(currentTime - lastOutFinishedTime[i] < 200) //the sensors are pretty cose together so the time it takes to trigger on and then the other should be small.. ~200ms
          {
            inTotal++;
            Serial.print(",1");
          }
        }
        Serial.println();
      }           
    }
    if(currentTime - outSensorTime[i] > DEBEE_BOUNCE && checkStateOut[i] == 0)  //debounce OUT sensor
    {
      checkStateOut[i] = 1; //passed debounce         
      if(outSensorReading[i] == HIGH) //a bee just entered the sensor
      {
        startOutReadingTime[i] = currentTime;
      }
      if(outSensorReading[i] == LOW)  //a bee just exits the sensor; that is, it was HIGH, now it is LOW (empty)
      {  
        lastOutFinishedTime[i] = currentTime;            
        outReadingTimeHigh[i] = currentTime - startOutReadingTime[i]; //this variable is how long the bee was present for
        Serial.print(i);
        Serial.print(",Out,");
        Serial.print(outReadingTimeHigh[i]);
        if(outReadingTimeHigh[i] < 600 && inReadingTimeHigh[i] < 600) //should be less than 600ms
        {
          if(currentTime - lastInFinishedTime[i] < 200) //the sensors are pretty cose together so this time should be small
          {
            outTotal++;
            Serial.print(",1");
          }
        }
        Serial.println();
      }          
    }        
  }    

  delay (15);   // debounce

  if (currentTime - lastOutput > SENDING_DELAY) 
  {
    sendData(inTotal, outTotal); 
    lastOutput = currentTime; 
    inTotal = 0;
    outTotal = 0; 
  }
}


void sendData(unsigned long beesIn, unsigned long beesOut)
{
  unsigned long tStart, t;
  tStart = t = millis();
  Serial.println("Send data. Reading temperatures");

  g_dallasOneWire.requestTemperatures();
  g_payload.temperatureIn = g_dallasOneWire.getTempCByIndex(0)*100;
  g_payload.temperatureOut = g_dallasOneWire.getTempCByIndex(1)*100;
  Serial.print("temp time: \t"); Serial.println((millis()-t)); t = millis();
 
  g_payload.grams = g_pScale->getGram();
  Serial.print("scale time:\t"); Serial.println((millis()-t)); t = millis();
 
  float measuredvbat = analogRead(VBATPIN);
  measuredvbat *= 2;    // we divided by 2, so multiply back
  measuredvbat *= 3.3;  // Multiply by 3.3V, our reference voltage
  measuredvbat /= 1024; // convert to voltage
  Serial.print("vRead time:\t");  Serial.println((millis()-t)); t = millis();


  g_payload.beeInRate=beesIn/((double)SENDING_DELAY/60000.0);
  g_payload.beeOutRate=beesOut/((double)SENDING_DELAY/60000.0);
  g_payload.beesIn += beesIn;
  g_payload.beesOut += beesOut;
  g_payload.supplyV = (unsigned long) (measuredvbat*1000);  //transmit as mV


  g_rf95.send((const uint8_t*) &g_payload, sizeof(g_payload));
  g_rf95.waitPacketSent();

  Serial.print("send time: \t"); Serial.println((millis()-t)); t = millis();

  //store the latest beesIn and beesOut to Flash on ATTiny85 via serial
  if( ++lastStoreToSRAM >= STORE_TO_SSD_DELAY)
  {
    lastStoreToSRAM = 0;
    char sendStr[40];
    sprintf(sendStr, "i%ld", g_payload.beesIn);
    Serial5.println(sendStr);
    sprintf(sendStr, "o%ld", g_payload.beesOut);
    Serial5.println(sendStr);
    Serial.print("Write Flash time:\t");  Serial.println((millis()-t)); t = millis();
  }
  Serial.print("total time:\t"); Serial.println((millis()-tStart));

  EmonSerial::PrintBeehivePayload(&g_payload);
  Blink(LED, 50, 1);
}
