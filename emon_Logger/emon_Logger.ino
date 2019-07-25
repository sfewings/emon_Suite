//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_Logger. Receive each packet from an emon group and write to Serial and SD card
//-------------------------------------------------------------------------------------------------------------------------------------------------


//JeeLab libraires				http://github.com/jcw
#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <EmonShared.h>
#include <SD.h>
#include <TimeLib.h>


const int RED_LED=6;	 
const int GREEN_LED = 5;

byte  currentDay = 0;

RF12Init rf12Init = { EMON_LOGGER, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

#define MAX_FILENAME_LEN 15
#define DATETIME_LEN 24


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
	digitalWrite(RED_LED, HIGH);		//Red LED has inverted logic. LOW is on, HIGH is off!
	Serial.begin(9600);
	
	delay(1000);
	Serial.println(F("Fewings emon Logger. Logging emon packets to SD card"));

	Serial.println(F("rf12_initialize"));
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);

	EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBasePayload(NULL);
	EmonSerial::PrintPulsePayload(NULL);
	EmonSerial::PrintDispPayload(NULL);
	EmonSerial::PrintTemperaturePayload(NULL);
	EmonSerial::PrintHWSPayload(NULL);
	EmonSerial::PrintWaterPayload(NULL);
	EmonSerial::PrintScalePayload(NULL);

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

	digitalWrite(GREEN_LED, LOW);
	digitalWrite(RED_LED, LOW);		//Red LED has inverted logic. LOW is on, HIGH is off!
}

#define PRINT_AND_LOG(NAME, PAYLOAD)\
		Payload##NAME* pPayload = (Payload##NAME*)rf12_data; \
		EmonSerial::Print##NAME##PAYLOAD(pPayload);\
		if(file) {\
			digitalWrite(GREEN_LED, HIGH);\
			file.print(dateTime);\
			EmonSerial::Print##NAME##PAYLOAD(file, pPayload); \
		}\



void loop () 
{
	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	if (rf12_recvDone())
	{
		digitalWrite(RED_LED, HIGH);

		if (rf12_crc)
		{
			Serial.print(F("rcv crc err:"));
			Serial.print(rf12_crc);
			Serial.print(F(",len:"));
			Serial.println(rf12_hdr);
		}

		if (rf12_crc == 0 && (rf12_hdr & RF12_HDR_CTL) == 0)	// and no rf errors
		{
			int node_id = (rf12_hdr & 0x1F);
			int subnode = 0;
			File file = File();
			char dateTime[DATETIME_LEN];

			if (currentDay != 0)  //the time has been set!
			{
				char fileName[MAX_FILENAME_LEN];
				//yyyy-mm-dd.txt
				snprintf_P(fileName, MAX_FILENAME_LEN, PSTR("%04d%02d%02d.txt"), year(), month(), day());

				file = SD.open(fileName, FILE_WRITE);

				//dd/mm/yyyy HH:mm:ss
				snprintf_P(dateTime, DATETIME_LEN, PSTR("%02d/%02d/%04d %02d:%02d:%02d,"), day(), month(), year(), hour(), minute(), second());
			}


			if (node_id == BASE_JEENODE)						// jeenode base Receives the time
			{
				PRINT_AND_LOG(Base, Payload);
				setTime(pPayload->time);
				currentDay = day();		//will indicate time is set
			}

			if (node_id == PULSE_JEENODE)						// === PULSE NODE ====
			{
				PRINT_AND_LOG(Pulse, Payload);
			}
			if (node_id == TEMPERATURE_JEENODE)
			{
				PRINT_AND_LOG(Temperature, Payload);
			}
			if (node_id == HWS_JEENODE )
			{
				PRINT_AND_LOG(HWS, Payload);
			}

			if (node_id == RAIN_NODE)				
			{
				PRINT_AND_LOG(Rain, Payload);
			}

			if (node_id == DISPLAY_NODE)
			{
				PRINT_AND_LOG(Disp, Payload);
			}

			if (node_id == WATERLEVEL_NODE)
			{
				PRINT_AND_LOG(Water, Payload);
			}

			if (node_id == SCALE_NODE)
			{
				PRINT_AND_LOG(Scale, Payload);
			}

			if (file)
				file.close();
		}
		

		digitalWrite(GREEN_LED, LOW);
		digitalWrite(RED_LED, LOW);
	}
} 
