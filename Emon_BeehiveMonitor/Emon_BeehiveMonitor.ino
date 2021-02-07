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
//Hx711 g_scale(SDA, SCL ); // SDA, SCL on Feaather M0 board
OneWire oneWire(ONE_WIRE);     // pin 10 for DS18b20 temperature sensors
DallasTemperature g_dallasOneWire(&oneWire);

PayloadBeehive g_payload;


const int numberOfGates = 24; // 24 gates, 48 sensors
const int startGate = 0;  //useful for testing
const int endGate = 24;   //useful for testing
const int debeebounce = 30;
const int outputDelay = 15000;  //prints bee counts every 15 seconds
const int numberOfBanks = 6;    // number of switch banks
unsigned long lastOutput = 0;
unsigned long currentTime = 0;


//boolean 0 or 1 sensor readings, 1 bee is present
boolean inSensorReading[numberOfGates];
boolean outSensorReading[numberOfGates];

boolean lastInSensorReading[numberOfGates];
boolean lastOutSensorReading[numberOfGates];

boolean checkStateIn[numberOfGates];
boolean checkStateOut[numberOfGates];

int inCount[numberOfGates];
int outCount[numberOfGates];
  
unsigned long startInReadingTime[numberOfGates];
unsigned long startOutReadingTime[numberOfGates];

unsigned long inSensorTime[numberOfGates];
unsigned long outSensorTime[numberOfGates];
 
unsigned long lastInFinishedTime[numberOfGates];
unsigned long lastOutFinishedTime[numberOfGates];
  
unsigned long inReadingTimeHigh[numberOfGates];
unsigned long outReadingTimeHigh[numberOfGates];

unsigned long lastInTime[numberOfGates];
unsigned long lastOutTime[numberOfGates];

unsigned long lastInReadingTimeHigh[numberOfGates];
unsigned long lastOutReadingTimeHigh[numberOfGates];

int totalTimeTravelGoingOut[numberOfGates];
int totalTimeTravelGoingIn[numberOfGates];

int firstTestInVariable[numberOfGates];


int firstTestOutVariable[numberOfGates];


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
  pinMode(LED, OUTPUT);    

  Blink(LED, 50, 3);

  Serial.begin(9600);
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


  //g_scale.setScale(-22.43f);		//calibration_factor = 19.55 for 4 load-cell 200kg rating


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

  SPI.begin();
  SPI.beginTransaction(SPISettings(3000000, MSBFIRST, SPI_MODE2));
  
  Serial.println ("Begin bee counter.");
  pinMode (LATCH, OUTPUT);
  digitalWrite (LATCH, HIGH);

  pinMode (POWER_GATES_1, OUTPUT);
  digitalWrite(POWER_GATES_1, LOW);
  pinMode (POWER_GATES_2, OUTPUT);
  digitalWrite(POWER_GATES_2, LOW);


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
  
}


byte switchBank[numberOfBanks];
byte oldSwitchBank[numberOfBanks];


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
  for(int i =0; i < numberOfBanks;i++)
  {
    switchBank[i] = SPI.transfer (0);
    if( switchBank[i] != oldSwitchBank[i])
      change = true;
  }

  if( change )
  {
    int gate = 0;
    for(int i =0; i < numberOfBanks;i++)
    {
      for(int j = 0; j < 8; j++)
      {
        if((switchBank[i] >> j) & 1)
            outSensorReading[gate] = HIGH;
        else outSensorReading[gate] = LOW;
        j++;
        if((switchBank[i] >> j) & 1)
            inSensorReading[gate] = HIGH;
        else inSensorReading[gate] = LOW;       
        gate++;  
      }
      oldSwitchBank[i] = switchBank[i];
    }
  }

  for (int i = startGate; i < endGate; i++) 
  { 
    if(inSensorReading[i] == HIGH || outSensorReading[i] == HIGH) 
    {
      digitalWrite(LED, HIGH);
      break;
    }
    digitalWrite(LED, LOW);
  }

  
  for (int i = startGate; i < endGate; i++) 
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
    if(currentTime - inSensorTime[i] > debeebounce && checkStateIn[i] == 0)  //debounce IN sensor
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
        Serial.print(", IT ,");
        Serial.print(inReadingTimeHigh[i]);
        Serial.print(", ");    
        if(outReadingTimeHigh[i] < 650 && inReadingTimeHigh[i] < 650){ //should be less than 650ms
          if(currentTime - lastOutFinishedTime[i] < 200){ //the sensors are pretty cose together so the time it takes to trigger on and then the other should be small.. ~200ms
            inTotal++;
            Serial.print(currentTime);
            Serial.print(",");
            Serial.println(1);
          }else{
            Serial.println(currentTime);
          }
        }else{
          Serial.println(currentTime);
        }
      }           
    }
    if(currentTime - outSensorTime[i] > debeebounce && checkStateOut[i] == 0)  //debounce OUT sensor
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
        Serial.print(", OT ,");
        Serial.print(outReadingTimeHigh[i]);
        Serial.print(", ");        
        if(outReadingTimeHigh[i] < 600 && inReadingTimeHigh[i] < 600){ //should be less than 600ms
          if(currentTime - lastInFinishedTime[i] < 200){ //the sensors are pretty cose together so this time should be small
            outTotal++;
            Serial.print(currentTime);
            Serial.print(",");
            Serial.println(1);
          }else{
            Serial.println(currentTime);
          }
        }else{
          Serial.println(currentTime);
        }
      }          
    }        
  }    

  delay (15);   // debounce

  if (currentTime - lastOutput > outputDelay) 
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
 

   Hx711 scale(SDA, SCL ); // SDA, SCL on Feaather M0 board
   scale.setScale(-22.43f);		//calibration_factor = 19.55 for 4 load-cell 200kg rating
   scale.setOffset( 8388608 );  //with no weight on beehive.
   g_payload.grams = scale.getGram();
//pinMode(SCL, INPUT);
	pinMode(SDA, OUTPUT);

  Serial.print("scale time:\t"); Serial.println((millis()-t)); t = millis();
 
  float measuredvbat = analogRead(VBATPIN);
  measuredvbat *= 2;    // we divided by 2, so multiply back
  measuredvbat *= 3.3;  // Multiply by 3.3V, our reference voltage
  measuredvbat /= 1024; // convert to voltage
  Serial.print("vRead time:\t");  Serial.println((millis()-t)); t = millis();


  g_payload.beeInRate=beesIn/((double)outputDelay/60000.0);
  g_payload.beeOutRate=beesOut/((double)outputDelay/60000.0);
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
