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
#include <time.h>

LiquidCrystal lcd(A2,4, 8,7,6,5);

#include <Time.h>

//#define ONE_WIRE_BUS 5              // temperature sensor connection - hard wired 
//const int greenLED=8;               // Green tri-color LED
//const int redLED=9;                 // Red tri-color LED
//const int switchpin=15;		    // digital pin of onboard pushswitch 
//const int LDRpin=4;    		    // analog pin of onboard lightsensor 

//--------------------------------------------------------------------------------------------
// RFM12B Setup
//--------------------------------------------------------------------------------------------
#define MYNODE 20            //Should be unique on network, node ID 30 reserved for base station
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

typedef struct { time_t time; } PayloadBase;
PayloadBase emonbase;
//---------------------------------------------------

typedef struct {
	volatile unsigned long rainCount;			//The count from the rain gauge
	volatile unsigned long transmitCount;		//Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
	unsigned long supplyV;						// unit supply voltage
} PayloadRain;
PayloadRain rainTx;

//--------------------------------------------------------------------------------------------
// Power variables
//--------------------------------------------------------------------------------------------
int importing, night;                                  //flag to indicate import/export
double consuming, gen, grid, wh_gen, wh_consuming;     //integer variables to store ammout of power currenty being consumed grid (in/out) +gen
unsigned long whtime;                                  //used to calculate energy used per day (kWh/d)

#define MAX_TIMES  3
unsigned int txReceived[MAX_TIMES];
unsigned int packetsReceived;

uint32_t timer;
int toggle = 0;


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
unsigned long last_rainTx;                   // Used to count time from last emontx update
unsigned long last_emonBase;				
unsigned long slow_update;                   // Used to count time for slow 10s events
unsigned long fast_update;                   // Used to count time for fast 100ms events
bool g_timeSet;								 // true if time has been set
unsigned long rainStartOfToday;
bool rainReceived;
unsigned long dailyRainfall;
time_t	lastUpdateTime;

