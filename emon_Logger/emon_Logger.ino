//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_Logger. Receive each packet from an emon group and write to Serial
//-------------------------------------------------------------------------------------------------------------------------------------------------


//JeeLab libraires				http://github.com/jcw
#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless

#include <EmonShared.h>

#include <SoftwareSerial.h>
#include <SD.h>

#include <PortsLCD.h>
#include <TimeLib.h>


const int RED_LED=6;				 // Red tri-color LED
const int GREEN_LED = 5;		 // Red tri-color LED

#define MAX_NODES	14				//number of jeenodes, node		0=emon,	1=emonTemperature, 2=rain, 3=base, 4=pulse, 5=hws, 6 = Display 
enum { eEmon, eTemp0, eTemp1, eTemp2, eTemp3, eRain, eBase, ePulse, eHWS, eDisp0, eDisp1, eDisp2, eDisp3, eWater };	//index into txReceived and lastReceived

unsigned int txReceived[MAX_NODES];
time_t lastReceived[MAX_NODES];

PayloadEmon emonPayload;
PayloadBase basePayload;
PayloadRain rainPayload;
PayloadPulse pulsePayload;
PayloadDisp displayPayload[MAX_SUBNODES];
PayloadTemperature temperaturePayload[MAX_SUBNODES];
PayloadHWS hwsPayload;
PayloadWater waterPayload;

