//------------------------------------------------------------------------------------------------------------------------------------------------
// Based on emonGLCD documentation http://openEnergyMonitor.org/emon/emonglcd
//
// GLCD library by Jean-Claude Wippler: JeeLabs.org
// 2010-05-28 <jcw@equi4.com> http://opensource.org/licenses/mit-license.php
//
//JeeLab libraires				http://github.com/jcw
//-------------------------------------------------------------------------------------------------------------------------------------------------


#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless

#include <EmonShared.h>

//#include <PortsLCD.h>
#include <TimeLib.h>

#define RED_LED		6			// Red tri-color LED
#define GREEN_LED 5			// Green tri-color LED
#define RESET_OUT A0		// The pin tied to the reset input


PayloadBase basePayload;
PayloadRain rainPayload;
PayloadPulse pulsePayload;
PayloadDisp displayPayload;
PayloadTemperature temperaturePayload;
PayloadTemperature temperaturePayload2;
PayloadHWS hwsPayload;
PayloadWater waterPayload;

RF12Init rf12Init = { BASE_JEENODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

//-------------------------------------------------------------------------------------------- 
//remote node reliability support
//-------------------------------------------------------------------------------------------- 
#define MAX_NODES	9				//number of jeenodes, node		0=emon,	1=emonTemperature, 1=emonTemperature2 2=rain, 3=base, 4=pulse, 5=hws, 6 = Display 
enum { eEmon, eTemp, eTemp2, eRain, eBase, ePulse, eHWS, eDisplay, eWater };	//index into txReceived and lastReceived
time_t lastReceived[MAX_NODES];


//--------------------------------------------------------------------------------------------
// Power variables
//--------------------------------------------------------------------------------------------
double wh_gen, wh_consuming;							//integer variables to store ammout of power currenty being consumed grid (in/out) +gen
unsigned long whtime;									//used to calculate energy used per day (kWh/d)


//--------------------------------------------------------------------------------------------
// Rain variables
//--------------------------------------------------------------------------------------------
int dailyRainfall, dayStartRainfall;						//daily Rainfall
unsigned long rainStartOfToday;
bool rainReceived;


//--------------------------------------------------------------------------------------------
// NTP time support 
//--------------------------------------------------------------------------------------------
// Number of seconds between 1-Jan-1900 and 1-Jan-1970, unix time starts 1970 and ntp time starts 1900.
#define GETTIMEOFDAY_TO_NTP_OFFSET 2208988800UL
#define NUM_TIMESERVERS 7

const char ntp0[] PROGMEM = "ntp1.anu.edu.au";
const char ntp1[] PROGMEM = "nist1-ny.ustiming.org";
const char ntp2[] PROGMEM = "ntp.exnet.com";
const char ntp3[] PROGMEM = "ntps1-0.cs.tu-berlin.de";
const char ntp4[] PROGMEM = "time.nist.gov";
const char ntp5[] PROGMEM = "ntps1-0.cs.tu-berlin.de";
const char ntp6[] PROGMEM = "time.nist.gov";
PGM_P const ntpList[] PROGMEM = { ntp0, ntp1, ntp2, ntp3, ntp4, ntp5, ntp6 };

uint8_t		clientPort = 123;
uint32_t	lastNTPUpdate = 0;
uint32_t	timeLong;
int				currentTimeserver = 0;


//--------------------------------------------------------------------------------------------
// Ethercard support
//-------------------------------------------------------------------------------------------- 
#include <EtherCard.h>
static byte mymac[] = { 0x74,0x69,0x69,0x2D,0x30,0x32 };
byte Ethernet::buffer[900];


//-------------------------------------------------------------------------------------------- 
//www.thingspeak.com support
//-------------------------------------------------------------------------------------------- 
#define APIKEY_POWER				"1OEHK8GL62859FAB"
#define APIKEY_TEMPERATURE	"TYG402MEEINATR4P"
#define APIKEY_HWS					"W5FD6RBQUGHU2DBP"

const char website[] PROGMEM = "api.thingspeak.com";
uint8_t		webip[4];
Stash			stash;
word			sessionID;
uint8_t		tcpReplyCount;
bool			awaitingReply;


//-------------------------------------------------------------------------------------------- 
// Flow control
//-------------------------------------------------------------------------------------------- 
unsigned long slow_update;					// Used to count time for slow 10s events
unsigned long web_update;
unsigned long request_NTP_Update;
byte	toggleWebUpdate = 0;				//toggle between temperature, power and hws updates to web
int thisHour = 0;


void initEthercard()
{
	uint8_t rev = ether.begin(sizeof Ethernet::buffer, mymac, 8);
	Serial.print(F("ENC28J60 Revision "));
	Serial.println(rev, DEC);
	if (rev == 0)
		Serial.println(F("Failed to access Ethernet controller"));

	Serial.println(F("Setting up DHCP"));
	if (!ether.dhcpSetup())
		Serial.println(F("DHCP failed"));

	ether.printIp(F("My IP: "), ether.myip);
	ether.printIp(F("Netmask: "), ether.netmask);
	ether.printIp(F("GW IP: "), ether.gwip);
	ether.printIp(F("DNS IP: "), ether.dnsip);

	Serial.print(F("ThingSpeak DNS lookup : "));
	if (!ether.dnsLookup(website))
		Serial.println(F("DNS failed"));
	else
		ether.printIp(F("ThingSpeak SRV: "), ether.hisip);

	ether.copyIp(webip, ether.hisip);
}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
	digitalWrite(RESET_OUT, HIGH);
	pinMode(RESET_OUT, OUTPUT);

	pinMode(GREEN_LED, OUTPUT);
	pinMode(RED_LED, OUTPUT);
	digitalWrite(GREEN_LED, LOW);		//LED has inverted logic. LOW is on, HIGH is off!
	digitalWrite(RED_LED, LOW );		//LED has inverted logic. LOW is on, HIGH is off!
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
	
	initEthercard();
	tcpReplyCount = 0;

	digitalWrite(GREEN_LED, HIGH);

	Serial.println(F("rf12_initialize"));
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);

	EmonSerial::PrintEmonPayload(NULL);
	EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBasePayload(NULL);
	EmonSerial::PrintPulsePayload(NULL);
	EmonSerial::PrintDispPayload(NULL);
	EmonSerial::PrintTemperaturePayload(NULL);
	EmonSerial::PrintHWSPayload(NULL);
	EmonSerial::PrintWaterPayload(NULL);
	
	temperaturePayload.numSensors = 0;
	temperaturePayload2.numSensors = 0;

	dailyRainfall = 0;
	dayStartRainfall = 0;

	slow_update = millis();
	web_update = millis();
	
	request_NTP_Update = millis()+1000;	//update in 1 second
	
	
	for (int i = 0; i < MAX_NODES; i++)
	{
		lastReceived[i] = now();
	}

	//NTP time
	//setSyncInterval(86400 * 7);		 // update the time every week	(24*60*60) *7
	//setSyncProvider(GetNtpTime);		// initiate the callback to GetNtpTime	

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
		if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)	// and no rf errors
		{
			digitalWrite(RED_LED, LOW);

			int node_id = (rf12_hdr & 0x1F);
		

			if (node_id == PULSE_JEENODE)
			{
				pulsePayload = *(PayloadPulse*)rf12_data;
				EmonSerial::PrintPulsePayload(&pulsePayload, now() - lastReceived[ePulse] );
				lastReceived[ePulse] = now();

				power_calculations_pulse();					
			}

			if (node_id == DISPLAY_NODE)
			{
				displayPayload = *(PayloadDisp*)rf12_data;								// get payload data
				EmonSerial::PrintDispPayload(&displayPayload, now() - lastReceived[eDisplay]);
				lastReceived[eDisplay] = now();
			}

			if (node_id == TEMPERATURE_JEENODE)
			{
				temperaturePayload = *(PayloadTemperature*)rf12_data;								// get payload data
				EmonSerial::PrintTemperaturePayload(&temperaturePayload, now() - lastReceived[eTemp]);
				lastReceived[eTemp] = now();
			}

			if (node_id == TEMPERATURE_JEENODE_2)
			{
				temperaturePayload2 = *(PayloadTemperature*)rf12_data;								// get payload data
				EmonSerial::PrintTemperaturePayload(&temperaturePayload2, now() - lastReceived[eTemp2]);
				lastReceived[eTemp2] = now();
			}

			if (node_id == HWS_JEENODE || node_id == HWS_JEENODE_RELAY )
			{
				hwsPayload = *(PayloadHWS*)rf12_data;								// get payload data
				if (node_id == HWS_JEENODE_RELAY)
					Serial.print("Relay_");
				EmonSerial::PrintHWSPayload(&hwsPayload, now() - lastReceived[eHWS]);
				lastReceived[eHWS] = now();
			}

		
			if (node_id == RAIN_NODE)						// ==== RainGauge Jeenode ====
			{
				rainPayload = *(PayloadRain*)rf12_data;								// get emonbase payload data
				EmonSerial::PrintRainPayload(&rainPayload, now() - lastReceived[eRain]);
				lastReceived[eRain] = now();

				if (!rainReceived)
				{
					dayStartRainfall = rainPayload.rainCount;
					rainReceived = true;
					dailyRainfall = 0;
				}
			}

			if(node_id == WATERLEVEL_NODE)
			{
				waterPayload = *(PayloadWater*)rf12_data;								// get payload data
				EmonSerial::PrintWaterPayload(&waterPayload, now() - lastReceived[eWater]);
				lastReceived[eWater] = now();
			}

			digitalWrite(RED_LED, HIGH);
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
			EmonSerial::PrintBasePayload(&basePayload);

			rf12_sendStart(0, &basePayload, sizeof(PayloadBase));
			rf12_sendWait(0);
		}
	}

	if (millis() > request_NTP_Update)
	{
		// time to send request
		request_NTP_Update = millis()+ 20000L;	//try again in 20 seconds
		Serial.print(F("NTP request: "));
		SerialPrint_P((const char**)pgm_read_word(&(ntpList[currentTimeserver])));
		Serial.println();

		if (!ether.dnsLookup((char*)pgm_read_word(&(ntpList[currentTimeserver]))))
		{
			Serial.println(F("DNS failed"));
		}
		else 
		{
			ether.printIp(F("SVR IP: "), ether.hisip);

			ether.ntpRequest(ether.hisip, ++clientPort);
			Serial.print(F("Send NTP request on port: "));
			Serial.println(clientPort, DEC);
		}
		if (++currentTimeserver >= NUM_TIMESERVERS)
			currentTimeserver = 0;
	}


	if (millis() % 10 == 0)
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
		
		if (tcpReplyCount)
		{
			const char* tcpReply = ether.tcpReply(sessionID);
			if (tcpReply)
			{
				//Serial.println(tcpReply);
				Serial.print(F("TCPReply for sesionID:"));
				Serial.println(sessionID);
				tcpReplyCount = 0;
			}
		}
	}

	if (millis() - web_update > 20000)
	{
		if (tcpReplyCount && ++tcpReplyCount > 3)
		{
			//still no return from the last post 3*20 seconds ago!
			initEthercard();
			tcpReplyCount = 0;
		}

		//update time after a possible initEtherCard() call;
		web_update = millis();
		digitalWrite(GREEN_LED, LOW);

		byte sd = stash.create();
		const char * apiKey;
		if( ++toggleWebUpdate ==3) 
			toggleWebUpdate=0;		//toggle

		if (toggleWebUpdate == 0)
		{
			//outside temperature
			apiKey = PSTR(APIKEY_TEMPERATURE);
			if (rainPayload.temperature != 0)
			{
				stash.print(F("field1="));
				stash.print(rainPayload.temperature / 100);
				stash.print(F("."));
				stash.print((rainPayload.temperature / 10) % 10);
			}
			if (displayPayload.temperature != 0)
			{
				stash.print(F("&field2="));
				stash.print(displayPayload.temperature / 100);
				stash.print(F("."));
				stash.print((displayPayload.temperature / 10) % 10);
			}
			if (temperaturePayload.temperature[0] != 0)
			{
				stash.print(F("&field3="));
				stash.print(temperaturePayload.temperature[0] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload.temperature[0] / 10) % 10);
			}
			if (temperaturePayload.temperature[1] != 0)
			{
				stash.print(F("&field4="));
				stash.print(temperaturePayload.temperature[1] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload.temperature[1] / 10) % 10);
			}
			if (temperaturePayload.temperature[2] != 0)
			{
				stash.print(F("&field5="));
				stash.print(temperaturePayload.temperature[2] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload.temperature[2] / 10) % 10);
			}
			if (temperaturePayload.temperature[3] != 0)
			{
				stash.print(F("&field6="));
				stash.print(temperaturePayload.temperature[3] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload.temperature[3] / 10) % 10);
			}
			if (temperaturePayload2.temperature[0] != 0)
			{
				stash.print(F("&field7="));
				stash.print(waterPayload.waterHeight);
				//stash.print(temperaturePayload2.temperature[0] / 100);
				//stash.print(F("."));
				//stash.print((temperaturePayload2.temperature[0] / 10) % 10);
			}
			if (temperaturePayload2.temperature[1] != 0)
			{
				stash.print(F("&field8="));
				stash.print(temperaturePayload2.temperature[1] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload2.temperature[1] / 10) % 10);
			}
		}
		else if( toggleWebUpdate == 1 )
		{
			//power
			apiKey = PSTR(APIKEY_POWER);
			stash.print(F("field1="));
			stash.print((word)pulsePayload.power[2]);
			stash.print("&field2=");
			stash.print((word)pulsePayload.power[1]);
			stash.print("&field3=");
			stash.print((word)wh_consuming);
			stash.print("&field4=");
			stash.print((word)wh_gen);
			stash.print("&field5=");
			stash.print((word)pulsePayload.power[0]);
			stash.print("&field6=");
			stash.print((int)(dailyRainfall / 5));
			stash.print(".");
			stash.print((dailyRainfall % 5) * 2);
			stash.print("&field7=");
			stash.print((word)pulsePayload.power[3]);
		}
		else if (toggleWebUpdate == 2)
		{
			//Hot water system
			apiKey = PSTR(APIKEY_HWS);
			if (hwsPayload.temperature[0])		//if there is no temperature reading yet, don't publish it
			{
				stash.print(F("field1="));
				stash.print((word)hwsPayload.temperature[0]);	//T1
				stash.print("&field2=");
				stash.print((word)hwsPayload.temperature[2]);	//T3
				stash.print("&field3=");
				stash.print((word)hwsPayload.temperature[5]);	//T6
				stash.print("&field4=");
				stash.print((word)hwsPayload.temperature[1]);	//T2
				stash.print("&field5=");
				stash.print((word)hwsPayload.temperature[4]);	//T5
				stash.print("&field6=");
				stash.print((word)hwsPayload.pump[0]);	//P1
				stash.print("&field7=");
				stash.print((word)hwsPayload.pump[1]);	//P2
				stash.print("&field8=");
				stash.print((word)hwsPayload.pump[2]);	//P3
			}
		}

		stash.save();

		ether.copyIp(ether.hisip, webip);

		Stash::prepare(PSTR("POST /update HTTP/1.1" "\r\n"
			"Host: $F"  "\r\n"
			"Connection: close"  "\r\n"
			"X-THINGSPEAKAPIKEY: $F"  "\r\n"
			"Content-Type: application/x-www-form-urlencoded"  "\r\n"
			"Content-Length: $D"  "\r\n"
			"\r\n"
			"$H"),
			website, apiKey , stash.size(), sd);

		for (;;) 
		{
			char c = stash.get();
			if (c == 0)
				break;
			Serial.print(c);
		}
		Serial.println();

		// send the packet - this also releases all stash buffers once done
		sessionID = ether.tcpSend();
		if (tcpReplyCount == 0)
			tcpReplyCount++;		//start the wait for a reply if not already waiting

		// added from: http://jeelabs.net/boards/7/topics/2241
		int freeCount = stash.freeCount();
		if (freeCount <= 3) 
		{ 
			Stash::initMap(56); 
		}
		Serial.print(F("stash.freeCount="));
		Serial.print(freeCount);
		Serial.print(F(",sessionID="));
		Serial.println(sessionID);

		//const char* reply = ether.tcpReply(sessionID);
		digitalWrite(GREEN_LED, HIGH);
	}

	int lastHour = thisHour;
	thisHour = hour();
	if (lastHour == 23 && thisHour == 00)
	{
		wh_gen = 0;
		wh_consuming = 0;

		Serial.println(F("Resetting Arduino at midnight."));
		delay(100); //Allow serial buffer to empty
		digitalWrite(RESET_OUT, LOW);
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

void power_calculations_pulse()
{
	//--------------------------------------------------
	// kWh calculation
	//--------------------------------------------------
	unsigned long lwhtime = whtime;
	whtime = millis();
	double whInc = pulsePayload.power[1] * ((whtime - lwhtime) / 3600000.0);  //solar comes in on pin 2
	wh_gen = wh_gen + whInc;
	whInc = pulsePayload.power[2] * ((whtime - lwhtime) / 3600000.0);					//main power comes in on pin 3
	wh_consuming = wh_consuming + whInc;
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

void SerialPrint_P(PGM_P* str)
{
	for (uint8_t c; (c = pgm_read_byte(str)); str++) 
		Serial.write(c);
}