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

#define SDA 20
#define SCL 21
#define LATCH A5
#define LED 13

//note. Requires 100k divide resistors between GND and PWR to pin A0 
#define VBATPIN A0

#define POWER_GATES_1 9
#define POWER_GATES_2 10

#define CS 8
#define INTERRUPT 3
#define ONE_WIRE 18

RH_RF69 g_rf69(CS,INTERRUPT);      // pins for Adafruit Feather M0 board
Hx711 * g_pScale;
OneWire oneWire(ONE_WIRE);     // pin 10 for DS18b20 temperature sensors
DallasTemperature g_dallasOneWire(&oneWire);

PayloadBeehive g_payload;

const int NUMBER_OF_GATES = 24; // 24 gates, 48 sensors
const int START_GATE = 0;  //useful for testing
const int END_GATE = 24;   //useful for testing
const int DEBEE_BOUNCE = 30;
const int SENDING_DELAY = 60000;  //prints bee counts every 60 seconds
const int NUMBER_OF_BANKS = 6;    // number of switch banks

unsigned long lastOutput = 0;
unsigned long currentTime = 0;

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

// unsigned long lastInTime[numberOfGates];
// unsigned long lastOutTime[numberOfGates];

// unsigned long lastInReadingTimeHigh[numberOfGates];
// unsigned long lastOutReadingTimeHigh[numberOfGates];

// int totalTimeTravelGoingOut[numberOfGates];
// int totalTimeTravelGoingIn[numberOfGates];

// int firstTestInVariable[numberOfGates];
// int firstTestOutVariable[numberOfGates];


byte switchBank[NUMBER_OF_BANKS];
byte oldSwitchBank[NUMBER_OF_BANKS];



unsigned long inTotal = 0;
unsigned long outTotal = 0;


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


void setup() 
{
  Serial.begin(9600);

  pinMode(LED, OUTPUT);    
  Blink(LED, 100, 10);

  delay(500);

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


  g_pScale = new Hx711(SDA, SCL, 22.43f ); // SDA, SCL on Feaather M0 board
  currentTime = millis(); 
  float grams = g_pScale->getGram();
  Serial.print("Scales grams,");
  Serial.print( grams );
  Serial.print(",");
  Serial.print("Scales initialisation time (ms),");
  Serial.print( millis()-currentTime );
  Serial.println();

  // Hx711 scale(SDA, SCL ); // SDA, SCL on Feaather M0 board
  // scale.setOffset( 8886700 );  //with no weight on beehive.
  // scale.setScale( 22.43f );		//calibration_factor = 19.55 for 4 load-cell 200kg rating

  // while (true)
  // {
  //   currentTime = millis(); 
  //   long value = scale.getValue();
  //   Serial.print( value );
  //   Serial.print(",");
  //   Serial.print( millis()-currentTime );
  //   currentTime = millis(); 
  //   Serial.print(",");
  
  //   float grams = scale.getGram();
  //   Serial.print( grams );
  //   Serial.print(",");
  //   Serial.print( millis()-currentTime );
  //   Serial.println();
  // }


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


  g_rf69.send((const uint8_t*) &g_payload, sizeof(g_payload));
  g_rf69.waitPacketSent();

  Serial.print("send time: \t"); Serial.println((millis()-t)); t = millis();
  Serial.print("total time:\t"); Serial.println((millis()-tStart));

  EmonSerial::PrintBeehivePayload(&g_payload);
  Blink(LED, 50, 1);
}
