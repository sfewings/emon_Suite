//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_Logger. Receive each packet from an emon group and write to Serial
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include <EmonShared.h>

#include <SoftwareSerial.h>
#include <SD.h>

#include <TimeLib.h>


const int RED_LED=6;				 // Red tri-color LED
const int GREEN_LED = 5;		 // Red tri-color LED

byte  currentDay = 0;
#define MAX_FILENAME_LEN 15
#define DATETIME_LEN 24
#define MAX_SERIAL_BUF 120


char buf1[MAX_SERIAL_BUF];
char buf2[MAX_SERIAL_BUF];
byte bufIndex1;
byte bufIndex2;


SoftwareSerial softSerial(2,3);

File file;


//callback to provide creation date and time for SD card files
void dateTime(uint16_t* date, uint16_t* time)
{
	*date = FAT_DATE(year(), month(), day());
	*time = FAT_TIME(hour(), minute(), second());
}

bool WriteDateToFile()
{
	if (timeStatus() == timeSet )  //the time has been set!
	{
		char fileName[MAX_FILENAME_LEN];
		//yyyy-mm-dd.txt
		snprintf_P(fileName, MAX_FILENAME_LEN, PSTR("%02d%02d%02d-A.txt"), year()%100, month(), day());

		file = SD.open(fileName, FILE_WRITE);

		if (file)
		{
			//dd/mm/yyyy HH:mm:ss
			char dateTime[DATETIME_LEN];
			snprintf_P(dateTime, DATETIME_LEN, PSTR("%02d/%02d/%04d %02d:%02d:%02d,"), day(), month(), year(), hour(), minute(), second());
			file.print(dateTime);
			return true;
		}
	}

	return false;
}


#define PARSE(CMP,LEN,NAME, PAYLOAD)\
 if(strncmp(buf, CMP,LEN)==0)\
 {\
		Payload##NAME pl; \
		if (EmonSerial::Parse##NAME##PAYLOAD(buf, &pl) && WriteDateToFile())\
		{\
			digitalWrite(GREEN_LED, HIGH);\
			EmonSerial::Print##NAME##PAYLOAD(file, &pl); \
			file.close(); \
			return true;\
		}\
		return false;\
}



bool ParseBuffer(char* buf, byte bufIndex)
{
	//special case for base to set the time. Otherwise the parsing can be done with PARSE() macro
	if (strncmp(buf, "base", 4) == 0)
	{
		PayloadBase pl;
		if (EmonSerial::ParseBasePayload(buf, &pl))
		{
			setTime(pl.time);

			if (WriteDateToFile())
			{
				digitalWrite(GREEN_LED, HIGH);
				EmonSerial::PrintBasePayload(file, &pl);
				file.close();
				return true;
			}
		}
		return false;
}

	PARSE("temp", 4, Temperature, Payload)
	PARSE("pulse", 5, Pulse, Payload)
	PARSE("scl", 3, Scale, Payload)
	PARSE("disp", 4, Disp, Payload)
	PARSE("wtr", 3, Water, Payload)
	PARSE("rain", 4, Rain, Payload)
	PARSE("hws", 3, HWS, Payload)

	return false;
}


bool AddCharToBuffer(char ch, char* buf, byte& bufIndex)
{
	buf[bufIndex] = ch;
	if (ch == '\n')
	{
		buf[bufIndex] = '\0';
		Serial.print(buf);
		buf[bufIndex] = '\n';
		buf[bufIndex+1] = '\0';
		digitalWrite(RED_LED, HIGH);
		if (ParseBuffer(buf, bufIndex))
		{
			Serial.print(F("=>Logged"));
		}
		Serial.println();
		bufIndex = 0;
		digitalWrite(RED_LED, LOW);
		digitalWrite(GREEN_LED, LOW);
		return true;
	}
	else
	{
		if (++bufIndex == MAX_SERIAL_BUF-1)
		{
			Serial.print("Buffer overflow. Discarding stream: ");
			buf[bufIndex - 1] = '\0';
			Serial.println(buf);
			bufIndex = 0;
		}
	}
	return false;
}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
	Serial.begin(9600);
	
	pinMode(RED_LED, OUTPUT);
	pinMode(GREEN_LED, OUTPUT);

	digitalWrite(GREEN_LED, HIGH);
	digitalWrite(RED_LED, HIGH);

	delay(100);
	Serial.println(F("Fewings Serial emon Logger. Logging emon packets to SD card"));

	SdFile::dateTimeCallback(dateTime);

	Serial.print("Initializing SD card...");

	// see if the card is present and can be initialized:
	if (!SD.begin(9)) {
		Serial.println("Card failed, or not present");
		// don't do anything more:
		while (1);
	}
	Serial.println("card initialized.");


	softSerial.begin(9600);
	bufIndex1 = 0;
	bufIndex2 = 0;

	digitalWrite(GREEN_LED, LOW);
	digitalWrite(RED_LED, LOW);
}


void loop () 
{
	while (Serial.available())
	{
		AddCharToBuffer(Serial.read(), buf1, bufIndex1);
	}

	while (softSerial.available())
	{
		AddCharToBuffer(softSerial.read(), buf2, bufIndex2);
	}
} 
