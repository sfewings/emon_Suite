//------------------------------------------------------------------------------------------------------------------------------------------------
// Fewings emon_StandardLCD
// S Fewings  Jun 2019

// Originally based on emonGLCD documentation http://openEnergyMonitor.org/emon/emonglcd
// Authors: Glyn Hudson and Trystan Lea
// Part of the: openenergymonitor.org project
// Licenced under GNU GPL V3
// http://openenergymonitor.org/emon/license
// GLCD library by Jean-Claude Wippler: JeeLabs.org
// 2010-05-28 <jcw@equi4.com> http://opensource.org/licenses/mit-license.php

//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <LiquidCrystal.h>
#include <TimeLib.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <PinChangeInterrupt.h>
//#include <PinChangeInt.h>				//Library to provide additional interrupts on the Arduino Uno328
#include <EEPROM.h>

#include <EmonShared.h>
#include <EmonEEPROM.h>

#include <SPI.h>
#include <RH_RF69.h>
#include <avr/wdt.h>    //watchdog timer


// Singleton instance of the radio driver
RH_RF69 g_rf69;


LiquidCrystal lcd(A2,4, 8,7,6,5);

//--------------------------------------------------------------------------------------------
// Power variables
//--------------------------------------------------------------------------------------------
double wh_gen, wh_consuming;	 
unsigned long whtime;						//used to calculate energy used per day (kWh/d)

#define NUM_THERMOMETERS	3		//number of temperature temp	1=water(emon), 2=inside(LCD), 3=outside(rain)
#define MAX_NODES	17				//number of node		1=emon,	2=emonTemperature, 3=rain, 4=base, 5=pulse, 6=hws 
enum { eTemp0, eTemp1, eTemp2, eTemp3, eDisp0, eDisp1, eDisp2, eDisp3, eRain, eBase, ePulse, eHWS, eWaterNode0, eWaterNode1, eWaterNode2, eWaterNode3 , eScale};	//index into txReceived and lastReceived
enum { eWaterTemp, eInside, eOutside};								//index to temperature array

unsigned int txReceived[MAX_NODES];
time_t lastReceived[MAX_NODES];
int temperature[NUM_THERMOMETERS];


PayloadRain rainPayload;
PayloadBase basePayload;
PayloadPulse pulsePayload;
PayloadHWS hwsPayload;
PayloadWater waterPayload[MAX_SUBNODES];
PayloadScale scalePayload;
PayloadDisp dispPayload[MAX_SUBNODES];
PayloadTemperature temperaturePayload[MAX_SUBNODES];


EEPROMSettings  eepromSettings;

int 	thisHour;
time_t	startTime = 0;
byte    currentHour = 0;
byte    currentDay = 0;
byte	currentRainDay = 0;

unsigned long rainStartOfToday;

time_t		lastUpdateTime;
bool		refreshScreen = false;	//set true when time to completely redraw the screen

bool		dogHasBeenFed = false;
long 		lastDogFoodReading = 0;
//---------------------------------------------------------------------------------------------------
// Push button support. On pin A3
//---------------------------------------------------------------------------------------------------
typedef enum {
	eSummary = 0,
	eCurrentPower,
	eTotalPower,
	eCurrentTemperatures,
	eRainFall,
	eDateTimeNow,
	eDateTimeStartRunning,
	eDiagnosisRainBase,
	eDiagnosisPulseHWS,
	eDiagnosisDisp,
	eDiagnosisTempEmons,
	eDiagnosisWater,
	eDiagnosisScale,
	eDiagnosisEEPROMSettings
}  ButtonDisplayMode;

volatile ButtonDisplayMode pushButton = eSummary;  //set this to the startup display
volatile unsigned long	g_RGlastTick = 0;
ButtonDisplayMode lastPushButton = eDiagnosisEEPROMSettings;


//---------------------------------------------------------------------------------------------------
// Dallas temperature sensor	on pin 5, Jeenode port 2
//---------------------------------------------------------------------------------------------------
OneWire oneWire(A4);
DallasTemperature temperatureSensor(&oneWire);
int numberOfTemperatureSensors = 0;

//-------------------------------------------------------------------------------------------- 
// Flow control
//-------------------------------------------------------------------------------------------- 
#define  SEND_UPDATE_PERIOD			60  //60	//seconds between updates

time_t slow_update;									// Used to count time for slow 10s events
time_t average_update;							// Used to store averages and totals
unsigned long fast_update;					// Used to count time for fast 100ms events


static void lcdUint (byte x, byte y, unsigned int value, char fill =' ') 
{
	lcd.setCursor(x, y);
	int places = log10(value);
	for(int i=0; i<4-places;i++)
	lcd.print(fill);
	lcd.print(value);	
}	

