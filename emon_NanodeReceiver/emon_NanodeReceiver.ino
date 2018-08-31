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


//JeeLab libraires				http://github.com/jcw
#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless

#include <EmonShared.h>


#include <PortsLCD.h>
#include <Time/Time.h>

const int RED_LED=6;				 // Red tri-color LED
const int GREEN_LED = 5;		 // Red tri-color LED


PayloadEmon emonPayload;	
PayloadBase basePayload;
PayloadRain rainPayload;

RF12Init rf12Init = { 15, RF12_915MHZ, 210 };


unsigned long rainStartOfToday;
bool rainReceived;

unsigned int g_etherResets = 0;

//---------------------------------------------------

//--------------------------------------------------------------------------------------------
// Power variables
//--------------------------------------------------------------------------------------------
double wh_gen, wh_consuming;							//integer variables to store ammout of power currenty being consumed grid (in/out) +gen
unsigned long whtime;									//used to calculate energy used per day (kWh/d)
unsigned int pktsReceived;
int dailyRainfall, dayStartRainfall;						//daily Rainfall

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
//Pachube support
//-------------------------------------------------------------------------------------------- 
// change these settings to match your own setup
#define FEED	"78783"
#define APIKEY	"f04d8709cfe8d8b88d5c843492a738f634f0fab11402e6c2abc2b4c7f6dfff31"
//#define USERAGENT "Cosm Arduino Example (78783)"
const char website[] PROGMEM = "api.pachube.com";
uint8_t		webip[4];
Stash			stash;
word			sessionID;

//--------------------------------------------------------------------------------------------
// Software RTC setup
//-------------------------------------------------------------------------------------------- 
//RTC_Millis RTC;
int thisHour;
	
//-------------------------------------------------------------------------------------------- 
// Flow control
//-------------------------------------------------------------------------------------------- 
int view = 1;								// Used to control which screen view is shown
unsigned long last_emontx;					// Used to count time from last emontx update
unsigned long last_rainTx;
unsigned long slow_update;					// Used to count time for slow 10s events
unsigned long fast_update;					// Used to count time for fast 100ms events
unsigned long web_update;
unsigned long request_NTP_Update;

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

	Serial.print(F("Pachube DNS lookup : "));
	if (!ether.dnsLookup(website))
		Serial.println(F("DNS failed"));

	ether.printIp(F("Pachube SRV: "), ether.hisip);

	ether.copyIp(webip, ether.hisip);
}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
	pinMode(RED_LED, OUTPUT);	
	digitalWrite(RED_LED, LOW );		//Red LED has inverted logic. LOW is on, HIGH is off!
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, HIGH);		//Red LED has inverted logic. LOW is on, HIGH is off!

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

	Serial.println(F("rf12_initialize"));
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);

	EmonSerial::PrintEmonPayload(NULL);
	EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBasePayload(NULL);


	pktsReceived = 0;
	dailyRainfall = 0;
	dayStartRainfall = 0;

	slow_update = millis();
	fast_update = millis();
	web_update = millis();
	request_NTP_Update = millis()+1000;	//update in 1 second


	last_emontx = millis();
	last_rainTx = millis();

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
			int node_id = (rf12_hdr & 0x1F);
		
			if (node_id == EMON_NODE)						// === EMONTX ====
			{
				//monitor the reliability of receival
				pktsReceived++;

				emonPayload = *(PayloadEmon*) rf12_data;		// get emontx payload data
				EmonSerial::PrintEmonPayload(&emonPayload, millis() - last_emontx);				// print data to serial
				last_emontx = millis();				 // set time of last update to now

			
				digitalWrite(RED_LED, LOW );
				delay(100);	
				digitalWrite(RED_LED, HIGH );
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

				digitalWrite(RED_LED, LOW);
				delay(100);
				digitalWrite(RED_LED, HIGH);
			}
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
			ether.printIp("SVR IP: ", ether.hisip);

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
			//else
			//{
			//	Ethernet::buffer[pos + len] = 0;// set the byte after the end of the buffer to zero to act as an end marker (also handy for displaying the buffer as a string)	
			//	Serial.println("HTTP response"); 
			//	Serial.println((char *)(Ethernet::buffer+pos));
			//}
		}
	}

	if (millis() - web_update > 60000)
	{
		web_update = millis();
		
		// generate two fake values as payload - by using a separate stash,
		// we can determine the size of the generated message ahead of time
		String str;
		byte sd = stash.create();
		stash.print("1,");
		stash.println((word)emonPayload.power);
		stash.print("2,");
		stash.println((word)emonPayload.ct1);
		stash.print("3,");
		stash.println((word) wh_consuming);
		stash.print("4,");
		stash.println((word) wh_gen);
		stash.print("5,");
		stash.println(TemperatureString(str, emonPayload.temperature));
		stash.print("6,");
		stash.println(RainString(str, dailyRainfall));
		stash.save();
		

		Serial.println(emonPayload.temperature);
		Serial.println(TemperatureString(str, emonPayload.temperature));

		pktsReceived = 0;

		ether.copyIp(ether.hisip, webip);

		// generate the header with payload - note that the stash size is used,
		// and that a "stash descriptor" is passed in as argument using "$H"
		Stash::prepare(PSTR("PUT http://$F/v2/feeds/$F.csv HTTP/1.0" "\r\n"
							"Host: $F" "\r\n"
							"X-PachubeApiKey: $F" "\r\n"
							"Content-Length: $D" "\r\n"
							"\r\n"
							"$H"),
				website, PSTR(FEED), website, PSTR(APIKEY), stash.size(), sd);

		for (;;) 
		{
			char c = stash.get();
			if (c == 0)
				break;
			Serial.print(c);
		}
		
		// send the packet - this also releases all stash buffers once done
		sessionID = ether.tcpSend();

		const char* reply = ether.tcpReply(sessionID);
		Serial.print("sessionID=");
		Serial.println(sessionID);

		if (reply != NULL)
		{
			Serial.println(reply);
			initEthercard();
			g_etherResets++;
		}
		else
		{
			Serial.println("tcpReply=0");
		}

		//Green LED flashes three times for 
		if (g_etherResets == 0)
		{
			for (int i = 0; i < 3; i++)
			{
				digitalWrite(GREEN_LED, LOW);
				delay(50);
				digitalWrite(GREEN_LED, HIGH);
				delay(100);
			}
		}
		else
		{
			for (int i = 0; i < g_etherResets; i++)
			{
				digitalWrite(RED_LED, LOW);
				delay(50);
				digitalWrite(RED_LED, HIGH);
				delay(200);
			}
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

void SerialPrint_P(PGM_P* str)
{
	for (uint8_t c; (c = pgm_read_byte(str)); str++) 
		Serial.write(c);
}