/*
                          _____    
                         |_   _|   
  ___ _ __ ___   ___  _ __ | |_  __
 / _ \ '_ ` _ \ / _ \| '_ \| \ \/ /
|  __/ | | | | | (_) | | | | |>  < 
 \___|_| |_| |_|\___/|_| |_\_/_/\_\
 
//--------------------------------------------------------------------------------------
//Interrupt pulse counting and one CT sensor 
//not low power - run emonTx from 5V USB adapter 

//Based on JeeLabs RF12 library http://jeelabs.org/2009/02/10/rfm12b-library-for-arduino/

// By Glyn Hudson and Trystan Lea: 21/9/11
// openenergymonitor.org
// GNU GPL V3

//  Modified by S Fewings.
//		1. Use power calculations from home power monitor project
//		2. Add temperature reading
//		3. Add rain gauge pulse counting. Added to Arduino IO pin 5, Jeenode Port 2. Une PinChangeInt library to add additional interrupt to Atmega328
//		4. Report line supply voltage. Only useful when powering by battery
//

// pulse input on pulse channel (top right jack)
// CT input on CT channel 2 (middle jack on RHS)

//--------------------------------------------------------------------------------------
*/

//JeeLabs libraries 
#include <Ports.h>
#include <RF12.h>
#include <avr/eeprom.h>
#include <util/crc16.h>  //cyclic redundancy check

//---------------------------------------------------------------------------------------------------
// Serial print settings - disable all serial prints if SERIAL 0 - increases long term stability 
//---------------------------------------------------------------------------------------------------
#define SERIAL 1
//---------------------------------------------------------------------------------------------------

//---------------------------------------------------------------------------------------------------
// RF12 settings 
//---------------------------------------------------------------------------------------------------
// fixed RF12 settings

#define myNodeID 10         //in the range 1-30
#define network     210      //default network group (can be in the range 1-250). All nodes required to communicate together must be on the same network group
#define freq RF12_915MHZ     //Frequency of RF12B module can be RF12_433MHZ, RF12_868MHZ or RF12_915MHZ. You should use the one matching the module you have.

// set the sync mode to 2 if the fuses are still the Arduino default
// mode 3 (full powerdown) can only be used with 258 CK startup fuses
#define RADIO_SYNC_MODE 2

#define COLLECT 0x20 // collect mode, i.e. pass incoming without sending acks
//--------------------------------------------------------------------------------------------------


//---------------------------------------------------------------------------------------------------
// Pulse counting settings 
//---------------------------------------------------------------------------------------------------

//long pulseCount = 0;               //Number of pulses, used to measure energy.
//unsigned long pulseTime,lastTime;  //Used to measure power.
//double power, elapsedWh;          //power and energy
//int ppwh = 1;                    ////1000 pulses/kwh = 1 pulse per wh - Number of pulses per wh - found or set on the meter.

//---------------------------------------------------------------------------------------------------

//--------------------------------------------------------------------------------------------------
// CT energy monitor setup definitions 
//--------------------------------------------------------------------------------------------------
int CT_INPUT_PIN =          0;    //I/O analogue 3 = emonTx CT2 channel. Change to analogue 0 for emonTx CT1 chnnel  
int NUMBER_OF_SAMPLES =     1480; //The period (one wavelength) of mains 50Hz is 20ms. Each samples was measured to take 0.188ms. This meas that 106.4 samples/wavelength are possible. 1480 samples takes 280.14ms which is 14 wavelengths. 
int RMS_VOLTAGE =           240;  //Assumed supply voltage (230V in UK).  Tolerance: +10%-6%
int CT_BURDEN_RESISTOR =    15;   //value in ohms of burden resistor R3 and R6
int CT_TURNS =              1500; //number of turns in CT sensor. 1500 is the vaue of the efergy CT 

double CAL=(1.295000139 *1.6);          //*calibration coefficient* IMPORTANT - each monitor must be calibrated for maximum accuracy. See step 4 http://openenergymonitor.org/emon/node/58. Set to 1.295 for Seedstudio 100A current output CT (included in emonTx V2.0 kit)
//--------------------------------------------------------------------------------------------------


//--------------------------------------------------------------------------------------------------
// LED Indicator  
//--------------------------------------------------------------------------------------------------
# define LEDpin 9          //hardwired on emonTx PCB
//--------------------------------------------------------------------------------------------------


//Temperature support - OneWire Dallas temperature sensor

#include <OneWire.h>
#include <DallasTemperature.h>

#define ONE_WIRE_BUS 4                                                  // Data wire is plugged into port 2 on the Arduino
OneWire oneWire(ONE_WIRE_BUS);                                          // Setup a oneWire instance to communicate with any OneWire devices (not just Maxim/Dallas temperature ICs)
DallasTemperature sensors(&oneWire);                                    // Pass our oneWire reference to Dallas Temperature.

// By using direct addressing its possible to make sure that as you add temperature sensors
// the temperature sensor to variable mapping will not change.
// To find the addresses of your temperature sensors use the: **temperature_search sketch**
// DeviceAddress address_T1 = { 0x28, 0x22, 0x70, 0xEE, 0x02, 0x00, 0x00, 0xB8 };

