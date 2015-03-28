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

//JeeLab libraires				http://github.com/jcw
#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <PortsLCD.h>
#include <time.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <PinChangeInt.h>				//Library to provide additional interrupts on the Arduino Uno328

#include <EmonShared.h>

LiquidCrystal lcd(A2,4, 8,7,6,5);


//--------------------------------------------------------------------------------------------
// Power variables
//--------------------------------------------------------------------------------------------
int importing, night;									//flag to indicate import/export
double consuming, gen, grid, wh_gen, wh_consuming;	 //integer variables to store ammout of power currenty being consumed grid (in/out) +gen
unsigned long whtime;									//used to calculate energy used per day (kWh/d)

#define MAX_NODES	3
unsigned int txReceived[MAX_NODES];
unsigned long lastReceived[MAX_NODES];


PayloadEmon emonPayload;
PayloadRain rainPayload;
PayloadBase basePayload;

RF12Init rf12Init = { DISPLAY_NODE, RF12_915MHZ, 210 };

int thisHour;
time_t startTime = 0;

//---------------------------------------------------------------------------------------------------
// Push button support. On pin A3
//---------------------------------------------------------------------------------------------------
typedef enum {
	eCurrent = 0,
	//eTotal,
	//eMax,
	//eMin,
	eRainFall,
	eDateTimeNow,
	eDateTimeStartRunning,
	eDiagnosis
}  ButtonDisplayMode;

volatile ButtonDisplayMode pushButton = eCurrent;
volatile unsigned long	g_RGlastTick = 0;
ButtonDisplayMode lastPushButton = eDiagnosis;


//---------------------------------------------------------------------------------------------------
// Dallas temperature sensor	on pin 5, Jeenode port 2
//---------------------------------------------------------------------------------------------------
OneWire oneWire(A4);
DallasTemperature temperatureSensor(&oneWire);

//-------------------------------------------------------------------------------------------- 
// Flow control
//-------------------------------------------------------------------------------------------- 
unsigned long slow_update;					// Used to count time for slow 10s events
unsigned long fast_update;					// Used to count time for fast 100ms events
bool g_timeSet;											// true if time has been set
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
	str += "	 ";
	return str;
}

// Push button interrupt routine
void interruptHandlerPushButton()
{
	unsigned long tick = millis();
	unsigned long period;
	if (tick < g_RGlastTick)
		period = tick + (g_RGlastTick - 0xFFFFFFFF);	//rollover occured
	else
		period = tick - g_RGlastTick;
	g_RGlastTick = tick;

	if (period > 500)	//more than 500 ms to avoid switch bounce
	{
		if (pushButton == eDiagnosis)
			pushButton = eCurrent;
		else
			pushButton = (ButtonDisplayMode)((int)pushButton + 1);

	}
}


