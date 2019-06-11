#include <TimeLib.h>
#include <SPI.h>
#include <Ethernet.h>
//#include <Udp.h>        //for SNTP time
#include <SoftwareSerial.h>
#include <ThingSpeak.h>

#include <EmonShared.h>


// Enter a MAC address and IP address for your controller below.
// The IP address will be dependent on your local network:
static byte mac[] = { 0x54,0x55,0x58,0x10,0x00,0x24 };

#define UPDATE_PERIOD        6        //Seconds between updates to Pachube

time_t          lastSend;
time_t          lastSumTime;
time_t          lastSyncTime;
time_t          startRunningTime = 0;

//Serial connection support to Jeenode
#define MAX_SERIAL_STRING 60
char serialIn[MAX_SERIAL_STRING];
int serialInIndex = 0;

SoftwareSerial emonSerial(3,4); // RX, TX

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


PayloadBase basePayload;
PayloadRain rainPayload;
PayloadPulse pulsePayload;
PayloadDisp displayPayload[1];// MAX_SUBNODES];
PayloadTemperature temperaturePayload[1];//MAX_SUBNODES];
PayloadHWS hwsPayload;
PayloadWater waterPayload;

//-------------------------------------------------------------------------------------------- 
// Flow control
//-------------------------------------------------------------------------------------------- 
unsigned long slow_update;					// Used to count time for slow 10s events
unsigned long web_update;
unsigned long request_NTP_Update;
byte	toggleWebUpdate = 0;				//toggle between temperature, power and hws updates to web
int thisHour = 0;


//-------------------------------------------------------------------------------------------- 
//www.thingspeak.com support
//-------------------------------------------------------------------------------------------- 
#define APIKEY_POWER		"1OEHK8GL62859FAB"
#define APIKEY_TEMPERATURE "TYG402MEEINATR4P"
#define APIKEY_HWS					F("W5FD6RBQUGHU2DBP")
#define APIKEY_WATER	F("BAO9U9BAT67YTZ0J")

ThingSpeakClass thingSpeak;
EthernetClient client;


void setup()
{
	Serial.begin(9600);
	Serial.println(F("emon_Ethernet"));

	// start the Ethernet connection:
	Serial.println(F("Initialize Ethernet with DHCP:"));
	if (Ethernet.begin(mac) == 0) {
		Serial.println(F("Failed to configure Ethernet using DHCP"));
		if (Ethernet.hardwareStatus() == EthernetNoHardware) {
			Serial.println(F("Ethernet shield was not found.  Sorry, can't run without hardware. :("));
		}
		else if (Ethernet.linkStatus() == LinkOFF) {
			Serial.println(F("Ethernet cable is not connected."));
		}
		// no point in carrying on, so do nothing forevermore:
		while (true) {
			delay(1);
		}
	}
	// print your local IP address:
	Serial.print(F("My IP address: "));
	Serial.println(Ethernet.localIP());
	Serial.print(F("DNS address: "));
	Serial.println(Ethernet.dnsServerIP());
	Serial.print(F("Gateway address: "));
	Serial.println(Ethernet.gatewayIP());
	Serial.print(F("Subnet mask address: "));
	Serial.println(Ethernet.subnetMask());
	// start the Ethernet connection and the server:

	NTPClientSetup();

	lastSend = now();
	lastSumTime = now();

	//the Jeenode is connected to serial 3
	emonSerial.begin(9600);

	//thingSpeak.begin(client);

}


