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
#include <eeprom.h>

#define RED_LED		6			// Red tri-color LED
#define GREEN_LED 5			// Green tri-color LED


//--------------------------------------------------------------------------------------------
// EEPROM startofDay counts support
//--------------------------------------------------------------------------------------------
#define EEPROM_BASE 0x10	//where the startOfToday counts are stored
typedef struct eepromStore
{
	byte version;
	time_t time;
} eepromStore;


PayloadBase basePayload;
PayloadRain rainPayload;
PayloadPulse pulsePayload;
PayloadHWS hwsPayload;
PayloadWater waterPayload[MAX_SUBNODES/2];
PayloadScale scalePayload;
PayloadDisp displayPayload[MAX_SUBNODES];
PayloadTemperature temperaturePayload[MAX_SUBNODES];
unsigned long lastRFReceived;


RF12Init rf12Init = { BASE_JEENODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

//--------------------------------------------------------------------------------------------
// pulse start of day counts 
//--------------------------------------------------------------------------------------------
unsigned long pulseStartOfToday[PULSE_NUM_PINS];
unsigned long waterStartOfToday[MAX_SUBNODES / 2];
unsigned long rainStartOfToday;

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
static byte mymac[] = { 0x74,0x69,0x69,0x2D,0x30,0x33 };
byte Ethernet::buffer[800];


//-------------------------------------------------------------------------------------------- 
//www.thingspeak.com support
//-------------------------------------------------------------------------------------------- 
#define APIKEY_POWER				"1OEHK8GL62859FAB"
#define APIKEY_TEMPERATURE	"TYG402MEEINATR4P"
#define APIKEY_HWS					"W5FD6RBQUGHU2DBP"
#define APIKEY_WATER				"BAO9U9BAT67YTZ0J"

const char website[] PROGMEM = "api.thingspeak.com";
uint8_t		webip[4];
Stash			stash;
word			sessionID;
uint8_t		tcpReplyCount;


//-------------------------------------------------------------------------------------------- 
// Flow control
//-------------------------------------------------------------------------------------------- 
unsigned long slow_update;					// Used to count time for slow 10s events
unsigned long web_update;
unsigned long request_NTP_Update;
byte	toggleWebUpdate = 0;				//toggle between temperature, power and hws updates to web
int thisHour = 0;


//--------------------------------------------------------------------------------------------
unsigned long readEEPROM(int offset)
{
	unsigned long value = 0;
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(unsigned long); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_BASE + offset + l);
	}

	return value;
}

void writeEEPROM(int offset, unsigned long value)
{
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(unsigned long); l++)
	{
		EEPROM.write(EEPROM_BASE + offset + l, *(pc + l));
	}
}

int loadStartOfTodayCounts()
{
	eepromStore storage;
	storage.version = 1;
	storage.time = now();
	char* pc = (char*)& storage;

	if (timeStatus() != timeSet)
		return 0;

	for (long l = 0; l < sizeof(storage); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_BASE + l);
	}
	if (storage.version != 1)
		return 0;
	if (day(storage.time) != day() || month(storage.time) != month() || year(storage.time) != year())
		return 0;

	for (long l = 0; l < PULSE_NUM_PINS; l++)
		pulseStartOfToday[l] = readEEPROM(sizeof(storage) + l * sizeof(unsigned long));
	for (long l = 0; l < MAX_SUBNODES / 2; l++)
		waterStartOfToday[l] = readEEPROM(sizeof(storage) + ((PULSE_NUM_PINS + l) * sizeof(unsigned long)));
	rainStartOfToday = readEEPROM(sizeof(storage) + ((PULSE_NUM_PINS + MAX_SUBNODES) * sizeof(unsigned long)));

	return 1;
}


int storeStartOfTodayCounts()
{
	eepromStore storage;
	storage.version = 1;
	storage.time = now();
	char* pc = (char*)& storage;

	if (timeStatus() != timeSet)
		return 0;

	for (long l = 0; l < sizeof(storage); l++)
	{
		EEPROM.write(EEPROM_BASE + l, *(pc + l));
	}

	for( long l = 0; l < PULSE_NUM_PINS; l++)
		writeEEPROM( sizeof(storage) + l*sizeof(unsigned long), pulseStartOfToday[l]);
	for (long l = 0; l < MAX_SUBNODES / 2; l++)
		writeEEPROM(sizeof(storage) + ((PULSE_NUM_PINS + l) * sizeof(unsigned long)), waterStartOfToday[l]);
	writeEEPROM(sizeof(storage) + ((PULSE_NUM_PINS + MAX_SUBNODES) * sizeof(unsigned long)), rainStartOfToday);

	return 1;
}
//--------------------------------------------------------------------------------------------

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

