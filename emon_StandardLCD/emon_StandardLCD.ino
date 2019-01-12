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
#include <Time/Time.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <PinChangeInt.h>				//Library to provide additional interrupts on the Arduino Uno328
#include <EEPROM.h>

#include <EmonShared.h>
#include "EEPROMHist.h"

LiquidCrystal lcd(A2,4, 8,7,6,5);


EEPROMHistory   usageHistory;


//--------------------------------------------------------------------------------------------
// Power variables
//--------------------------------------------------------------------------------------------
int importing;									//flag to indicate import/export
double consuming, gen, grid, wh_gen, wh_consuming;	 //integer variables to store ammout of power currenty being consumed grid (in/out) +gen
unsigned long whtime;									//used to calculate energy used per day (kWh/d)

#define NUM_THERMOMETERS	3		//number of temperature temp	1=water(emon), 2=inside(LCD), 3=outside(rain)
#define MAX_NODES	5				//number of jeenodes, node		1=emon,	2=emonTemperature, 3=rain, 4=base, 5=pulse 
enum { eWater, eInside, eOutside};	//index to temperature array

unsigned int txReceived[MAX_NODES];
time_t lastReceived[MAX_NODES];
int temperature[NUM_THERMOMETERS];


PayloadEmon emonPayload;
PayloadRain rainPayload;
PayloadBase basePayload;
PayloadDisp dispPayload;
PayloadPulse pulsePayload;

RF12Init rf12Init = { DISPLAY_NODE, RF12_915MHZ, 210 };

int thisHour;
time_t					startTime = 0;
byte            currentHour = 0;
byte            currentDay = 0;
byte						currentRainDay = 0;
byte            currentMonth = 0;
byte						currentRainMonth = 0;


unsigned long rainStartOfToday;
bool rainGaugeReadingReceived;
unsigned long dailyRainfall;
time_t	lastUpdateTime;
int			tempLCD;										//temperature of this unit

//---------------------------------------------------------------------------------------------------
// Push button support. On pin A3
//---------------------------------------------------------------------------------------------------
typedef enum {
	eSummary = 0,
	eCurrentPower,
	eTotalPower,
	eCurrentTemperatures,
	eMaxTemperatures,
	eMinTemperatures,
	eRainFall,
	eRainFallTotals,
	eDateTimeNow,
	eDateTimeStartRunning,
	eDiagnosisRainBase,
	eDiagnosisEmons
}  ButtonDisplayMode;

volatile ButtonDisplayMode pushButton = eSummary;
volatile unsigned long	g_RGlastTick = 0;
ButtonDisplayMode lastPushButton = eDiagnosisEmons;


//---------------------------------------------------------------------------------------------------
// Dallas temperature sensor	on pin 5, Jeenode port 2
//---------------------------------------------------------------------------------------------------
OneWire oneWire(A4);
DallasTemperature temperatureSensor(&oneWire);

//-------------------------------------------------------------------------------------------- 
// Flow control
//-------------------------------------------------------------------------------------------- 
#define  SEND_UPDATE_PERIOD			60	//seconds between updates

time_t slow_update;									// Used to count time for slow 10s events
time_t average_update;							// Used to store averages and totals
unsigned long fast_update;					// Used to count time for fast 100ms events


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
	//don't show decimals if more that 100mm (not enough room on display!)
	if (rainGauge < 500)
	{
		str += ".";
		str += (rainGauge % 5) * 2;
	}
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