//int supplyV; //no need to send supply voltage as emonTx will be powered from USB adapter when using pulse counting 
//########################################################################################################################
//Data Structure to be sent
//######################################################################################################################## 
typedef struct {
  	  int power;		// power value
          int pulse;            //pulse increments 
          int ct1;              //CT reading 
          int supplyV;          // unit supply voltage
		  int temperature;		//DB1820 temperature
		  int rainGauge;		//rain gauge pulse
} Payload;
Payload emontx;
//########################################################################################################################



void setup()
{
  Serial.begin(9600);                   //fast serial 
  pinMode(LEDpin, OUTPUT);
  digitalWrite(LEDpin, HIGH);    //turn on LED 

  delay(1000);
  
  Serial.println(F("Fewings emonTx. Based on openenergymonitor.org"));
  
  delay(10);  
  //-----------------------------------------
  // RFM12B Initialize
  //------------------------------------------
  rf12_initialize(myNodeID,freq,network,1600);     //Initialize RFM12 with settings defined above, use pin 10 as SSelect
  //------------------------------------------
  
  delay(20);
  
  Serial.print(F("Node: ")); 
  Serial.print(myNodeID); 
  Serial.print(F(" Freq: ")); 
  if (freq == RF12_433MHZ) Serial.print(F("433Mhz"));
  if (freq == RF12_868MHZ) Serial.print(F("868Mhz"));
  if (freq == RF12_915MHZ) Serial.print(F("915Mhz"));  
  Serial.print(F(" Network: ")); 
  Serial.println(network);
  delay(20);
  
  if (SERIAL==0) {
    Serial.println("serial disabled"); 
    Serial.end();
  }

  SetupPulseCount();


  //temperature
  sensors.begin();

  DeviceAddress tmp_address;
  int numberOfDevices = sensors.getDeviceCount();
  
  for(int i=0;i<numberOfDevices; i++)
  {
    sensors.getAddress(tmp_address, i);
	Serial.print(F("Temperature sensor address "));
	Serial.print(i+1);
	Serial.print(F(": "));
    printAddress(tmp_address);
    Serial.println();
  }

  // Initialise 
  emontx.pulse = 0;      
  emontx.ct1 = 0;        
  emontx.supplyV = 0;    
  emontx.temperature = 0;
  emontx.rainGauge = 0;	

  Serial.println(F("emontx: Power IR_Pulse CurrentTransformer Temperature RainGauge"));

  digitalWrite(LEDpin, LOW);              //turn off LED
}


void loop()
{  
   //--------------------------------------------------------------------------------------------------
    // 1. Read current supply voltage and get current CT energy monitoring reading 
    //--------------------------------------------------------------------------------------------------
    emontx.power = MeterCurrentWatts(); 
    emontx.pulse = MeterPulseLog();					//as well as sending power we also send pulse increments inorder to accuratly calculate kwhr
    emontx.supplyV = readVcc();					//read emontx supply voltage
    emontx.ct1= int(emon( CT_INPUT_PIN, CAL, RMS_VOLTAGE, NUMBER_OF_SAMPLES, CT_BURDEN_RESISTOR, CT_TURNS, emontx.supplyV));
	emontx.rainGauge = MeterRainGauge();			//return the raingauge counts. 
	sensors.requestTemperatures();  
	emontx.temperature = sensors.getTempCByIndex(0)*100;

    //--------------------------------------------------------------------------------------------------
    // 2. Send data via RF 
    //--------------------------------------------------------------------------------------------------
    while (!rf12_canSend())
    rf12_recvDone();
    rf12_sendStart(0,&emontx, sizeof emontx); 
    //rf12_sendStart(rf12_hdr, &emontx, sizeof emontx, RADIO_SYNC_MODE); 
    //--------------------------------------------------------------------------------------------------    


    if (SERIAL==1){
      Serial.print(F("emontx: "));
      Serial.print(emontx.power);
      Serial.print(F(" "));
      Serial.print(emontx.pulse);
      Serial.print(F(" "));
      Serial.print(emontx.ct1);
      Serial.print(F(" "));
      //Serial.print(emontx.supplyV);
      //Serial.print(" ");
      Serial.print(emontx.temperature);
      Serial.print(F(" "));
	  Serial.println(emontx.rainGauge);
    }
   
    digitalWrite(LEDpin, HIGH);     //flash LED - very quickly each time a pluse occus  
    delay(1);
	digitalWrite(LEDpin, LOW);     //flash LED - very quickly each time a pluse occus  

    delay(1000);        //1s delay  
}



void printAddress(uint8_t deviceAddress[8])
{
  Serial.print("{ ");
  for (uint8_t i = 0; i < 8; i++)
  {
    // zero pad the address if necessary
    Serial.print("0x");
    if (deviceAddress[i] < 16) Serial.print("0");
    Serial.print(deviceAddress[i], HEX);
    if (i<7) Serial.print(", ");
    
  }
  Serial.print(" }");
}


//--------------------------------------------------------------------------------------------------
// Read current emonTx battery voltage - not main supplyV!
//--------------------------------------------------------------------------------------------------
long readVcc() {
  long result;
  // Read 1.1V reference against AVcc
  ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
  delay(2); // Wait for Vref to settle
  ADCSRA |= _BV(ADSC); // Convert
  while (bit_is_set(ADCSRA,ADSC));
  result = ADCL;
  result |= ADCH<<8;
  result = 1126400L / result; // Back-calculate AVcc in mV
  return result;
}
//--------------------------------------------------------------------------------------------------