static void lcdInt (byte x, byte y, unsigned int value, char fill =' ') 
{
  lcd.setCursor(x, y);
  int places = log10(value);
  for(int i=0; i<4-places;i++)
  lcd.print(fill);
  lcd.print(value);  
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

String RainString(String& str, int rainGauge )
{
	//raingauge increments in 0.2mm per value
	str = String(rainGauge/5);
	str += ".";
	str += (rainGauge%5)*2;
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

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
    Serial.begin(9600);
    
    lcd.begin(16, 2);
    lcd.setCursor(0, 0);

	lcd.print("Hello");
   
   Serial.println("rf12_initialize");
   rf12_initialize(MYNODE, freq,group);
   Serial.println("rf12_initialize finished");

    print_glcd_setup();

	print_emontx_setup();
    
    for(int i=0; i< MAX_TIMES;i++)
    {
      txReceived[i] = 0;
    }
    packetsReceived = 0;
	g_timeSet = false;
    

	rainReceived = false;
	rainStartOfToday = 0;
	lastUpdateTime = now();

    //pinMode(greenLED, OUTPUT); 
    //pinMode(redLED, OUTPUT);  
  
    //sensors.begin();                         // start up the DS18B20 temp sensor onboard  
    //sensors.requestTemperatures();
    //temp = (sensors.getTempCByIndex(0));     // get inital temperture reading
    //mintemp = temp; maxtemp = temp;          // reset min and max
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
				int index = (int)(((millis() - last_emontx) / 5050.0) - 1.0);  //expect these 5 seconds apart
				if (index < 0)
					index = 0;
				if (index >= MAX_TIMES)
					index = MAX_TIMES - 1;
				txReceived[index]++;
				packetsReceived++;

				emontx = *(PayloadTX*)rf12_data;       // get emontx payload data
#ifdef DEBUG 
				print_emontx_payload(millis() - last_emontx);               // print data to serial
#endif  
				last_emontx = millis();                 // set time of last update to now

				delay(100);                             // delay to make sure printing finished
				power_calculations();                   // do the power calculations
			}

			if (node_id == 11)                        // ==== RainGauge Jeenode ====
			{
				rainTx = *(PayloadRain*)rf12_data;   // get emonbase payload data
				print_rain_payload(millis() - last_rainTx );             // print data to serial
				last_rainTx = millis();

				if (!rainReceived)
				{
					rainStartOfToday = rainTx.rainCount;
					rainReceived = true;
					dailyRainfall = 0;
				}
				if (rainTx.rainCount < rainStartOfToday)
				{
					// int rollover or emontx has been reset to 0
					dailyRainfall = dailyRainfall + rainTx.rainCount;
				}
				else
					dailyRainfall = rainTx.rainCount - rainStartOfToday;

			}


			if (node_id == 15)						//emon base. Receives the time
			{
				PayloadBase base = *((PayloadBase*)rf12_data);
				print_emonbase_payload(base.time, (millis() - last_emonBase));             // print data to serial
				setTime(base.time);
				lastUpdateTime = now();
				last_emonBase = millis();
				g_timeSet = true;
			}
		}
	}



    //--------------------------------------------------------------------
    // Control toggling of screen pages
    //--------------------------------------------------------------------    
    //if (digitalRead(switchpin) == TRUE) view = 2; else view = 1;

    //--------------------------------------------------------------------
    // Update the display every 200ms
    //--------------------------------------------------------------------
    if ((millis()-fast_update)>200)
    {
      fast_update = millis();
      lcdInt(0,0, (unsigned int) emontx.power );
      lcdInt(5,0, (unsigned int) emontx.ct1 );

	  String str;
	  lcd.setCursor(11, 0);
	  lcd.print( TemperatureString(str, emontx.temperature));

      //lcdInt(11,0, (unsigned int) emontx.supplyV );

	  if( !g_timeSet || (toggle++ %10 < 5 ) )
	  {
		  lcd.setCursor(0, 1);
		  lcd.print(RainString(str, (rainReceived? dailyRainfall : 0)));
		  lcdInt(5,1, (unsigned int) txReceived[0] );
		  lcd.setCursor(11, 1);
		  //use TemperatureString to display seconds since last receive
		  lcd.print( TemperatureString(str, (unsigned int)((millis()-last_emontx)/10)));
		  //lcdInt(11,1, (unsigned int) ((millis()-last_emontx)*10) );
	  }
	  else
	  {
		  lcd.setCursor(0, 1);
		  lcd.print(TimeString(str, now()));
	  }


	  //DateTime now = RTC.now();
	  time_t time = now();
	  int last_hour = thisHour;
	  thisHour = hour();
	  if (last_hour == 23 && thisHour == 00)
	  {
		  wh_gen = 0;
		  wh_consuming = 0;
	  }
	  if (rainReceived)
	  {
		  if (last_hour == 10 && thisHour == 9)
		  {
			  rainStartOfToday = rainTx.rainCount;
			  dailyRainfall = 0;
		  }
	  }

    }
    
} //end loop
//--------------------------------------------------------------------------------------------

//--------------------------------------------------------------------
// Calculate power and energy variables
//--------------------------------------------------------------------
void power_calculations()
{
  gen = 0; // emontx.gen;  if (gen<100) gen=0;	// remove noise offset 
  consuming = emontx.power; 		        // for type 1 solar PV monitoring
  grid = emontx.power - gen;		        // for type 1 solar PV monitoring
  // grid=emontx.grid; 		         	// for type 2 solar PV monitoring                     
  // consuming=gen + emontx.grid; 	        // for type 2 solar PV monitoring - grid should be positive when importing and negastive when exporting. Flip round CT cable clap orientation if not
         
  if (gen > consuming) {
    importing=0; 			        //set importing flag 
    grid= grid*-1;			        //set grid to be positive - the text 'importing' will change to 'exporting' instead. 
  } else importing=1;
            
  //--------------------------------------------------
  // kWh calculation
  //--------------------------------------------------
  unsigned long lwhtime = whtime;
  whtime = millis();
  double whInc = gen * ((whtime-lwhtime)/3600000.0);
  wh_gen=wh_gen+whInc;
  whInc = consuming *((whtime-lwhtime)/3600000.0);
  wh_consuming=wh_consuming+whInc;
  //---------------------------------------------------------------------- 
}