//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
	Serial.begin(9600);
	
	lcd.begin(16, 2);
	lcd.setCursor(0, 0);

	lcd.print(F("Fewings Power Mon"));
	
	Serial.println(F("Fewings emonGLCD solar PV monitor - gen and use"));

	Serial.println("rf12_initialize");
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);


	for (int i = 0; i< MAX_NODES; i++)
	{
		txReceived[i] = 0;
		lastReceived[i] = millis();
	}
	//packetsReceived = 0;
	g_timeSet = false;
	

	rainReceived = false;
	rainStartOfToday = 0;
	lastUpdateTime = now();


	//Temperature setup
	temperatureSensor.begin();
	int numberOfDevices = temperatureSensor.getDeviceCount();
	if (numberOfDevices)
	{
		Serial.print(F("Temperature sensors "));

		for (int i = 0; i<numberOfDevices; i++)
		{
			uint8_t tmp_address[8];
			temperatureSensor.getAddress(tmp_address, i);
			Serial.print(F("Sensor address "));
			Serial.print(i + 1);
			Serial.print(F(": "));
			PrintAddress(tmp_address);
			Serial.println();
		}
	}

	pinMode(A3, INPUT_PULLUP);
	attachPinChangeInterrupt(A3, interruptHandlerPushButton, RISING);



	//pinMode(greenLED, OUTPUT); 
	//pinMode(redLED, OUTPUT);	
	
	//sensors.begin();						 // start up the DS18B20 temp sensor onboard	
	//sensors.requestTemperatures();
	//temp = (sensors.getTempCByIndex(0));	 // get inital temperture reading
	//mintemp = temp; maxtemp = temp;			// reset min and max
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
		if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)	// and no rf errors
		{
			int node_id = (rf12_hdr & 0x1F);

			if (node_id == EMON_NODE)						// === EMONTX ====
			{
				//monitor the reliability of receival
				//int index = (int)(((millis() - last_emontx) / 5050.0) - 1.0);	//expect these 5 seconds apart
				//if (index < 0)
				//	index = 0;
				//if (index >= MAX_TIMES)
				//	index = MAX_TIMES - 1;
				//packetsReceived++;

				emonPayload = *(PayloadEmon*)rf12_data;							// get emontx payload data

				EmonSerial::PrintEmonPayload(&emonPayload, millis() - lastReceived[0]);				// print data to serial
				
				txReceived[0]++;
				lastReceived[0] = millis();				 // set time of last update to now

				power_calculations();					// do the power calculations
			}

			if (node_id == RAIN_NODE)						// ==== RainGauge Jeenode ====
			{
				rainPayload = *(PayloadRain*)rf12_data;	// get emonbase payload data
				
				EmonSerial::PrintRainPayload(&rainPayload, millis() - lastReceived[1] );			 // print data to serial
				lastReceived[1] = millis();
				txReceived[1]++;

				if (!rainReceived)
				{
					rainStartOfToday = rainPayload.rainCount;
					rainReceived = true;
					dailyRainfall = 0;
				}
				if (rainPayload.rainCount < rainStartOfToday)
				{
					// int rollover or emontx has been reset to 0
					dailyRainfall = dailyRainfall + rainPayload.rainCount;
				}
				else
					dailyRainfall = rainPayload.rainCount - rainStartOfToday;

			}


			if (node_id == BASE_NODE)						//emon base. Receives the time
			{
				basePayload = *((PayloadBase*)rf12_data);
				EmonSerial::PrintBasePayload(&basePayload, (millis() - lastReceived[2]));			 // print data to serial
				txReceived[2]++;
				lastReceived[2] = millis();

				setTime(basePayload.time);
				if (startTime == 0)
				{
					startTime = basePayload.time;
				}
				lastUpdateTime = basePayload.time;
				g_timeSet = true;
			}
		}
	}


	//--------------------------------------------------------------------
	// Update the display every 200ms
	//--------------------------------------------------------------------
	if ((millis()-fast_update)>200)
	{
		String str;

		if (pushButton != lastPushButton)
		{
			lcd.clear();
			lastPushButton = pushButton;
		}

		fast_update = millis();

		switch (pushButton)
		{
			case eCurrent:
			{
				lcdInt(0, 0, (unsigned int)emonPayload.power);
				lcdInt(5, 0, (unsigned int)emonPayload.ct1);
				if (rainReceived && dailyRainfall != 0)
				{
					lcd.setCursor(11, 0);
					lcd.print(RainString(str, (rainReceived ? dailyRainfall : 0)));
				}

				//print temperatures
				lcd.setCursor(0, 1);
				//water temperatre
				lcd.print(TemperatureString(str, emonPayload.temperature));

				//inside temperature
				lcd.setCursor(6, 1);
				temperatureSensor.requestTemperatures();
				lcd.print(TemperatureString(str, temperatureSensor.getTempCByIndex(0) * 100));

				//outside temperature
				lcd.setCursor(12, 1);
				lcd.print(TemperatureString(str, rainPayload.temperature));
				break;
			}
			case eRainFall:
			{
				lcdInt(0, 0, (unsigned int)emonPayload.power);
				lcdInt(5, 0, (unsigned int)emonPayload.ct1);
				if (rainReceived && dailyRainfall != 0)
				{
					lcd.setCursor(11, 0);
					lcd.print(RainString(str, (rainReceived ? dailyRainfall : 0)));
				}

				lcd.setCursor(0, 1);
				lcd.print(F("Supply V: "));
				lcd.setCursor(11, 1);
				lcd.print(TemperatureString(str, rainPayload.supplyV/10));
				break;
			}
			case eDateTimeStartRunning:
			{
				lcd.setCursor(5, 0);
				lcd.print(DateString(str, startTime));
				lcd.setCursor(5, 1);
				lcd.print(TimeString(str, startTime));
				break;
			}

			case eDateTimeNow:
			{
				lcd.setCursor(5, 0);
				lcd.print(DateString(str, now()));
				lcd.setCursor(5, 1);
				lcd.print(TimeString(str, now()));
				break;
			}
			case eDiagnosis:
			{
				for (int i = 0; i < MAX_NODES; i++)
				{
					lcdInt(i*5, 0, (unsigned int)txReceived[i]);
					lcd.setCursor(i*5, 1);
					//use TemperatureString to display seconds since last receive
					lcd.print(TemperatureString(str, (unsigned int)((millis() - lastReceived[i]) / 10)));
				}
				break;
			}
			//default:
			//{
			//	lcd.setCursor(0, 1);
			//	lcd.print(F("                "));
			//	break;
			//}
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
				rainStartOfToday = rainPayload.rainCount;
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
	gen = 0; // emontx.gen;	if (gen<100) gen=0;	// remove noise offset 
	consuming = emonPayload.power; 				// for type 1 solar PV monitoring
	grid = emonPayload.power - gen;				// for type 1 solar PV monitoring
	// grid=emontx.grid; 				 	// for type 2 solar PV monitoring					 
	// consuming=gen + emontx.grid; 			// for type 2 solar PV monitoring - grid should be positive when importing and negastive when exporting. Flip round CT cable clap orientation if not
		 
	if (gen > consuming) {
	importing=0; 					//set importing flag 
	grid= grid*-1;					//set grid to be positive - the text 'importing' will change to 'exporting' instead. 
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

void PrintAddress(uint8_t deviceAddress[8])
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