void initRF12()
{
	Serial.println(F("rf12_initialize"));
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);
}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
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

	initRF12();

	lastRFReceived = millis();

	EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBasePayload(NULL);
	EmonSerial::PrintPulsePayload(NULL);
	EmonSerial::PrintDispPayload(NULL);
	EmonSerial::PrintTemperaturePayload(NULL);
	EmonSerial::PrintHWSPayload(NULL);
	EmonSerial::PrintWaterPayload(NULL);
	EmonSerial::PrintScalePayload(NULL);

	for(int i=0;i<MAX_SUBNODES;i++)
		temperaturePayload[i].numSensors = 0;
		
	rainPayload.rainCount = rainStartOfToday = 0;
	for (int i = 0; i < PULSE_NUM_PINS; i++)
		pulsePayload.pulse[i] = pulseStartOfToday[i] = 0;
	for (int i = 0; i < MAX_SUBNODES / 2; i++)
		waterStartOfToday[i] = waterPayload[i].flowCount = 0;

	scalePayload.grams = 0;

	slow_update = millis();
	web_update = millis();
	
	request_NTP_Update = millis()+1000;	//update in 1 second
	
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
		lastRFReceived = millis();

		if (rf12_crc)
		{
			Serial.print(F("rcv crc err:"));
			Serial.print(rf12_crc);
			Serial.print(F(",len:"));
			Serial.println(rf12_hdr);
		}

		if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)	// and no rf errors
		{
			digitalWrite(RED_LED, LOW);

			int node_id = (rf12_hdr & 0x1F);
			

			if (node_id == PULSE_JEENODE)
			{
				pulsePayload = *(PayloadPulse*)rf12_data;
				EmonSerial::PrintPulsePayload(&pulsePayload);
				if (pulseStartOfToday[0] == 0)
				{
					for (int i = 0; i < PULSE_NUM_PINS; i++)
						pulseStartOfToday[i] = pulsePayload.pulse[i];
				}
			}

			if (node_id == DISPLAY_NODE)
			{
				PayloadDisp dpl = *((PayloadDisp*)rf12_data);
				byte subnode = dpl.subnode;
				if (subnode >= MAX_SUBNODES)
				{
					Serial.print(F("Invalid display subnode. Exiting"));
					return;
				}
				memcpy(&displayPayload[subnode], &dpl, sizeof(PayloadDisp));
				EmonSerial::PrintDispPayload(&displayPayload[subnode]);			 // print data to serial
			}

			if (node_id == TEMPERATURE_JEENODE)
			{
				PayloadTemperature tpl = *((PayloadTemperature*)rf12_data);
				byte subnode = tpl.subnode;
				if (subnode >= MAX_SUBNODES)
				{
					Serial.print(F("Invalid temperature subnode. Exiting"));
					return;
				}
				memcpy(&temperaturePayload[subnode], &tpl, sizeof(PayloadTemperature));
				EmonSerial::PrintTemperaturePayload(&temperaturePayload[subnode]);			 // print data to serial
			}

			if (node_id == HWS_JEENODE )
			{
				hwsPayload = *(PayloadHWS*)rf12_data;								// get payload data
				EmonSerial::PrintHWSPayload(&hwsPayload);
			}

		
			if (node_id == RAIN_NODE)						// ==== RainGauge Jeenode ====
			{
				rainPayload = *(PayloadRain*)rf12_data;								// get emonbase payload data
				EmonSerial::PrintRainPayload(&rainPayload);

				if (rainStartOfToday == 0)
				{
					rainStartOfToday = rainPayload.rainCount;
				}
			}

			if(node_id == WATERLEVEL_NODE)
			{
				PayloadWater wpl = *((PayloadWater*)rf12_data);
				byte subnode = wpl.subnode;
				if (subnode >= MAX_SUBNODES / 2)
				{
					Serial.print(F("Invalid water subnode. Exiting"));
					return;
				}
				memcpy(&waterPayload[subnode], &wpl, sizeof(PayloadWater));
				EmonSerial::PrintWaterPayload(&waterPayload[subnode]);			 // print data to serial

				if (waterStartOfToday[subnode] == 0)
				{
					waterStartOfToday[subnode] = waterPayload[subnode].flowCount;
				}			
			}

			if(node_id == SCALE_NODE)
			{
				scalePayload = *(PayloadScale*)rf12_data;								// get payload data
				EmonSerial::PrintScalePayload(&scalePayload);
			}

			digitalWrite(RED_LED, HIGH);
		}
	}
	
	if (millis() - lastRFReceived > 60000)
	{
		//no RF12 data received for 60 secnds. Re-initialise the RF12
		initRF12();
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

					Serial.print(F("Load startOfToday pulse counts - "));
					if( loadStartOfTodayCounts() )
						Serial.println(F("Success"));
					else
						Serial.println(F("Fail"));
						
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

	if (millis() - web_update > 15000)
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
		if( ++toggleWebUpdate ==4) 
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
			if (displayPayload[0].temperature != 0)
			{
				stash.print(F("&field2="));
				stash.print(displayPayload[0].temperature / 100);
				stash.print(F("."));
				stash.print((displayPayload[0].temperature / 10) % 10);
			}
			if (temperaturePayload[0].temperature[0] != 0)
			{
				stash.print(F("&field3="));
				stash.print(temperaturePayload[0].temperature[0] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload[0].temperature[0] / 10) % 10);
			}
			if (temperaturePayload[0].temperature[1] != 0)
			{
				stash.print(F("&field4="));
				stash.print(temperaturePayload[0].temperature[1] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload[0].temperature[1] / 10) % 10);
			}
			if (temperaturePayload[0].temperature[2] != 0)
			{
				stash.print(F("&field5="));
				stash.print(temperaturePayload[0].temperature[2] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload[0].temperature[2] / 10) % 10);
			}
			if (temperaturePayload[0].temperature[3] != 0)
			{
				stash.print(F("&field6="));
				stash.print(temperaturePayload[0].temperature[3] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload[0].temperature[3] / 10) % 10);
			}
			if (temperaturePayload[1].temperature[0] != 0)
			{
				stash.print(F("&field7="));
				stash.print(temperaturePayload[1].temperature[0] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload[1].temperature[0] / 10) % 10);
			}
			if (temperaturePayload[1].temperature[1] != 0)
			{
				stash.print(F("&field8="));
				stash.print(temperaturePayload[1].temperature[1] / 100);
				stash.print(F("."));
				stash.print((temperaturePayload[1].temperature[1] / 10) % 10);
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
			stash.print((word)((pulsePayload.pulse[2] - pulseStartOfToday[2])));
			stash.print("&field4=");
			stash.print((word)((pulsePayload.pulse[1] - pulseStartOfToday[1])));
			stash.print("&field5=");
			stash.print((word)pulsePayload.power[0]);
			stash.print("&field6=");
			stash.print((word)((pulsePayload.pulse[0] - pulseStartOfToday[0])));
			stash.print("&field7=");
			stash.print((word)pulsePayload.power[3]);
			stash.print("&field8=");
			stash.print((word)((pulsePayload.pulse[3] - pulseStartOfToday[3])));
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
		else if (toggleWebUpdate == 3)
		{
			//Hot water system
			apiKey = PSTR(APIKEY_WATER);
			if (waterPayload[0].waterHeight)		//if there is no temperature reading yet, don't publish it
			{
				stash.print(F("&field1="));
				stash.print(waterPayload[0].waterHeight);
			}
			if (rainPayload.rainCount != 0)
			{
				stash.print("&field2=");
				stash.print((int)((rainPayload.rainCount - rainStartOfToday) / 5));
				stash.print(".");
				stash.print(((rainPayload.rainCount - rainStartOfToday) % 5) * 2);
			}
			if (waterPayload[0].flowCount != 0)
			{
				stash.print("&field3=");
				stash.print((int)((waterPayload[0].flowCount - waterStartOfToday[0]) / 1000));
			}
			if (waterPayload[1].flowCount != 0)
			{
				stash.print("&field4=");
				stash.print((int)((waterPayload[1].flowCount - waterStartOfToday[1])));
			}
			if (scalePayload.grams != 0)
			{
				stash.print("&field5=");
				stash.print((int)scalePayload.grams);
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
		Serial.print(sessionID);
		Serial.print(F(",freeMem="));
		Serial.println( getFreeMemory() );

		//const char* reply = ether.tcpReply(sessionID);
		digitalWrite(GREEN_LED, HIGH);
	}

	int lastHour = thisHour;
	thisHour = hour();
	if (lastHour == 23 && thisHour == 00)
	{
		for (int i = 0; i < PULSE_NUM_PINS; i++)
			pulseStartOfToday[i] = pulsePayload.pulse[i];
		for (int i = 0; i < MAX_SUBNODES / 2; i++)
			waterStartOfToday[i] = waterPayload[i].flowCount;

		Serial.print(F("Store startOfToday pulse counts - "));
		if (storeStartOfTodayCounts())
			Serial.println(F("Success"));
		else
			Serial.println(F("Fail"));
	}

	if (lastHour == 8 && thisHour == 9)
	{
		rainStartOfToday = rainPayload.rainCount;
		
		Serial.print(F("Store startOfToday pulse counts - "));
		if (storeStartOfTodayCounts())
			Serial.println(F("Success"));
		else
			Serial.println(F("Fail"));
	}
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


// predefined variables
extern unsigned int __data_start;
extern unsigned int __data_end;
extern unsigned int __bss_start;
extern unsigned int __bss_end;
extern unsigned int __heap_start;
extern void* __brkval;

int getFreeMemory()
{
	int free_memory;

	if ((int)__brkval == 0)
		free_memory = ((int)& free_memory) - ((int)& __bss_end);
	else
		free_memory = ((int)& free_memory) - ((int)__brkval);

	return free_memory;
}

void SerialPrint_P(PGM_P* str)
{
	for (uint8_t c; (c = pgm_read_byte(str)); str++) 
		Serial.write(c);
}