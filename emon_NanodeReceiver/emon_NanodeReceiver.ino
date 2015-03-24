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

const int RED_LED=6;                 // Red tri-color LED


//--------------------------------------------------------------------------------------------
// Workaround for http://gcc.gnu.org/bugzilla/show_bug.cgi?id=34734
//remove compiler warning "Warning: only initialized variables can be placed into program memory area" from 
//   Serial.println(F("string literal"));
//#ifdef PROGMEM
//#undef PROGMEM
//#define PROGMEM __attribute__((section(".progmem.data")))
//#endif
//--------------------------------------------------------------------------------------------


//--------------------------------------------------------------------------------------------
// RFM12B Setup
//--------------------------------------------------------------------------------------------
#define MYNODE 15            //Should be unique on network, node ID 30 reserved for base station
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
		  int temperature;		//DB1820 temperature
		  int rainGauge;		//rain gauge pulse
} PayloadTX;
PayloadTX emontx;    

typedef struct { int temperature; } PayloadGLCD;
PayloadGLCD emonglcd;

typedef struct { time_t time; } PayloadBase;
PayloadBase emonbase;

typedef struct {
	volatile unsigned long rainCount;			//The count from the rain gauge
	volatile unsigned long transmitCount;		//Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
	unsigned long supplyV;						// unit supply voltage
} PayloadRain;
PayloadRain rainTx;

unsigned long rainStartOfToday;
bool rainReceived;

//---------------------------------------------------

//--------------------------------------------------------------------------------------------
// Power variables
//--------------------------------------------------------------------------------------------
double wh_gen, wh_consuming;                           //integer variables to store ammout of power currenty being consumed grid (in/out) +gen
unsigned long whtime;                                  //used to calculate energy used per day (kWh/d)
unsigned int pktsReceived;
int dailyRainfall, lastRainfall;					   //daily Rainfall
//--------------------------------------------------------------------------------------------
// DS18B20 temperature setup - onboard sensor 
//--------------------------------------------------------------------------------------------
//OneWire oneWire(ONE_WIRE_BUS);
//DallasTemperature sensors(&oneWire);
//double temp,maxtemp,mintemp;


//--------------------------------------------------------------------------------------------
// NTP time support 
//--------------------------------------------------------------------------------------------

uint8_t clientPort = 123;

// The next part is to deal with converting time received from NTP servers
// to a value that can be displayed. This code was taken from somewhere that
// I cant remember. Apologies for no acknowledgement.

uint32_t lastNTPUpdate = 0;
uint32_t timeLong;
// Number of seconds between 1-Jan-1900 and 1-Jan-1970, unix time starts 1970
// and ntp time starts 1900.
#define GETTIMEOFDAY_TO_NTP_OFFSET 2208988800UL

static int currentTimeserver = 0;

// Find list of servers at http://support.ntp.org/bin/view/Servers/StratumTwoTimeServers
// Please observe server restrictions with regard to access to these servers.
// This number should match how many ntp time server strings we have
#define NUM_TIMESERVERS 7

// Create an entry for each timeserver to use
prog_char ntp0[] PROGMEM = "ntp1.anu.edu.au";
prog_char ntp1[] PROGMEM = "nist1-ny.ustiming.org";
prog_char ntp2[] PROGMEM = "ntp.exnet.com";
prog_char ntp3[] PROGMEM = "ntps1-0.cs.tu-berlin.de";
prog_char ntp4[] PROGMEM = "time.nist.gov";
prog_char ntp5[] PROGMEM = "ntps1-0.cs.tu-berlin.de";
prog_char ntp6[] PROGMEM = "time.nist.gov";

//static byte NTP_server_IP[NUM_NTPSERVERS][4] = {
//	{ 150, 203, 1, 10 },   // ntp1.anu.edu.au
//	{ 64, 90, 182, 55 },    // nist1-ny.ustiming.org
//	{ 130, 149, 17, 21 },    // ntps1-0.cs.tu-berlin.de
//	{ 192, 53, 103, 108 },    // ptbtime1.ptb.de
//	{ 192, 43, 244, 18 },    // time.nist.gov
//	{ 130, 149, 17, 21 },    // ntps1-0.cs.tu-berlin.de
//	{ 192, 53, 103, 108 } };   // ptbtime1.ptb.de


