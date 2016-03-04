//------------------------------------------------------------------------------------------------------------------------------------------------
// emonBase on JeeNode S Fewings, Jan 2016
// Listens to emon traffic and publishes on serial port
// Listens to serial port and extracts time to publish on emon traffic
// This is an interface JeeNode that sits next to the original house monitor

// emonGLCD documentation http://openEnergyMonitor.org/emon/emonglcd

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
#include <Time.h>
#include <EmonShared.h>


//--------------------------------------------------------------------------------------------
// Workaround for http://gcc.gnu.org/bugzilla/show_bug.cgi?id=34734
//remove compiler warning "Warning: only initialized variables can be placed into program memory area" from 
//	Serial.println(F("string literal"));
#ifdef PROGMEM
#undef PROGMEM
#define PROGMEM __attribute__((section(".progmem.data")))
#endif
//--------------------------------------------------------------------------------------------

PayloadEmon emonPayload;	
PayloadBase basePayload;
PayloadRain rainPayload;
PayloadDisp dispPayload;


RF12Init rf12Init = { BASE_JEENODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

//--------------------------------------------------------------------------------------------
//Raifall variables
//--------------------------------------------------------------------------------------------
bool rainReceived;														//true after we have received an input from the rain gauge
unsigned long dailyRainfall;									//amount of rain today
unsigned long dayStartRainfall;								//raingauge counter at start of day recording

//--------------------------------------------------------------------------------------------
// Power variables
//--------------------------------------------------------------------------------------------
double wh_gen, wh_consuming;							//integer variables to store ammout of power currenty being consumed grid (in/out) +gen
unsigned long whtime;											//used to calculate energy used per day (kWh/d)
//unsigned int pktsReceived;


//--------------------------------------------------------------------------------------------
// Software RTC setup
//-------------------------------------------------------------------------------------------- 
//RTC_Millis RTC;
int thisHour;
	
//-------------------------------------------------------------------------------------------- 
// Flow control
//-------------------------------------------------------------------------------------------- 
unsigned long last_emontx;					// Used to count time from last emontx update
unsigned long last_rainTx;
unsigned long last_dispTx; 

unsigned long slow_update;					// Used to count time for slow 10s events
unsigned long fast_update;					// Used to count time for fast 100ms events


//-------------------------------------------------------------------------------------------- 
// Serial string parsing
//-------------------------------------------------------------------------------------------- 
#define MAX_SERIAL_STRING 60
char serialIn[MAX_SERIAL_STRING];
int serialInIndex = 0;

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
	Serial.begin(9600);
	
	delay(2000);
	Serial.println(F("Fewings Jeenode emon based on openenergymonitor.org"));


	Serial.println(F("rf12_initialize"));
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);

	EmonSerial::PrintEmonPayload(NULL);
	EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintDispPayload(NULL);


	rainReceived = false;
	dailyRainfall = 0;
	dayStartRainfall = 0;

	slow_update = millis();
	fast_update = millis();

	last_emontx = millis();
	last_rainTx = millis();
	last_dispTx = millis();


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
				//pktsReceived++;

				emonPayload = *(PayloadEmon*) rf12_data;		// get emontx payload data
				EmonSerial::PrintEmonPayload(&emonPayload, millis() - last_emontx);				// print data to serial
				last_emontx = millis();				 // set time of last update to now
			
				power_calculations();					// do the power calculations
			}
		
			if (node_id == RAIN_NODE)						// ==== RainGauge Jeenode ====
			{
				rainPayload = *(PayloadRain*)rf12_data;								// get emonbase payload data
				EmonSerial::PrintRainPayload(&rainPayload, millis() - last_rainTx);			 // print data to serial
				last_rainTx = millis();

				if (!rainReceived)
				{
					dayStartRainfall = rainPayload.rainCount;
					rainReceived = true;
					dailyRainfall = 0;
				}
			}
			if (node_id == DISPLAY_NODE)
			{
				dispPayload = *(PayloadDisp*)rf12_data;
				EmonSerial::PrintDispPayload(&dispPayload, millis() - last_dispTx);			 // print data to serial
				last_dispTx = millis();
			}

			//flash the LED
			digitalWrite(4, HIGH);
			delay(100);
			digitalWrite(4, LOW);
		}
	}


	while (Serial.available())
	{
		serialIn[serialInIndex++] = Serial.read();
		if (serialInIndex >= MAX_SERIAL_STRING - 1)
			serialInIndex = 0;		//overflow the buffer
		if (serialIn[serialInIndex - 1] == '\n')	//end of line
		{
			serialIn[serialInIndex] = 0; //null terminate
			Serial.println();
			char* node = strchr(serialIn, ':');
			if (node != 0)
			{
				if (0 == strncmp(node - 4, "base:",5))
				{
					if (EmonSerial::ParseBasePayload(node - 4, &basePayload))
					{
						setTime(basePayload.time);
						Serial.print("SetTime from serial:");
						Serial.println(now());
						EmonSerial::PrintBasePayload(&basePayload, 10);

						slow_update = millis() - 10001;  //force an update to be broadcast!
					}
				}
			}
			serialInIndex = 0;
		}
	}
	
	//--------------------------------------------------------------------
	// 
	//--------------------------------------------------------------------
	if ((millis()-slow_update)>10000)
	{		//Things to do every 10s
		slow_update = millis();

		while (!rf12_canSend())
			rf12_recvDone();
		if ((timeStatus() == timeSet))
		{
			basePayload.time = now();

			rf12_sendStart(0, &basePayload, sizeof(PayloadBase));
			rf12_sendWait(0);

			EmonSerial::PrintBasePayload(&basePayload, 10);
		}
	}


	int lastHour = thisHour;
	thisHour = hour();
	if (lastHour == 23 && thisHour == 00)
	{
		wh_gen = 0;
		wh_consuming = 0;
	}

	if (rainReceived)
	{
		if (lastHour == 8 && thisHour == 9)
		{
			dayStartRainfall = rainPayload.rainCount;
			dailyRainfall = 0;
		}
		if (rainPayload.rainCount < dayStartRainfall)
		{
			// int rollover or emontx has been reset to 0
			dailyRainfall = dailyRainfall + rainPayload.rainCount;
		}
		else
		{
			dailyRainfall = rainPayload.rainCount - dayStartRainfall;
		}
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
	double whInc = emonPayload.ct1 * ((whtime - lwhtime) / 3600000.0);
	wh_gen=wh_gen+whInc;
	whInc = emonPayload.power *((whtime - lwhtime) / 3600000.0);
	wh_consuming=wh_consuming+whInc;
}

String RainString(String& str, int rainGauge)
{
	//raingauge increments in 0.2mm per value
	str = "";
	str += (int) (rainGauge / 5);
	str += ".";
	str += (rainGauge % 5) * 2;
	return str;
}

String TemperatureString(String& str, int temperature )
{
	str = "";
	int t = temperature;
	if( t < 0 )
	{
		str = "-";
		t *= -1;
		str += t/100;
	}
	else
		str += t/100;

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
	str += "		";
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
	str += "	";
	return str;
}

void SerialPrint_P(const prog_char* str)
{
	for (uint8_t c; (c = pgm_read_byte(str)); str++) 
		Serial.write(c);
}