void loop()
{
	time_t time = now();

	if (NTPClientLoop())
	{
		lastSend = now();
		lastSumTime = now();
		lastSyncTime = now();
		if (startRunningTime == 0)
			startRunningTime = now();
	}

	while (emonSerial.available())
	{
		serialIn[serialInIndex++] = emonSerial.read();
		//Serial.write(serialIn[serialInIndex - 1]);
		if (serialInIndex >= MAX_SERIAL_STRING - 1)
			serialInIndex = 0;		//overflow the buffer
		if (serialIn[serialInIndex - 1] == '\n' ||
			serialIn[serialInIndex - 1] == '&')	//end of line
		{
			serialIn[serialInIndex] = 0; //null terminate

			char* node = strchr(serialIn, ':');
			if (node != 0)
			{
				if (0 == strncmp(node - 4, "rain:", 5))
				{
					if (EmonSerial::ParseRainPayload(node - 4, &rainPayload))
					{
						EmonSerial::PrintRainPayload(&rainPayload);
					}

					if (!rainReceived)
					{
						dayStartRainfall = rainPayload.rainCount;
						rainReceived = true;
						dailyRainfall = 0;
					}
				}
				else if (0 == strncmp(node - 4, "temp:", 5))
				{
					if (EmonSerial::ParseTemperaturePayload(node - 4, &temperaturePayload[0]))
					{
						EmonSerial::PrintTemperaturePayload(&temperaturePayload[0]);
					}
				}
				else if (0 == strncmp(node - 4, "disp:", 5))
				{
					if (EmonSerial::ParseDispPayload(node - 4, &displayPayload[0]))
					{
						EmonSerial::PrintDispPayload(&displayPayload[0]);
					}
				}
				else if (0 == strncmp(node - 4, "pulse:", 6))
				{
					if (EmonSerial::ParsePulsePayload(node - 4, &pulsePayload))
					{
						EmonSerial::PrintPulsePayload(&pulsePayload);

						power_calculations_pulse();
					}
				}
			}
			serialInIndex = 0;
		}
	}

	// update every UPDATE_PERIOD seconds
	if (time >= (lastSend + UPDATE_PERIOD))
	{
		lastSend = time;
		Serial.print("+");
		//update 24hr tallies
		if ((timeStatus() == timeSet))
		{
			//Send the time to the Jeenode so it can broadcast it to other nodes
			basePayload.time = now();
			Serial.print("+");

			EmonSerial::PrintBasePayload(Serial, &basePayload);
			Serial.print("+");

			//EmonSerial::PrintBasePayload(emonSerial, &basePayload);
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

		//Thingspeak update
		const char* apiKey;
		if (++toggleWebUpdate == 2)
			toggleWebUpdate = 0;		//toggle

		if (toggleWebUpdate == 0)
		{
			Serial.print("P");
			//power
			apiKey = PSTR(APIKEY_POWER);
			thingSpeak.setField(1, pulsePayload.power[2]);
			//thingSpeak.setField(2, pulsePayload.power[1]);
			//thingSpeak.setField(3, (float) wh_consuming);
			//thingSpeak.setField(4, (float) wh_gen);
			//thingSpeak.setField(5, pulsePayload.power[0]);
			//thingSpeak.setField(6, dailyRainfall* 0.2f);
			//thingSpeak.setField(7, pulsePayload.power[3]);
		}
		else if (toggleWebUpdate == 1)
		{
			Serial.print("T");
			apiKey = PSTR(APIKEY_TEMPERATURE);

			if (rainPayload.temperature != 0)
			{
				thingSpeak.setField(1, rainPayload.temperature / 100.0f);
			}
			//if (displayPayload[0].temperature != 0)
			//{
			//	thingSpeak.setField(2, displayPayload[0].temperature / 100.0f);
			//}
			//if (temperaturePayload[0].temperature[0] != 0)
			//{
			//	thingSpeak.setField(3, temperaturePayload[0].temperature[0] / 100.0f);
			//}
			//if (temperaturePayload[0].temperature[1] != 0)
			//{
			//	thingSpeak.setField(4, temperaturePayload[0].temperature[1] / 100.0f);
			//}
			//if (temperaturePayload[0].temperature[2] != 0)
			//{
			//	thingSpeak.setField(5, temperaturePayload[0].temperature[2] / 100.0f);
			//}
			//if (temperaturePayload[0].temperature[3] != 0)
			//{
			//	thingSpeak.setField(6, temperaturePayload[0].temperature[3] / 100.0f);
			//}
			//if (temperaturePayload[1].temperature[0] != 0)
			//{
			//	thingSpeak.setField(7, temperaturePayload[1].temperature[0] / 100.0f);
			//}
			//if (temperaturePayload[1].temperature[1] != 0)
			//{
			//	thingSpeak.setField(8, temperaturePayload[10].temperature[1] / 100.0f);
			//}
		}
		Serial.print("T");

		// write to the ThingSpeak channel 
		int x = thingSpeak.writeFields(0, APIKEY_POWER);
		if (x == 200) {
			Serial.println(F("Channel update successful."));
		}
		else 
		{
			Serial.print(F("Problem updating channel. HTTP error code "));
			Serial.println(x);
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
