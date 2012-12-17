//------------------------------------------------------------------------------------------------------------------------------------------------
// emonGLCD Single CT example
// to be used with nanode auto update time base example

// emonGLCD documentation http://openEnergyMonitor.org/emon/emonglcd

// For use with emonTx setup with one CT
// RTC to reset Kwh counters at midnight is implemented is software. 
// Correct time is updated via NanodeRF which gets time from internet
// Temperature recorded on the emonglcd is also sent to the NanodeRF for online graphing

// GLCD library by Jean-Claude Wippler: JeeLabs.org
// 2010-05-28 <jcw@equi4.com> http://opensource.org/licenses/mit-license.php
//
// Authors: Glyn Hudson and Trystan Lea
// Part of the: openenergymonitor.org project
// Licenced under GNU GPL V3
// http://openenergymonitor.org/emon/license

//-------------------------------------------------------------------------------------------------------------------------------------------------
#define DEBUG

//#include <OneWire.h>		    // http://www.pjrc.com/teensy/td_libs_OneWire.html
//#include <DallasTemperature.h>      // http://download.milesburton.com/Arduino/MaximTemperature/ (3.7.2 Beta needed for Arduino 1.0)

//JeeLab libraires		       http://github.com/jcw
#include <JeeLib.h>		    // ports and RFM12 - used for RFM12B wireless

#include <PortsLCD.h>

#include <Time.h>
//#include <Udp.h>        //for SNTP time

const int redLED=6;                 // Red tri-color LED

//--------------------------------------------------------------------------------------------
// RFM12B Setup
//--------------------------------------------------------------------------------------------
#define MYNODE 21            //Should be unique on network, node ID 30 reserved for base station
#define freq RF12_915MHZ     //frequency - match to same frequency as RFM12B module (change to 868Mhz or 915Mhz if appropriate)
#define group 210            //network group, must be same as emonTx and emonBase

//---------------------------------------------------
// Data structures for transfering data between units
//---------------------------------------------------
//typedef struct { int power, battery; } PayloadTX;
typedef struct {
  	  int power;		// power value
          int pulse;            //pulse increments 
          int ct1;              //CT reading 
          int supplyV;          // unit supply voltage
} PayloadTX;
PayloadTX emontx;    

typedef struct { int temperature; } PayloadGLCD;
PayloadGLCD emonglcd;

typedef struct { int hour, mins, sec; } PayloadBase;
PayloadBase emonbase;
//---------------------------------------------------

//--------------------------------------------------------------------------------------------
// Power variables
//--------------------------------------------------------------------------------------------
double wh_gen, wh_consuming;                           //integer variables to store ammout of power currenty being consumed grid (in/out) +gen
unsigned long whtime;                                  //used to calculate energy used per day (kWh/d)
unsigned int pktsReceived;
//--------------------------------------------------------------------------------------------
// DS18B20 temperature setup - onboard sensor 
//--------------------------------------------------------------------------------------------
//OneWire oneWire(ONE_WIRE_BUS);
//DallasTemperature sensors(&oneWire);
//double temp,maxtemp,mintemp;


//--------------------------------------------------------------------------------------------
// Ethercard support
//-------------------------------------------------------------------------------------------- 
#include <EtherCard.h>
static byte mymac[] = { 0x74,0x69,0x69,0x2D,0x30,0x32 };
byte Ethernet::buffer[900];

//-------------------------------------------------------------------------------------------- 
//Pachube support
//-------------------------------------------------------------------------------------------- 
// change these settings to match your own setup
#define FEED    "78783"
#define APIKEY  "f04d8709cfe8d8b88d5c843492a738f634f0fab11402e6c2abc2b4c7f6dfff31"
//#define USERAGENT "Cosm Arduino Example (78783)"
char website[] PROGMEM = "api.pachube.com";

uint32_t timer;
Stash stash;


//--------------------------------------------------------------------------------------------
// Software RTC setup
//-------------------------------------------------------------------------------------------- 
//RTC_Millis RTC;
int thisHour;
  
//-------------------------------------------------------------------------------------------- 
// Flow control
//-------------------------------------------------------------------------------------------- 
int view = 1;                                // Used to control which screen view is shown
unsigned long last_emontx;                   // Used to count time from last emontx update
unsigned long slow_update;                   // Used to count time for slow 10s events
unsigned long fast_update;                   // Used to count time for fast 100ms events
  
//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () {
    Serial.begin(9600);
    
  
    Serial.print("MAC: ");
    for (byte i = 0; i < 6; ++i) {
      Serial.print(mymac[i], HEX);
      if (i < 5)
        Serial.print(':');
    }
    Serial.println();
    
    if (ether.begin(sizeof Ethernet::buffer, mymac, 8) == 0) 
      Serial.println( "Failed to access Ethernet controller");
    
    Serial.println("Setting up DHCP");
    if (!ether.dhcpSetup())
      Serial.println( "DHCP failed");
    
    ether.printIp("My IP: ", ether.myip);
    ether.printIp("Netmask: ", ether.mymask);
    ether.printIp("GW IP: ", ether.gwip);
    ether.printIp("DNS IP: ", ether.dnsip);
   
    if (!ether.dnsLookup(website))
      Serial.println("DNS failed");
      
    ether.printIp("Pachube SRV: ", ether.hisip);
   
   
   Serial.println("rf12_initialize");
   rf12_initialize(MYNODE, freq,group);
   Serial.println("rf12_initialize finished");

    print_glcd_setup();
    
    pinMode(redLED, OUTPUT);  
    pktsReceived = 0;
}
//--------------------------------------------------------------------------------------------