String TimeSpanString(String& str, time_t timeSpan)
{
	str = "";
	if (timeSpan < 60)
		str += second(timeSpan);
	else if (timeSpan < 60 * 60)
	{
		str += minute(timeSpan);
		str += ".";
		str += second(timeSpan);
	}
	else if (timeSpan < 86400 ) //(60 * 60 * 24)
	{
		str += hour(timeSpan);
		str += ":";
		str += minute(timeSpan);
	}
	else
	{
		str += day(timeSpan);
		str += ".";
		str += hour(timeSpan);
		str += "d";
	}
	while (str.length()<5)
		str = " " + str;
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

	if (period > 200)	//more than 50 ms to avoid switch bounce
	{
		if (pushButton == eDiagnosisEmons)
			pushButton = eSummary;
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

	lcd.print(F("Fewings Power"));
	lcd.setCursor(0, 1);
	lcd.print(F("Monitor 2.0"));

	Serial.println(F("Fewings emonGLCD solar PV monitor - gen and use"));

	Serial.println("rf12_initialize");
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);


	//initialise the day and month total histories from EEPROM memory
	short usesEEPROMto = usageHistory.init(0);
	Serial.print("EEPROM init:");
	Serial.println(usesEEPROMto, DEC);
	lcd.print(".");


	for (int i = 0; i< MAX_NODES; i++)
	{
		txReceived[i] = 0;
		lastReceived[i] = now();
	}

	rainGaugeReadingReceived = false;
	rainStartOfToday = 0;
	lastUpdateTime = now();


	//Temperature sensor setup
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

	EmonSerial::PrintEmonPayload(NULL);
	EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBasePayload(NULL);
	EmonSerial::PrintDispPayload(NULL);
	EmonSerial::PrintPulsePayload(NULL);


	//let the startup LCD display for a while!
	delay(2500);
	
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
	time_t time = now();
	bool refreshScreen = false;	//set true when time to completely redraw the screen
	Serial.print("1");
	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	
	if (rf12_recvDone())
	{
		Serial.print("2");
		if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)	// and no rf errors
		{
			int node_id = (rf12_hdr & 0x1F);

			if (node_id == EMON_NODE)						// === EMONTX ====
			{
				Serial.print("3");
				emonPayload = *(PayloadEmon*)rf12_data;							// get emontx payload data

				EmonSerial::PrintEmonPayload(&emonPayload, (now() - lastReceived[0]));				// print data to serial
				
				txReceived[0]++;
				lastReceived[0] = now();				// set time of last update to now

				//temperature[eWater] = emonPayload.temperature;
				power_calculations_emon();							// do the power calculations
			}
			if (node_id == PULSE_JEENODE)						// === PULSE NODE ====
			{
				Serial.print("X");
				pulsePayload = *(PayloadPulse*)rf12_data;							// get payload data

				EmonSerial::PrintPulsePayload(&pulsePayload, (now() - lastReceived[4]));				// print data to serial

				txReceived[4]++;
				lastReceived[4] = now();				// set time of last update to now

				//temperature[eWater] = emonPayload.temperature;
				power_calculations_pulse();							// do the power calculations
			}
			if (node_id == EMON_TEMP_NODE)
			{
				Serial.print("4");
				PayloadEmon emon2Payload = *(PayloadEmon*)rf12_data;							// get emontx payload data

				EmonSerial::PrintEmonPayload(&emon2Payload, (now() - lastReceived[1]));				// print data to serial

				txReceived[1]++;
				lastReceived[1] = now();				// set time of last update to now

				temperature[eWater] = emon2Payload.temperature;
			}

			if (node_id == RAIN_NODE)						// ==== RainGauge Jeenode ====
			{
				Serial.print("5");
				rainPayload = *(PayloadRain*)rf12_data;	// get emonbase payload data
				
				EmonSerial::PrintRainPayload(&rainPayload, (now() - lastReceived[2]));			 // print data to serial
				lastReceived[2] = now();
				txReceived[2]++;

				temperature[eOutside] = rainPayload.temperature;

				if (!rainGaugeReadingReceived)
				{
					rainStartOfToday = rainPayload.rainCount;
					rainGaugeReadingReceived = true;
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


			if ( node_id == BASE_JEENODE )						// jeenode base Receives the time
			{
				Serial.print("5");
				basePayload = *((PayloadBase*)rf12_data);
				EmonSerial::PrintBasePayload(&basePayload, (now() - lastReceived[3]));			 // print data to serial
				txReceived[3]++;
				lastReceived[3] = now();

				setTime(basePayload.time);
				if (startTime == 0)
				{
					startTime = basePayload.time;
					//time has been updated from the base
					currentHour = hour();
					currentDay = day() - 1;        //note day() base 1, currentDay base 0
					currentMonth = month() - 1;    //note month() base 1, currentMonth base 0
					currentRainDay = currentDay;    //note the rainDay and rainMonth change at 9am!
					currentRainMonth = currentMonth;
					if (currentHour < 9 && currentDay > 0)
					{
						//correct if turned on before 9am! n.b don't wory if the month is wrong!
						currentRainDay = day() - 2;
					}

					//reset the timers as the time has changed
					average_update = now();
					slow_update = now();
				}
				lastUpdateTime = basePayload.time;
			}
		}
	}


	//--------------------------------------------------------------------
	// Update the temperatures every 3s
	//--------------------------------------------------------------------
	if (time >= (slow_update + 3))
	{
		Serial.print("6");

		slow_update = time;

		//get the temperature of this unit (inside temperature)
		temperatureSensor.requestTemperatures();
		temperature[eInside] = temperatureSensor.getTempCByIndex(0) * 100;
	}

	if (time >= (average_update + SEND_UPDATE_PERIOD))
	{
		Serial.print("7");
		average_update = time;

		usageHistory.addMonitoredValues(temperature, 0);

		//update 24hr tallies
		if ((timeStatus() == timeSet))
		{
			//usageHistory.addValue(eHour, currentHour, wattsConsumed, (unsigned short)wattsGenerated);
			Serial.print("8");

			if (hour() != currentHour)
			{
				Serial.print("9");
				unsigned short consumed, generated;
				//we only store the hour totals every hour. THen add it to the current hour and to the current day
				usageHistory.getTotalTo(eHour, currentHour, &consumed, &generated);
				usageHistory.addValue(eHour, currentHour, wh_consuming - consumed, wh_gen - generated);
				usageHistory.addValue(eDay, currentDay, wh_consuming - consumed, wh_gen - generated);

				//rainfall is measured from 9am
				if (hour() == 9)
				{
					Serial.print("A");
					usageHistory.addRainfall(eDay, currentRainDay, dailyRainfall);
					usageHistory.addRainfall(eMonth, currentRainMonth, dailyRainfall );

					rainStartOfToday = rainPayload.rainCount;
					dailyRainfall = 0;

					if (month() - 1 != currentRainMonth)
					{
						currentRainMonth = month() - 1;
						usageHistory.resetRainfall(eMonth, currentRainMonth);
					}
					currentRainDay = day() - 1;
					usageHistory.resetRainfall(eDay, currentRainDay);
				}


				if (day() - 1 != currentDay)
				{
					Serial.print("B");
					usageHistory.resetMonitoredValues();
					
					//reset daily totals
					wh_gen = 0;
					wh_consuming = 0;

					usageHistory.getValue(eDay, currentDay, &consumed, &generated);
					usageHistory.addValue(eMonth, currentMonth, consumed, generated);

					if (month() - 1 != currentMonth)
					{
						currentMonth = month() - 1;
						usageHistory.resetValue(eMonth, currentMonth);
					}

					currentDay = day() - 1;
					usageHistory.resetValue(eDay, currentDay);
				}

				currentHour = hour();
				usageHistory.resetValue(eHour, currentHour);

			}
			//send the temperature every 60 seconds
			dispPayload.temperature = temperature[eInside];
	
			int i = 0;
			while (!rf12_canSend() && i < 100)
			{
				i++;
			}
			Serial.print("C");
			if (i < 100)
			{
				rf12_sendStart(0, &dispPayload, sizeof(PayloadDisp));
				rf12_sendWait(0);
				EmonSerial::PrintDispPayload(&dispPayload, SEND_UPDATE_PERIOD);
				Serial.print("D");
			}

			Serial.print("E");
			refreshScreen = true;	//every 60 seconds
		}
	}
	//--------------------------------------------------------------------
	// Update the display every 200ms
	//--------------------------------------------------------------------
	if ((millis()-fast_update)>200)
	{
		Serial.print("F");
		String str;

		fast_update = millis();
		

		//clear the screen if the button has been pushed
		if (pushButton != lastPushButton)
		{
			lcd.clear();
			lastPushButton = pushButton;
		}

		if (refreshScreen)
		{
			Serial.print("G");
			lcd.clear();
		}

		switch (pushButton)
		{
		case eSummary:
			{
				Serial.print("H");

				lcdInt(0, 0, (unsigned int)pulsePayload.power[2]);
				lcdInt(5, 0, (unsigned int)pulsePayload.power[1]);

				lcd.setCursor(0,0);
				lcd.print( txReceived[4]%2 ? "*" : " "); //toggle "*" every time a pulseNodeTx received. Every second

				if (rainGaugeReadingReceived && dailyRainfall != 0)
				{
					lcd.setCursor(11, 0);
					lcd.print(RainString(str, (rainGaugeReadingReceived ? dailyRainfall : 0)));
					lcd.print(F("mm"));
				}

				//print temperatures
				lcd.setCursor(0, 1);
				//water temperatre
				lcd.print(TemperatureString(str, temperature[eWater]));

				//inside temperature
				lcd.setCursor(6, 1);
				lcd.print(TemperatureString(str, temperature[eInside]));

				//outside temperature
				lcd.setCursor(12, 1);
				lcd.print(TemperatureString(str, temperature[eOutside]));
				break;
			}
		case eCurrentPower:
		{
			lcd.setCursor(0, 0);
			lcd.print(F("Cur: Consmd Prod"));
			lcdInt(0, 1, (unsigned int)pulsePayload.power[2]);
			lcdInt(8, 1, (unsigned int)pulsePayload.power[1]);
			break;
		}
		case eTotalPower:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Tot: Consmd Prod"));
				lcdInt(0, 1, (unsigned int)wh_consuming);
				lcdInt(8, 1, (unsigned int)wh_gen);
				break;
		}
			case eCurrentTemperatures:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Cur: Wtr In  Out"));
				//print temperatures
				lcd.setCursor(0, 1);
				//water temperatre
				lcd.print(TemperatureString(str, temperature[eWater]));

				//inside temperature
				lcd.setCursor(6, 1);
				lcd.print(TemperatureString(str, temperature[eInside]));

				//outside temperature
				lcd.setCursor(12, 1);
				lcd.print(TemperatureString(str, temperature[eOutside]));
				break;
			}
			case eMinTemperatures:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Min: Wtr In  Out"));
				//print temperatures
				lcd.setCursor(0, 1);

				int minTemp[3];
				usageHistory.getMonitoredValues(eValueStatisticMin, minTemp, NULL);
				//water temperatre
				lcd.print(TemperatureString(str, minTemp[eWater]));

				//inside temperature
				lcd.setCursor(6, 1);
				lcd.print(TemperatureString(str, minTemp[eInside]));

				//outside temperature
				lcd.setCursor(12, 1);
				lcd.print(TemperatureString(str, minTemp[eOutside]));
				break;
			}
			case eMaxTemperatures:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Max: Wtr In  Out"));
				//print temperatures
				lcd.setCursor(0, 1);

				int maxTemp[3];
				usageHistory.getMonitoredValues(eValueStatisticMax, maxTemp, NULL);

				//water temperatre
				lcd.print(TemperatureString(str, maxTemp[eWater]));

				//inside temperature
				lcd.setCursor(6, 1);
				lcd.print(TemperatureString(str, maxTemp[eInside]));

				//outside temperature
				lcd.setCursor(12, 1);
				lcd.print(TemperatureString(str, maxTemp[eOutside]));
				break;
			}
			case eRainFall:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Rain today:"));
				lcd.setCursor(11, 0);
				lcd.print(RainString(str, (rainGaugeReadingReceived ? dailyRainfall : 0)));
				lcd.print(F("mm"));

				lcd.setCursor(0, 1);
				lcd.print(F("Supply V  : "));
				lcd.setCursor(11, 1);
				lcd.print(TemperatureString(str, rainPayload.supplyV/10));
				break;
			}
			case eRainFallTotals:
			{
				unsigned short totalRain = (rainGaugeReadingReceived ? dailyRainfall : 0);

				lcd.setCursor(0, 0);
				lcd.print(F("Day  Month Year"));
				lcd.setCursor(0, 1);

				lcd.print(RainString(str, totalRain));
				
				totalRain += usageHistory.getRainfallTo(eDay, currentRainDay);
				lcd.setCursor(5, 1);
				lcd.print(RainString(str, totalRain));

				totalRain = (rainGaugeReadingReceived ? dailyRainfall : 0);
				totalRain += usageHistory.getRainfallTo(eMonth, currentRainMonth);
				lcd.setCursor(10, 1);
				lcd.print(RainString(str, totalRain ));
				break;
			}
			case eDateTimeStartRunning:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Start:"));
				lcd.print(DateString(str, startTime));
				lcd.setCursor(5, 1);
				lcd.print(TimeString(str, startTime));
				break;
			}
			case eDateTimeNow:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Time :"));
				lcd.print(DateString(str, now()));
				lcd.setCursor(5, 1);
				lcd.print(TimeString(str, now()));
				break;
			}
			case eDiagnosisRainBase:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Rain"));
				lcd.setCursor(0, 1);
				lcd.print(F("Base"));
				for (int i = 2; i < 4; i++)
				{
					lcdInt(4, i % 2, (unsigned int)txReceived[i]);
					lcd.setCursor(10, i % 2);
					lcd.print(TimeSpanString(str, (now() - lastReceived[i])));
				}
				break;
			}
			case eDiagnosisEmons:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Emon1"));
				lcd.setCursor(0, 1);
				lcd.print(F("Emon2"));
				for (int i = 0; i < 2; i++)
				{
					lcdInt(4, i % 2, (unsigned int)txReceived[i]);
					lcd.setCursor(10, i % 2);
					lcd.print(TimeSpanString(str, (now() - lastReceived[i])));
				}
				break;
			}
		}
		Serial.print("I");
	}
	Serial.print(".");
} //end loop
//--------------------------------------------------------------------------------------------

//--------------------------------------------------------------------
// Calculate power and energy variables
//--------------------------------------------------------------------
void power_calculations_emon()
{
	//--------------------------------------------------
	// kWh calculation
	//--------------------------------------------------
	unsigned long lwhtime = whtime;
	whtime = millis();
	double whInc = emonPayload.ct1 * ((whtime-lwhtime)/3600000.0);
	wh_gen=wh_gen+whInc;
	whInc = emonPayload.power *((whtime-lwhtime)/3600000.0);
	wh_consuming=wh_consuming+whInc;
}

void power_calculations_pulse()
{
	//--------------------------------------------------
	// kWh calculation
	//--------------------------------------------------
	unsigned long lwhtime = whtime;
	whtime = millis();
	double whInc = pulsePayload.power[1] * ((whtime - lwhtime) / 3600000.0);  //solar comes in on pin 2
	wh_gen = wh_gen + whInc;
	whInc = pulsePayload.power[2] *((whtime - lwhtime) / 3600000.0);					//main power comes in on pin 3
	wh_consuming = wh_consuming + whInc;
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