// Now define another array in PROGMEM for the above strings
prog_char *ntpList[] PROGMEM = { ntp0, ntp1, ntp2, ntp3, ntp4, ntp5, ntp6 };



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
unsigned long last_rainTx;
unsigned long slow_update;                   // Used to count time for slow 10s events
unsigned long fast_update;                   // Used to count time for fast 100ms events
unsigned long request_NTP_Update;
//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
    pinMode(RED_LED, OUTPUT);  
    digitalWrite(RED_LED, LOW );		//Red LED has inverted logic. LOW is on, HIGH is off!

	Serial.begin(9600);
  
	delay(1000);
    Serial.println(F("Fewings Nanode emon based on openenergymonitor.org"));

    Serial.print(F("MAC: "));
    for (byte i = 0; i < 6; ++i) {
      Serial.print(mymac[i], HEX);
      if (i < 5)
        Serial.print(':');
    }
    Serial.println();
    
	uint8_t rev = ether.begin(sizeof Ethernet::buffer, mymac, 8);
	Serial.print(F("\nENC28J60 Revision "));
	Serial.println(rev, DEC);
    if (rev == 0) 
      Serial.println( F("Failed to access Ethernet controller"));
    
    Serial.println(F("Setting up DHCP"));
    if (!ether.dhcpSetup())
      Serial.println( F("DHCP failed"));
    
    ether.printIp(F("My IP: "), ether.myip);
    ether.printIp(F("Netmask: "), ether.mymask);
    ether.printIp(F("GW IP: "), ether.gwip);
    ether.printIp(F("DNS IP: "), ether.dnsip);
   
    Serial.print(F("Pachube DNS lookup : "));
    if (!ether.dnsLookup(website))
      Serial.println(F("DNS failed"));
      
    ether.printIp(F("Pachube SRV: "), ether.hisip);
   
   
    Serial.println(F("rf12_initialize"));
    rf12_initialize(MYNODE, freq,group);
    Serial.println(F("rf12_initialize finished"));

    print_glcd_setup();
    
	print_emontx_setup();

    pktsReceived = 0;
	dailyRainfall = 0;
	lastRainfall = 0;


	request_NTP_Update = millis()+1000;	//update in 1 second

	//NTP time
	//setSyncInterval(86400 * 7);         // update the time every week  (24*60*60) *7
	//setSyncProvider(GetNtpTime);      // initiate the callback to GetNtpTime   

	digitalWrite(RED_LED, HIGH );
}
//--------------------------------------------------------------------------------------------