RF12Init rf12Init = { EMON_LOGGER, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

byte  currentDay = 0;
#define MAX_FILENAME_LEN 15
#define DATETIME_LEN 24


int thisHour;


//callback to provide creation date and time for SD card files
void dateTime(uint16_t* date, uint16_t* time)
{
	*date = FAT_DATE(year(), month(), day());
	*time = FAT_TIME(hour(), minute(), second());
}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
	pinMode(RED_LED, OUTPUT);
	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(RED_LED, LOW);		//Red LED has inverted logic. LOW is on, HIGH is off!
	Serial.begin(9600);
	
	delay(1000);
	Serial.println(F("Fewings emon Logger. Logging emon packets to SD card"));

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

	for (int i = 0; i < MAX_NODES; i++)
	{
		txReceived[i] = 0;
		lastReceived[i] = now();
	}


	SdFile::dateTimeCallback(dateTime);

	digitalWrite(GREEN_LED, LOW);		//Red LED has inverted logic. LOW is on, HIGH is off!
	Serial.print("Initializing SD card...");

	// see if the card is present and can be initialized:
	if (!SD.begin(9)) {
		Serial.println("Card failed, or not present");
		// don't do anything more:
		while (1);
	}
	Serial.println("card initialized.");

	digitalWrite(GREEN_LED, HIGH);
	digitalWrite(RED_LED, HIGH);		//Red LED has inverted logic. LOW is on, HIGH is off!
}


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
			int subnode = 0;

			if (node_id == BASE_JEENODE)						// jeenode base Receives the time
			{
				basePayload = *((PayloadBase*)rf12_data);
				EmonSerial::PrintBasePayload(&basePayload, (now() - lastReceived[eBase]));			 // print data to serial
				txReceived[eBase]++;
				lastReceived[eBase] = now();

				//set the time from the base
				setTime(basePayload.time);
				currentDay = day();		//will indicate time is set
			}

			if (node_id == EMON_NODE)						// === EMONTX ====
			{
				emonPayload = *(PayloadEmon*)rf12_data;							// get emontx payload data
				EmonSerial::PrintEmonPayload(&emonPayload, (now() - lastReceived[eEmon]));				// print data to serial
				txReceived[eEmon]++;
				lastReceived[eEmon] = now();				// set time of last update to now
			}

			if (node_id == PULSE_JEENODE)						// === PULSE NODE ====
			{
				pulsePayload = *(PayloadPulse*)rf12_data;							// get payload data
				EmonSerial::PrintPulsePayload(&pulsePayload, (now() - lastReceived[ePulse]));				// print data to serial
				txReceived[ePulse]++;
				lastReceived[ePulse] = now();				// set time of last update to now
			}
			if (node_id == TEMPERATURE_JEENODE)
			{
				PayloadTemperature tpl = *((PayloadTemperature*)rf12_data);
				subnode = tpl.subnode;
				if (subnode > MAX_SUBNODES)
				{
					Serial.print("Invalid temperature subnode. Exiting");
					return;
				}
				memcpy(&temperaturePayload[subnode], &tpl, sizeof(PayloadTemperature));
				EmonSerial::PrintTemperaturePayload(&temperaturePayload[subnode], (now() - lastReceived[eTemp0 + subnode]));			 // print data to serial
				txReceived[eTemp0 + subnode]++;
				lastReceived[eTemp0 + subnode] = now();
			}
			if (node_id == HWS_JEENODE )
			{
				hwsPayload = *(PayloadHWS*)rf12_data;							// get emontx payload data
				EmonSerial::PrintHWSPayload(&hwsPayload, (now() - lastReceived[eHWS]));				// print data to serial
				txReceived[eHWS]++;
				lastReceived[eHWS] = now();				// set time of last update to now
			}

			if (node_id == RAIN_NODE)						// ==== RainGauge Jeenode ====
			{
				rainPayload = *(PayloadRain*)rf12_data;	// get emonbase payload data
				EmonSerial::PrintRainPayload(&rainPayload, (now() - lastReceived[eRain]));			 // print data to serial
				lastReceived[eRain] = now();
				txReceived[eRain]++;
			}

			if (node_id == DISPLAY_NODE)
			{
				PayloadDisp dpl = *((PayloadDisp*)rf12_data);
				subnode = dpl.subnode;
				if (subnode > MAX_SUBNODES)
				{
					Serial.print("Invalid subnode. Exiting");
					return;
				}
				memcpy(&displayPayload[subnode], &dpl, sizeof(PayloadDisp));
				EmonSerial::PrintDispPayload(&displayPayload[subnode], (now() - lastReceived[eDisp0 + subnode]));			 // print data to serial
				txReceived[eDisp0 + subnode]++;
				lastReceived[eDisp0 + subnode] = now();
			}

			if (node_id == WATERLEVEL_NODE)
			{
				waterPayload = *((PayloadWater*)rf12_data);
				EmonSerial::PrintWaterPayload(&waterPayload, (now() - lastReceived[eWater]));			 // print data to serial
				txReceived[eWater]++;
				lastReceived[eWater] = now();
			}


			digitalWrite(RED_LED, LOW);
			delay(100);
			digitalWrite(RED_LED, HIGH);

			if (currentDay != 0)  //the time has been set!
			{
				char fileName[MAX_FILENAME_LEN];
				//yyyy-mm-dd.txt
				snprintf_P(fileName, MAX_FILENAME_LEN, PSTR("%02d%02d%02d.txt"), year(), month(), day());


				File file = SD.open(fileName, FILE_WRITE);

				if (file)
				{
					//dd/mm/yyyy HH:mm:ss
					char dateTime[DATETIME_LEN];
					snprintf_P(dateTime, DATETIME_LEN, PSTR("%02d/%02d/%04d %02d:%02d:%02d,"), day(), month(), year(), hour(), minute(), second() );
					file.print(dateTime);

					switch (node_id)
					{
					case BASE_JEENODE:
						EmonSerial::PrintBasePayload(file, &basePayload);
						break;
					case RAIN_NODE:
						EmonSerial::PrintRainPayload(file, &rainPayload);
						break;
					case PULSE_JEENODE:
						EmonSerial::PrintPulsePayload(file, &pulsePayload);
						break;
					case DISPLAY_NODE:
						EmonSerial::PrintDispPayload(file, &displayPayload[subnode]);
						break;
					case TEMPERATURE_JEENODE:
						EmonSerial::PrintTemperaturePayload(file, &temperaturePayload[subnode]);
						break;
					case HWS_JEENODE:
						EmonSerial::PrintHWSPayload(file, &hwsPayload);
						break;
					case WATERLEVEL_NODE:
						EmonSerial::PrintWaterPayload(file, &waterPayload);
						break;
					}

					file.close();

					digitalWrite(GREEN_LED, LOW);
					delay(100);
					digitalWrite(GREEN_LED, HIGH);
				}
			}
		}
	}
} 