static void lcdLong(byte x, byte y, long value, char fill = ' ')
{
	lcd.setCursor(x, y);
	int places = 0;
	if (value < 0)
		places = 1; //for -ve sign
	places += log10(abs(value));
	for (int i = 0; i < 4 - places; i++)
		lcd.print(fill);
	lcd.print(value);
}

void lcdSupplyV(byte line, unsigned long supplyV)
{
	String str;

	lcd.setCursor(0, line);
	lcd.print(F("Supply V :"));
	lcd.setCursor(9, line);
	lcd.print(TemperatureString(str, supplyV / 10));
}

void lcdDiagnosis(byte line, const __FlashStringHelper* text, uint16_t index)
{
	String str;

	lcd.setCursor(0, line);
	lcd.print(text);
	lcdUint(4, line, txReceived[index]);
	lcd.setCursor(10, line);
	lcd.print(TimeSpanString(str, (now() - lastReceived[index])));
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


//--------------------------------------------------------------------
// Calculate power and energy variables
//--------------------------------------------------------------------
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
		if(period >10000)
			pushButton = eSummary; //if press is after 10 seconds, return to summary
		else if (pushButton == eDiagnosisEEPROMSettings)
			pushButton = eSummary;
		else
			pushButton = (ButtonDisplayMode)((int)pushButton + 1);
	}
}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup()
{
	Serial.begin(9600);

	lcd.begin(16, 2);
	lcd.setCursor(0, 0);

	lcd.print(F("Fewings Power"));
	lcd.setCursor(0, 1);
	lcd.print(F("Monitor 4.2"));

	Serial.println(F("Fewings emon LCD monitor - gen and use"));

	//initialise the EEPROMSettings for relay and node number
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	if (eepromSettings.relayNumber)
		dispPayload[eepromSettings.subnode].relay = 1 << (eepromSettings.relayNumber-1);
	else
		dispPayload[eepromSettings.subnode].relay = 0;

	if (eepromSettings.subnode)
	{
		lcd.setCursor(12, 1);
		lcd.print(F("n="));
		lcd.print(eepromSettings.subnode);
		//set the subnode of all packets sent from us
		dispPayload[eepromSettings.subnode].subnode = eepromSettings.subnode;
	}

	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(DISPLAY_NODE);

	Serial.print("RF69 initialise node: ");
	Serial.print(DISPLAY_NODE);
	Serial.println(" Freq: 915MHz");


	for (int i = 0; i< MAX_NODES; i++)
	{
		txReceived[i] = 0;
		lastReceived[i] = now();
	}

	rainPayload.rainCount = rainStartOfToday = 0;

	lastUpdateTime = now();


	//Temperature sensor setup
	temperatureSensor.begin();
	numberOfTemperatureSensors = temperatureSensor.getDeviceCount();
	if (numberOfTemperatureSensors)
	{
		Serial.print(F("Temperature sensors "));

		for (int i = 0; i< numberOfTemperatureSensors; i++)
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
	else
	{
		Serial.println(F("No temperature sensors found"));
	}

	temperature[eWaterTemp] = 0;
	temperature[eInside] = 0;
	temperature[eOutside] = 0;

	wh_gen = 0;
	wh_consuming = 0;

	//pushbutton configuration
	pinMode(A3, INPUT_PULLUP);
	//attachPinChangeInterrupt(A3, interruptHandlerPushButton, RISING);
  attachPCINT(digitalPinToPCINT(A3),interruptHandlerPushButton, RISING);
  
  EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBasePayload(NULL);
	EmonSerial::PrintDispPayload(NULL);
	EmonSerial::PrintPulsePayload(NULL);
	EmonSerial::PrintHWSPayload(NULL);
	EmonSerial::PrintWaterPayload(NULL);
	EmonSerial::PrintScalePayload(NULL);

	average_update = now();
	slow_update = now();

	//let the startup LCD display for a while!
	delay(2500);

  	wdt_enable(WDTO_8S);
}
//--------------------------------------------------------------------------------------------


//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	wdt_reset();

	time_t time = now();
	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	volatile uint8_t *data = NULL;
	uint8_t buf[66];
	int node_id= -1;
	byte len = 0;
	bool okToRelay = false;

	if (g_rf69.available())
	{
		len = RH_RF69_MAX_MESSAGE_LEN;  //ASSERT( len <= sizeof(buf));
		if (g_rf69.recv(buf, &len))
		{
			node_id = g_rf69.headerId();
			//Serial.print("RSSI: ");
			//Serial.print(g_rf69.lastRssi(), DEC);
			//Serial.print(", node: ");
			//Serial.println(node_id);
		}
	}

	if( node_id != -1)
	{
		if (node_id == PULSE_JEENODE && len == sizeof(PayloadPulse)) // === PULSE NODE ====
		{
			pulsePayload = *(PayloadPulse*)buf;							// get payload data

			EmonSerial::PrintPulsePayload(&pulsePayload, (now() - lastReceived[ePulse]));				// print data to serial

			txReceived[ePulse]++;
			lastReceived[ePulse] = now();				// set time of last update to now

			power_calculations_pulse();							// do the power calculations
			okToRelay = true;
		}
		if (node_id == TEMPERATURE_JEENODE && len == sizeof(PayloadTemperature))
		{
			PayloadTemperature tpl = *((PayloadTemperature*)buf);
			byte subnode = tpl.subnode;
			if (subnode >= MAX_SUBNODES)
			{
				Serial.print(F("Invalid temperature subnode. Exiting"));
				return;
			}
			memcpy(&temperaturePayload[subnode], &tpl, sizeof(PayloadTemperature));
			EmonSerial::PrintTemperaturePayload(&temperaturePayload[subnode], (now() - lastReceived[eTemp0+subnode]));				// print data to serial

			txReceived[eTemp0 + subnode]++;
			lastReceived[eTemp0 + subnode] = now();				// set time of last update to now

			okToRelay = true;
		}

		if (node_id == HWS_JEENODE  && len == sizeof(PayloadHWS))
		{
			PayloadHWS hwsPayload = *(PayloadHWS*)buf;							// get emontx payload data

			EmonSerial::PrintHWSPayload(&hwsPayload, (now() - lastReceived[eHWS]));				// print data to serial

			txReceived[eHWS]++;
			lastReceived[eHWS] = now();				// set time of last update to now

			temperature[eWaterTemp] = 100* (int)hwsPayload.temperature[2];  //T3 . Multiply by 100 as temperature[] are in 100ths of degree

			okToRelay = true;
		}

		if (node_id == RAIN_NODE && len == sizeof(PayloadRain))						// ==== RainGauge Jeenode ====
		{
			rainPayload = *(PayloadRain*)buf;	// get emonbase payload data
			
			EmonSerial::PrintRainPayload(&rainPayload, (now() - lastReceived[eRain]));			 // print data to serial
			lastReceived[eRain] = now();
			txReceived[eRain]++;

			temperature[eOutside] = rainPayload.temperature;

			okToRelay = true;

			if (rainStartOfToday == 0)
			{
				rainStartOfToday = rainPayload.rainCount;
			}
		}

		if (node_id == WATERLEVEL_NODE)
		{
			PayloadWater wpl = *(PayloadWater*)buf;							// get emontx payload data
			int packedSize = EmonSerial::UnpackWaterPayload((byte*)&wpl, &wpl);				// we are able to unpack this into the same structure!
			if( len == packedSize)
			{
				byte subnode = wpl.subnode;
				if (subnode >= MAX_SUBNODES)
				{
					Serial.print(F("Invalid water subnode. Exiting"));
					return;
				}
				memcpy(&waterPayload[subnode], &wpl, sizeof(PayloadWater));
				EmonSerial::PrintWaterPayload(&waterPayload[subnode], (now() - lastReceived[eWaterNode0 + subnode]));				// print data to serial

				txReceived[eWaterNode0 + subnode]++;
				lastReceived[eWaterNode0 + subnode] = now();				// set time of last update to now
	
				okToRelay = true;
			}
		}

		if (node_id == SCALE_NODE && len == sizeof(PayloadScale))
		{
			scalePayload = *(PayloadScale*)buf;							// get emontx payload data

			if( scalePayload.subnode == 0 )
			{
				if(lastDogFoodReading - scalePayload.grams > 150 )
					dogHasBeenFed = true;	//more than 150gram drop in dog food scales
				lastDogFoodReading = scalePayload.grams;	
			}
			
			EmonSerial::PrintScalePayload(&scalePayload, (now() - lastReceived[eScale]));				// print data to serial
			txReceived[eScale]++;
			lastReceived[eScale] = now();				// set time of last update to now

			okToRelay = true;
		}

		if (node_id == DISPLAY_NODE && len == sizeof(PayloadDisp))
		{
			PayloadDisp dp = *(PayloadDisp*)buf;							// get emontx payload data

			byte subnode = dp.subnode;
			if (subnode >= MAX_SUBNODES)
			{
				Serial.print(F("Invalid display subnode. Exiting"));
				return;
			}
			memcpy(&dispPayload[subnode], &dp, sizeof(PayloadDisp));
			EmonSerial::PrintDispPayload(&dispPayload[subnode]);			 // print data to serial

			txReceived[eDisp0 + subnode]++;
			lastReceived[eDisp0 + subnode] = now();				// set time of last update to now

			okToRelay = true;
		}

		if ( node_id == BASE_JEENODE && len == sizeof(PayloadBase))						// jeenode base Receives the time
		{
			basePayload = *((PayloadBase*)buf);
			EmonSerial::PrintBasePayload(&basePayload, (now() - lastReceived[eBase]));			 // print data to serial
			txReceived[eBase]++;
			lastReceived[eBase] = now();

			setTime(basePayload.time);
			if (startTime == 0)
			{
				startTime = basePayload.time;
				//time has been updated from the base
				currentHour = hour();
				currentDay = day() - 1;        //note day() base 1, currentDay base 0
				currentRainDay = currentDay;    //note the rainDay and rainMonth change at 9am!
				dogHasBeenFed = false;
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

			okToRelay = true;
		}

		//resend the incoming packets of rain, temperature and HWS systems. These are at the outer extents fo the house
		if (eepromSettings.relayNumber && okToRelay)
		{
			PayloadRelay* pRelayPayload = (PayloadRelay*)buf;
			//check if we havn't already relayed this packet!
			if ((pRelayPayload->relay & (1 << (eepromSettings.relayNumber-1))) == 0)
			{
				//check that the node is one we are listed to relay
				if (((long)1 << node_id) & eepromSettings.relayNodes)
				{
					delay(10);
					// switch the outgoing node to the incoming node ID.
					g_rf69.setHeaderId(node_id);
					Serial.print("Relay packet "); EmonEEPROM::PrintNode(Serial, node_id); Serial.println();
					//set the bit in the relay byte to our relayNumber ID
					pRelayPayload->relay |= (1 << (eepromSettings.relayNumber-1));

					g_rf69.send((const uint8_t*) buf, len);
					if( g_rf69.waitPacketSent() )
					{
						Serial.println("Packet Resent");
					}
					else
					{
						Serial.println(F("No packet sent"));
					}
					//reset our node ID
					g_rf69.setHeaderId(DISPLAY_NODE);
				}
			}
		}
	}
	

	//--------------------------------------------------------------------
	// Update the temperatures every 3s
	//--------------------------------------------------------------------
	if (time >= (slow_update + 3))
	{
		slow_update = time;

		//get the temperature of this unit (inside temperature)
		temperatureSensor.requestTemperatures();
		temperature[eInside] = temperatureSensor.getTempCByIndex(0) * 100;
	}

	if (time >= (average_update + SEND_UPDATE_PERIOD))
	{
		average_update = time;

		//update 24hr tallies
		if ((timeStatus() == timeSet))
		{
			if (hour() != currentHour)
			{
				//rainfall is measured from 9am
				if (hour() == 9)
				{
					rainStartOfToday = rainPayload.rainCount;
				}


				if (day() - 1 != currentDay)
				{
					//reset daily totals
					wh_gen = 0;
					wh_consuming = 0;
					whtime = millis();

					currentDay = day() - 1;
					dogHasBeenFed = false;
				}

				currentHour = hour();
			}

			refreshScreen = true;	//every 60 seconds
		}
		if (numberOfTemperatureSensors)
		{
#ifdef USE_JEELIB
			int wait = 1000;
			while (!rf12_canSend() && --wait)
				;
			if (wait)
			{
				//send the temperature every 60 seconds
				dispPayload[eepromSettings.subnode].temperature = temperature[eInside];

				rf12_sendStart(0, &dispPayload[eepromSettings.subnode], sizeof(PayloadDisp));
				rf12_sendWait(0);
				EmonSerial::PrintDispPayload(&dispPayload[eepromSettings.subnode], SEND_UPDATE_PERIOD);
			}
#else
			//send the temperature every 60 seconds
			dispPayload[eepromSettings.subnode].temperature = temperature[eInside];
			
			g_rf69.send((const uint8_t*) &dispPayload[eepromSettings.subnode], sizeof(PayloadDisp));
			if( g_rf69.waitPacketSent() )
			{
				EmonSerial::PrintDispPayload(&dispPayload[eepromSettings.subnode], SEND_UPDATE_PERIOD);
			}
			else
			{
				Serial.println(F("No packet sent"));
			}
#endif
		}
	}
	//--------------------------------------------------------------------
	// Update the display every 200ms
	//--------------------------------------------------------------------
	if ((millis()-fast_update)>200)
	{
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
			lcd.clear();
			refreshScreen = false;
		}

		switch (pushButton)
		{
		case eSummary:
			{
				lcdUint(0, 0, (unsigned int)pulsePayload.power[2]);
				lcdUint(5, 0, (unsigned int)pulsePayload.power[1]);

				lcd.setCursor(0,0);
				lcd.print( txReceived[ePulse]%2 ? "*" : (dogHasBeenFed ? "+" : " ")); //toggle "*" every time a pulseNodeTx received. Every second

				if (rainPayload.rainCount - rainStartOfToday != 0)
				{
					lcd.setCursor(11, 0);
					lcd.print(RainString(str, rainPayload.rainCount - rainStartOfToday));
					lcd.print(F("mm"));
				}

				//print temperatures
				lcd.setCursor(0, 1);
				//water temperatre
				lcd.print(TemperatureString(str, temperature[eWaterTemp]));

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
			lcdUint(0, 1, (unsigned int)pulsePayload.power[2]);
			lcdUint(8, 1, (unsigned int)pulsePayload.power[1]);
			break;
		}
		case eTotalPower:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Tot: Consmd Prod"));
				lcdUint(0, 1, (unsigned int)wh_consuming);
				lcdUint(8, 1, (unsigned int)wh_gen);
				break;
		}
			case eCurrentTemperatures:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Cur: Wtr In  Out"));
				//print temperatures
				lcd.setCursor(0, 1);
				//water temperatre
				lcd.print(TemperatureString(str, temperature[eWaterTemp]));

				//inside temperature
				lcd.setCursor(6, 1);
				lcd.print(TemperatureString(str, temperature[eInside]));

				//outside temperature
				lcd.setCursor(12, 1);
				lcd.print(TemperatureString(str, temperature[eOutside]));

				break;
			}

			case eRainFall:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Rain today:"));
				lcd.setCursor(11, 0);
				lcd.print(RainString(str, rainPayload.rainCount - rainStartOfToday));
				lcd.print(F("mm"));

				lcdSupplyV(1, rainPayload.supplyV);
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
				lcdDiagnosis(0, F("Rain"), eRain);
				lcdDiagnosis(1, F("Base"), eBase);
				break;
			}
			case eDiagnosisPulseHWS:
			{
				lcdDiagnosis(0, F("Puls"), ePulse);
				lcdDiagnosis(1, F("HWS"), eHWS);
				break;
			}
			case eDiagnosisScale:
			{
				lcdDiagnosis(0, F("Scl"), eScale);
				break;
			}
			case eDiagnosisDisp:
			{
				switch (eepromSettings.subnode)
				{
				case 0:
					lcdDiagnosis(0, F("Dsp1"), eDisp1);
					lcdDiagnosis(1, F("Dsp3"), eDisp3);
					break;
				case 1:
					lcdDiagnosis(0, F("Dsp0"), eDisp0);
					lcdDiagnosis(1, F("Dsp3"), eDisp3);
					break;
				case 2:
				case 3:
					lcdDiagnosis(0, F("Dsp0"), eDisp0);
					lcdDiagnosis(1, F("Dsp1"), eDisp1);
					break;
				}
				break;
			}
			case eDiagnosisTempEmons:
			{
				lcdDiagnosis(0, F("Tmp0"), eTemp0);
				lcdDiagnosis(1, F("Tmp1"), eTemp1);
				break;
			}
			case eDiagnosisWater:
			{
				lcdDiagnosis(0, F("Wtr0"), eWaterNode0);
				lcdDiagnosis(1, F("Wtr1"), eWaterNode1);
				break;
			}
			case eDiagnosisEEPROMSettings:
			{
				lcd.setCursor(0, 0);
				lcd.print(F("Subnode"));
				lcd.setCursor(8, 0);
				lcd.print(eepromSettings.subnode);
				lcd.setCursor(0, 1);
				lcd.print(F("Relay"));
				lcd.setCursor(8, 1);
				lcd.print(eepromSettings.relayNumber);
				if (eepromSettings.relayNumber)
				{
					static int dispNodeID = 0;
					static int wait = 4;
					if (++wait == 5) //5*200ms= every second
					{
						wait = 0;
						while ((eepromSettings.relayNodes & ((long)1 << dispNodeID)) == 0)
							dispNodeID = (++dispNodeID) % 32;
						lcd.setCursor(10, 1);
						lcd.print(EmonEEPROM::NodeName(dispNodeID));
						dispNodeID = (++dispNodeID) % 32;
					}
				}
				break;
			}
		}
	}
}