//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () {
  
    //--------------------------------------------------------------------------------------------
    // 1. On RF recieve
    //--------------------------------------------------------------------------------------------  
    if (rf12_recvDone()){
      if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)  // and no rf errors
      {
        int node_id = (rf12_hdr & 0x1F);
        
        if (node_id == 10)                        // === EMONTX ====
        {
          //monitor the reliability of receival
          pktsReceived++;

          emontx = *(PayloadTX*) rf12_data;       // get emontx payload data
          #ifdef DEBUG 
            print_emontx_payload();               // print data to serial
          #endif  
          last_emontx = millis();                 // set time of last update to now

          
          digitalWrite(redLED, HIGH );
          delay(100);                             // delay to make sure printing finished
          digitalWrite(redLED, LOW );
          power_calculations();                   // do the power calculations
        }
        
        if (node_id == 15)                        // ==== EMONBASE ====
        {
          emonbase = *(PayloadBase*) rf12_data;   // get emonbase payload data
          #ifdef DEBUG 
            print_emonbase_payload();             // print data to serial
          #endif  
          //RTC.adjust(DateTime(2012, 1, 1, emonbase.hour, emonbase.mins, emonbase.sec));  // adjust emonglcd software real time clock
          
          delay(100);                             // delay to make sure printing and clock setting finished
           
          //emonglcd.temperature = (int) (temp * 100);                          // set emonglcd payload
          //int i = 0; while (!rf12_canSend() && i<10) {rf12_recvDone(); i++;}  // if ready to send + exit loop if it gets stuck as it seems too
          //rf12_sendStart(0, &emonglcd, sizeof emonglcd);                      // send emonglcd data
          //rf12_sendWait(0);
          #ifdef DEBUG 
            Serial.println("3 emonglcd sent");                                // print status
          #endif                               
        }
      }
    }
    
    //--------------------------------------------------------------------
    // Things to do every 10s
    //--------------------------------------------------------------------
    //if ((millis()-slow_update)>10000)
    //{
    //   slow_update = millis();
       
       // Control led's
    //   led_control();
    //   backlight_control();
       
       // Get temperatue from onboard sensor
    //   sensors.requestTemperatures();
    //   temp = (sensors.getTempCByIndex(0));
    //   if (temp > maxtemp) maxtemp = temp;
    //   if (temp < mintemp) mintemp = temp;
    //}

    if( millis()%10 == 0)
    {
        //Do the ethernet stuff including pachube update
        word pos = ether.packetLoop(ether.packetReceive());
        if (pos) 
        {
          char* data = (char *) Ethernet::buffer + pos;
          Serial.println(data);
        }
    }    
    if (millis() > timer) 
    {
      timer = millis() + 60000;
      
      // generate two fake values as payload - by using a separate stash,
      // we can determine the size of the generated message ahead of time
      byte sd = stash.create();
      stash.print("1,");
      stash.println((word) emontx.power);
      stash.print("2,");
      stash.println((word) emontx.ct1);
      stash.print("3,");
      stash.println((word) wh_consuming);
      stash.print("4,");
      stash.println((word) wh_gen);
      stash.print("5,");
      stash.println((word) pktsReceived);
      stash.save();
      
      pktsReceived = 0;

      // generate the header with payload - note that the stash size is used,
      // and that a "stash descriptor" is passed in as argument using "$H"
      Stash::prepare(PSTR("PUT http://$F/v2/feeds/$F.csv HTTP/1.0" "\r\n"
                          "Host: $F" "\r\n"
                          "X-PachubeApiKey: $F" "\r\n"
                          "Content-Length: $D" "\r\n"
                          "\r\n"
                          "$H"),
              website, PSTR(FEED), website, PSTR(APIKEY), stash.size(), sd);

      //for (;;) 
      //{
      //  char c = stash.get();
      //  if (c == 0)
      //    break;
      //  Serial.print(c);
      //}
      //Serial.println();

      // send the packet - this also releases all stash buffers once done
      ether.tcpSend();

      digitalWrite(redLED, HIGH);
      delay(500);
      digitalWrite(redLED, LOW);

      //Serial.println((char*)Ethernet::buffer);
    }
   
} 

//--------------------------------------------------------------------
// Calculate power and energy variables
//--------------------------------------------------------------------
void power_calculations()
{
  //DateTime now = RTC.now();
  time_t time = now();
  int last_hour = thisHour;
  thisHour = hour();
  if (last_hour == 23 && thisHour == 00) 
  { 
      wh_gen = 0; 
      wh_consuming = 0; 
  }
  
  //--------------------------------------------------
  // kWh calculation
  //--------------------------------------------------
  unsigned long lwhtime = whtime;
  whtime = millis();
  double whInc = emontx.ct1 * ((whtime-lwhtime)/3600000.0);
  wh_gen=wh_gen+whInc;
  whInc = emontx.power *((whtime-lwhtime)/3600000.0);
  wh_consuming=wh_consuming+whInc;
  //---------------------------------------------------------------------- 
}