//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
  
    //--------------------------------------------------------------------------------------------
    // 1. On RF recieve
    //--------------------------------------------------------------------------------------------  
    if (rf12_recvDone())
	{
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

          
          digitalWrite(RED_LED, LOW );
          delay(100);                             // delay to make sure printing finished
          digitalWrite(RED_LED, HIGH );
          power_calculations();                   // do the power calculations
        }
        
		if (node_id == 11)                        // ==== RainGauge Jeenode ====
		{
			rainTx = *(PayloadRain*)rf12_data;   // get emonbase payload data
			print_rain_payload(millis() - last_rainTx);             // print data to serial
			last_rainTx = millis();

			if (!rainReceived)
			{
				lastRainfall = rainTx.rainCount;
				rainReceived = true;
				dailyRainfall = 0;
			}
		}



        //if (node_id == 15)                        // ==== EMONBASE ====
        //{
        //  emonbase = *(PayloadBase*) rf12_data;   // get emonbase payload data
        //  #ifdef DEBUG 
        //    print_emonbase_payload();             // print data to serial
        //  #endif  
        //  //RTC.adjust(DateTime(2012, 1, 1, emonbase.hour, emonbase.mins, emonbase.sec));  // adjust emonglcd software real time clock
        //  
        //  delay(100);                             // delay to make sure printing and clock setting finished
        //   
        //  //emonglcd.temperature = (int) (temp * 100);                          // set emonglcd payload
        //  //int i = 0; while (!rf12_canSend() && i<10) {rf12_recvDone(); i++;}  // if ready to send + exit loop if it gets stuck as it seems too
        //  //rf12_sendStart(0, &emonglcd, sizeof emonglcd);                      // send emonglcd data
        //  //rf12_sendWait(0);
        //  #ifdef DEBUG 
        //    Serial.println("3 emonglcd sent");                                // print status
        //  #endif                               
        //}
      }
    }
    
    //--------------------------------------------------------------------
    // Things to do every 10s
    //--------------------------------------------------------------------
    if ((millis()-slow_update)>10000)
    {
       slow_update = millis();

	   while (!rf12_canSend())
		   rf12_recvDone();
	   emonbase.time = now();

	   Serial.print(F("emonBaseTx: "));
	   Serial.println(emonbase.time);

	   rf12_sendStart(0, &emonbase, sizeof(PayloadBase) );
	   rf12_sendWait(0);
    }

	if (millis() > request_NTP_Update)
	{
		// time to send request
		request_NTP_Update = millis()+ 20000L;	//try again in 20 seconds
		Serial.print(F("TimeSvr: "));
		Serial.println(currentTimeserver, DEC);

		if (!ether.dnsLookup((char*)pgm_read_word(&(ntpList[currentTimeserver]))))
		{
			Serial.println(F("DNS failed"));
		}
		else 
		{
			ether.printIp("SRV: ", ether.hisip);

			Serial.print(F("Send NTP request "));
			Serial.println(currentTimeserver, DEC);

			ether.ntpRequest(ether.hisip, ++clientPort);
			Serial.print(F("clientPort: "));
			Serial.println(clientPort, DEC);
		}
		if (++currentTimeserver >= NUM_TIMESERVERS)
			currentTimeserver = 0;
	}


    if( millis()%10 == 0)
    {
        //Do the ethernet stuff including pachube update
		int len = ether.packetReceive();
		word pos = ether.packetLoop(len);
		if (len) 
        {
			if (ether.ntpProcessAnswer(&timeLong, clientPort))
			{
				Serial.print(F("Time:"));

				if (timeLong) 
				{
					timeLong -= GETTIMEOFDAY_TO_NTP_OFFSET;
					timeLong += 8 * 60 * 60;			//correct for Perth timezone
					setTime(timeLong);

					Serial.println(timeLong); // secs since year 1900

					request_NTP_Update = millis() + 24 * 60 * 60 * 10000L;	//update in 7 days
					String str;
					Serial.print(F("NTP time received: "));
					Serial.print(DateString(str, now()));
					Serial.println(TimeString(str, now()));
				}
			}
        }
    }    
    if (millis() > timer) 
    {
      timer = millis() + 60000;
      
      // generate two fake values as payload - by using a separate stash,
      // we can determine the size of the generated message ahead of time
	  String str;
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
      stash.println( TemperatureString(str, emontx.temperature));
      stash.print("6,");
      stash.println((word) dailyRainfall);
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

      digitalWrite(RED_LED, LOW);
      delay(500);
      digitalWrite(RED_LED, HIGH);

      //Serial.println((char*)Ethernet::buffer);
    }

	time_t time = now();
	int lastHour = thisHour;
	thisHour = hour();
	if (lastHour == 23 && thisHour == 00)
	{
		wh_gen = 0;
		wh_consuming = 0;
	}
	//--------------------------------------------------
	// Rainfall caculations
	//--------------------------------------------------
	if (rainReceived)
	{
		if (lastHour == 10 && thisHour == 9)
		{
			lastRainfall = rainTx.rainCount;
			dailyRainfall = 0;
		}
		if (rainTx.rainCount < lastRainfall)
		{
			// int rollover or emontx has been reset to 0
			dailyRainfall = dailyRainfall + rainTx.rainCount;
		}
		else
			dailyRainfall = emontx.rainGauge - lastRainfall;
	}

} 

//--------------------------------------------------------------------
// Calculate power and energy variables
//--------------------------------------------------------------------
void power_calculations()
{
  //--------------------------------------------------
  // kWh calculation
  //--------------------------------------------------
  unsigned long lwhtime = whtime;
  whtime = millis();
  double whInc = emontx.ct1 * ((whtime-lwhtime)/3600000.0);
  wh_gen=wh_gen+whInc;
  whInc = emontx.power *((whtime-lwhtime)/3600000.0);
  wh_consuming=wh_consuming+whInc;
}


String TemperatureString(String& str, int temperature )
{
  int t = temperature;
  if( t < 0 )
  {
    str = "-";
    t *= -1;
    str += t/100;
  }
  else
    str = String(t/100);
  str +=".";
 
  str += (t/10)%10;

  return str;
}

String DateString(String& str, time_t time)
{
	str = "";
	str += day(time);
	str += "-";
	str += monthShortStr(month(time));
	str += "-";
	str += year(time) % 100;
	str += "       ";
	return str;
}

String TimeString(String& str, time_t time)
{
	str = "";
	if (hourFormat12(time) < 10)
		str += " ";
	str += hourFormat12(time);
	str += ":";
	if (minute(time) < 10)
		str += "0";
	str += minute(time);
	str += ":";
	if (second(time) < 10)
		str += "0";
	str += second(time);
	if (hour(time) < 12)
		str += " am";
	else
		str += " pm";
	str += "   ";
	return str;
}
