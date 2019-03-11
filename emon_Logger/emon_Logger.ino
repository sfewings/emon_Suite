//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_Logger. Receive each packet from an emon group and write to Serial
//-------------------------------------------------------------------------------------------------------------------------------------------------


//JeeLab libraires				http://github.com/jcw
#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless

#include <EmonShared.h>

#include <SoftwareSerial.h>
#include <tinyFAT.h>

#include <PortsLCD.h>
#include <Time/Time.h>
//#include "utils.h"

#include <SD.h>


const int RED_LED=6;				 // Red tri-color LED
const int GREEN_LED = 5;		 // Red tri-color LED

#define MAX_NODES	7				//number of jeenodes, node		1=emon,	2=emonTemperature, 3=rain, 4=base, 5=pulse, 6=hws 
enum { eEmon, eTemp, eRain, eBase, ePulse, eHWS, eDisplay };	//index into txReceived and lastReceived

unsigned int txReceived[MAX_NODES];
time_t lastReceived[MAX_NODES];
long pktsReceived;

PayloadEmon emonPayload;
PayloadEmon emonTempPayload;
PayloadBase basePayload;
PayloadRain rainPayload;
PayloadPulse pulsePayload;
PayloadDisp displayPayload;
PayloadTemperature temperaturePayload;
PayloadHWS hwsPayload;

RF12Init rf12Init = { EMON_LOGGER, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

byte  currentDay = 0;
#define MAX_FILENAME_LEN 12


//--------------------------------------------------------------------------------------------
// Software RTC setup
//-------------------------------------------------------------------------------------------- 
//RTC_Millis RTC;
int thisHour;
	
// Initiate an instance of the SoftwareSerial class. Requires the pin numbers used for RX and TX.
SoftwareSerial swSerial(2, 3); // RX, TX

const char *verboseError(byte err)
{
	switch (err)
	{
	case ERROR_MBR_READ_ERROR:
		return "Error reading MBR";
		break;
	case ERROR_MBR_SIGNATURE:
		return "MBR Signature error";
		break;
	case ERROR_MBR_INVALID_FS:
		return "Unsupported filesystem";
		break;
	case ERROR_BOOTSEC_READ_ERROR:
		return "Error reading Boot Sector";
		break;
	case ERROR_BOOTSEC_SIGNATURE:
		return "Boot Sector Signature error";
		break;
	default:
		return "Unknown error";
		break;
	}
}



char* GetFileName(char* fileName, byte len)
{
	snprintf_P(fileName, len, PSTR("%02d-%02d-%02d.txt"), year(), month(), day());
	return fileName;
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
	Serial.println(F("Fewings Logger emon based on openenergymonitor.org"));

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
	
	for (int i = 0; i < MAX_NODES; i++)
	{
		txReceived[i] = 0;
		lastReceived[i] = now();
	}
	pktsReceived = 0;

	swSerial.begin(9600);
	swSerial.listen();

	file.setSSpin(9);
	byte initres = file.initFAT();
	Serial.print("Initialised:");
	Serial.print(initres);

	if (initres != NO_ERROR)
	{
		Serial.print("***** ERROR: ");
		Serial.println(verboseError(initres));
		//while (true) {};
	}



	digitalWrite(RED_LED, HIGH );
}
//--------------------------------------------------------------------------------------------


//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	char serialBuf[256] = "";



	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	if (rf12_recvDone())
	{
		if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)	// and no rf errors
		{
			int node_id = (rf12_hdr & 0x1F);
			byte buf[66];
			memcpy(buf, (void*)rf12_data, rf12_len);

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
				temperaturePayload = *(PayloadTemperature*)rf12_data;							// get emontx payload data
				EmonSerial::PrintTemperaturePayload(&temperaturePayload, (now() - lastReceived[eTemp]));				// print data to serial
				txReceived[eTemp]++;
				lastReceived[eTemp] = now();				// set time of last update to now
			}

			if (node_id == HWS_JEENODE)
			{
				PayloadHWS hwsPayload = *(PayloadHWS*)rf12_data;							// get emontx payload data
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
			
			if (node_id == BASE_JEENODE)						// jeenode base Receives the time
			{
				basePayload = *((PayloadBase*)rf12_data);
				EmonSerial::PrintBasePayload(&basePayload, (now() - lastReceived[eBase]));			 // print data to serial
				txReceived[eBase]++;
				lastReceived[eBase] = now();

				setTime(basePayload.time);
			}

			if (node_id == DISPLAY_NODE )
			{
				displayPayload = *((PayloadDisp*)rf12_data);
				EmonSerial::PrintDispPayload(&displayPayload, (now() - lastReceived[eDisplay]));			 // print data to serial
				txReceived[eDisplay]++;
				lastReceived[eDisplay] = now();
			}


			digitalWrite(RED_LED, LOW);
			delay(100);
			digitalWrite(RED_LED, HIGH);
		}
	}


	if( swSerial.isListening() && swSerial.available() )
	{
		digitalWrite(GREEN_LED, LOW);
		delay(100);
		digitalWrite(GREEN_LED, HIGH);
	}
	
	//if (swSerial.readBytesUntil('\r', serialBuf, 256))
	//{
	//	digitalWrite(GREEN_LED, LOW);
	//	delay(100);
	//	digitalWrite(GREEN_LED, HIGH);


	//	if (currentDay != 0)  //the time has been set!
	//	{
	//		char fileName[MAX_FILENAME_LEN];
	//		//yyyy-mm-dd.txt
	//		snprintf_P(fileName, MAX_FILENAME_LEN, PSTR("%02d-%02d-%02d.txt"), year(), month(), day());
	//		if (file.exists(fileName))
	//			file.openFile(fileName, FILEMODE_TEXT_WRITE);
	//		else
	//			file.create(fileName);
	//		//dd/mm/yyyy hh:mm:ss AM/PM
	//		char dateTime[23];
	//		snprintf_P(dateTime, 23, PSTR("%02d/%02d/%02d %02d:%02d:%02d %s,"), day(), month(), year(), hourFormat12(), minute(), second(), isAM() ? "AM" : "PM");

	//		file.writeLn(dateTime);
	//		file.writeLn(serialBuf);
	//		file.closeFile();

	//		digitalWrite(GREEN_LED, LOW);
	//		delay(100);
	//		digitalWrite(GREEN_LED, HIGH);

	//	}
	//}
} 
