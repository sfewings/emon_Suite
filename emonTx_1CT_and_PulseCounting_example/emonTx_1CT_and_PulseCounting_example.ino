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

//int supplyV; //no need to send supply voltage as emonTx will be powered from USB adapter when using pulse counting 
//########################################################################################################################
//Data Structure to be sent
//######################################################################################################################## 
typedef struct {
  	  int power;		// power value
          int pulse;            //pulse increments 
          int ct1;              //CT reading 
          int supplyV;          // unit supply voltage
} Payload;
Payload emontx;
//########################################################################################################################

void setup()
{
  Serial.begin(9600);                   //fast serial 
  pinMode(LEDpin, OUTPUT);
  digitalWrite(LEDpin, HIGH);    //turn on LED 
  
  Serial.println("emonTx interrupt pulse counting + one CT example");
  Serial.println("openenergymonitor.org");
  
  delay(10);  
  //-----------------------------------------
  // RFM12B Initialize
  //------------------------------------------
  rf12_initialize(myNodeID,freq,network,10);     //Initialize RFM12 with settings defined above, use pin 10 as SSelect
  //------------------------------------------
  
  delay(20);
  
  Serial.print("Node: "); 
  Serial.print(myNodeID); 
  Serial.print(" Freq: "); 
  if (freq == RF12_433MHZ) Serial.print("433Mhz");
  if (freq == RF12_868MHZ) Serial.print("868Mhz");
  if (freq == RF12_915MHZ) Serial.print("915Mhz");  
  Serial.print(" Network: "); 
  Serial.println(network);
  delay(20);
  
  if (SERIAL==0) {
    Serial.println("serial disabled"); 
    Serial.end();
  }
  SetupPulseCount();
  //attachInterrupt(1, onPulse, FALLING);    // KWH interrupt attached to IRQ 1  = pin3 - hardwired to emonTx pulse jackplug. For connections see: http://openenergymonitor.org/emon/node/208

  digitalWrite(LEDpin, LOW);              //turn off LED
}


void loop()
{  
    digitalWrite(LEDpin, HIGH);     //flash LED - very quickly each time a pluse occus  
   //--------------------------------------------------------------------------------------------------
    // 1. Read current supply voltage and get current CT energy monitoring reading 
    //--------------------------------------------------------------------------------------------------
    emontx.supplyV = readVcc();  //read emontx supply voltage
    emontx.ct1=int(emon( CT_INPUT_PIN, CAL, RMS_VOLTAGE, NUMBER_OF_SAMPLES, CT_BURDEN_RESISTOR, CT_TURNS, emontx.supplyV));
    //--------------------------------------------------------------------------------------------------
  
    emontx.pulse=MeterPulseLog(); //pulseCount;        //as well as sending power we also send pulse increments inorder to accuratly calculate kwhr
    emontx.power=MeterCurrentWatts(); 
    
    //--------------------------------------------------------------------------------------------------
    // 2. Send data via RF 
    //--------------------------------------------------------------------------------------------------
    while (!rf12_canSend())
    rf12_recvDone();
    //rf12_sendStart(0,&emontx, sizeof emontx); 
    rf12_sendStart(rf12_hdr, &emontx, sizeof emontx, RADIO_SYNC_MODE); 
    //--------------------------------------------------------------------------------------------------    

    if (SERIAL==1){
      Serial.print(emontx.power);
      Serial.print(" ");
      Serial.print(emontx.pulse);
      Serial.print(" ");
      Serial.print(emontx.ct1);
      Serial.print(" ");
      Serial.println(emontx.supplyV);
    }
   
    //pulseCount=0;       //reset pulse increments 
    digitalWrite(LEDpin, LOW);     //flash LED - very quickly each time a pluse occus  

    delay(1000);        //1s delay  
}

//--------------------------------------------------------------------------------------------------
// The interrupt routine - runs each time a falling edge of a pulse is detected
//--------------------------------------------------------------------------------------------------
/*
void onPulse()                  
{
  digitalWrite(LEDpin, HIGH);     //flash LED - very quickly each time a pluse occus  

  lastTime = pulseTime;        //used to measure time between pulses.
  pulseTime = micros();

  pulseCount++;                                                      //pulseCounter               

  emontx.power = int((3600000000.0 / (pulseTime - lastTime))/ppwh);  //Calculate power
  
  //elapsedWh= (1.0*pulseCount/(ppwh));   // Find wh elapsed
  

  digitalWrite(LEDpin, LOW);
}
//--------------------------------------------------------------------------------------------------
*/



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


