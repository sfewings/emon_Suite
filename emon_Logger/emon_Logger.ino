//------------------------------------------------------------------------------------------------------------------------------------------------
//emon_Logger. Receive each packet from an emon group and write to Serial and SD card
//-------------------------------------------------------------------------------------------------------------------------------------------------

#include <Time.h>
#include <EmonShared.h>
#include <SD.h>
#include <TimeLib.h>

#include <SPI.h>
#include <RH_RF69.h>
// Singleton instance of the radio driver
RH_RF69 g_rf69;
#define RFM69_RST     4

#undef RTC_LIB

#ifdef RTC_LIB
#include <Wire.h>
#include "RTClib.h"
RTC_DS3231 rtc;
#endif

const int RED_LED=6;	 
const int GREEN_LED = 5;

byte  currentDay = 0;

#define MAX_FILENAME_LEN 15
#define DATETIME_LEN 24


//callback to provide creation date and time for SD card files
void dateTime(uint16_t* date, uint16_t* time)
{
	*date = FAT_DATE(year(), month(), day());
	*time = FAT_TIME(hour(), minute(), second());
}

void GetDateTimeStr(char* dateTime)
{
	//dd/mm/yyyy HH:mm:ss
	snprintf_P(dateTime, DATETIME_LEN, PSTR("%02d/%02d/%04d,%02d:%02d:%02d,"), day(), month(), year(), hour(), minute(), second());
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

	pinMode(RFM69_RST, OUTPUT);
	digitalWrite(RFM69_RST, LOW);
	delay(1);
	digitalWrite(RFM69_RST, HIGH);
	delay(10);
	digitalWrite(RFM69_RST, LOW);
	delay(10);


	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	Serial.println("RF69 initialise node: 10 Freq: 915MHz");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(BASE_JEENODE);

	EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBasePayload(NULL);
	EmonSerial::PrintPulsePayload(NULL);
	EmonSerial::PrintDispPayload(NULL);
	EmonSerial::PrintTemperaturePayload(NULL);
	EmonSerial::PrintHWSPayload(NULL);
	EmonSerial::PrintWaterPayload(NULL);
	EmonSerial::PrintScalePayload(NULL);
	EmonSerial::PrintBatteryPayload(NULL);
	EmonSerial::PrintInverterPayload(NULL);
	EmonSerial::PrintBeehivePayload(NULL);
	EmonSerial::PrintAirQualityPayload(NULL);
	EmonSerial::PrintLeafPayload(NULL);

	SdFile::dateTimeCallback(dateTime);

	digitalWrite(GREEN_LED, LOW);		//Red LED has inverted logic. LOW is on, HIGH is off!
	Serial.print("Initializing SD card...");

	// see if the card is present and can be initialized:
	if (!SD.begin(9)) {
		Serial.println(F("Card failed, or not present"));
		// don't do anything more:
		//while (1);
	}
	else
	{
		Serial.println(F("Card initialized."));
	}

#ifdef RTC_LIB
	if (!rtc.begin()) {
		Serial.println(F("Couldn't find RTC"));
	}

	if (rtc.lostPower()) 
	{
		Serial.println(F("RTC lost power"));
		// following line sets the RTC to the date & time this sketch was compiled
		rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));

		File file = File();
		file = SD.open(F("DateTime.txt"), FILE_READ);
		if (file)
		{
			Serial.println(F("Setting RTC from contents of DateTime.txt on SD card"));
			bool comment = false;
			int line = 0;
			int pos = 0;
			char date[20], time[20];
			while (file.available())
			{
				char ch = file.read();
				Serial.write(ch);
				if (pos == 0)
					comment = (ch == '#');
				if (ch == '\n')
				{
					pos = 0;
					if (!comment)
						line++;
				}
				else
				{
					if (pos < 20)
					{
						if (line == 1)
						{
							date[pos++] = ch;
							date[pos] = '\0';
						}
						else if (line == 2)
						{
							time[pos++] = ch;
							time[pos] = '\0';
						}
					}
				}
			}
			file.close();
			rtc.adjust(DateTime(date, time));
		}
		else
		{
			Serial.println(F("No real-time clock time set and no DateTime.txt file found on SD card"));
			Serial.println(F("Add a file and insert two lines with Date and Time in format \"Sep 12 2019\" \"17:20:00\""));
		}
		// This line sets the RTC with an explicit date & time, for example to set
		// January 21, 2014 at 3am you would call:

		// rtc.adjust(DateTime(2014, 1, 21, 3, 0, 0));
	}
	DateTime dt = rtc.now();

	setTime(dt.hour(), dt.minute(), dt.second(), dt.day(), dt.month(), dt.year());

	Serial.print(F("Arduino Date and Time set from RTC to "));
	char dateTime[DATETIME_LEN];
	GetDateTimeStr(dateTime);
	Serial.println(dateTime);
	currentDay = day();		//will indicate time is set
#endif

	digitalWrite(GREEN_LED, LOW);
	digitalWrite(RED_LED, LOW);		//Red LED has inverted logic. LOW is on, HIGH is off!
}

#define PRINT_AND_LOG(NAME, PAYLOAD)\
		Payload##NAME* pPayload = (Payload##NAME*)data; \
		EmonSerial::Print##NAME##PAYLOAD(pPayload);\
		if(file) {\
			file.print(dateTime);\
			EmonSerial::Print##NAME##PAYLOAD(file, pPayload); \
		}\



void loop () 
{
	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
	if (g_rf69.available())
	{
		volatile uint8_t *data = NULL;
		uint8_t len = 0;
		int node_id = 0;
		int led = RED_LED;

		//digitalWrite(RED_LED, HIGH);
		// Should be a message for us now   
		uint8_t buf[RH_RF69_MAX_MESSAGE_LEN];
		memset(buf, 0, RH_RF69_MAX_MESSAGE_LEN);
		len = sizeof(buf);
		if (g_rf69.recv(buf, &len))
		{
			//RH_RF69::printBuffer("Received: ", buf, len);
			//Serial.print("Got request: ");
			//Serial.print((char*)buf);
			Serial.print("RSSI: ");
			Serial.println(g_rf69.lastRssi(), DEC);

			node_id = g_rf69.headerId();
			data = buf;

			File file = File();
			char dateTime[DATETIME_LEN];
			
			if (currentDay != 0)  //the time has been set!
			{
				char fileName[MAX_FILENAME_LEN];
				//yyyy-mm-dd.txt
				snprintf_P(fileName, MAX_FILENAME_LEN, PSTR("%04d%02d%02d.txt"), year(), month(), day());
				if( SD.exists(fileName))
					led = GREEN_LED;  //note. THis doesn't work. If the card is ejected this still returns true!
				file = SD.open(fileName, FILE_WRITE);
				GetDateTimeStr(dateTime);
			}
			digitalWrite(led, HIGH);

			if (node_id == BASE_JEENODE && len == sizeof(PayloadBase))						// jeenode base Receives the time
			{
				PRINT_AND_LOG(Base, Payload);
				setTime(pPayload->time);
				currentDay = day();		//will indicate time is set
			}

			if (node_id == PULSE_JEENODE && len == sizeof(PayloadPulse))						// === PULSE NODE ====
			{
				PRINT_AND_LOG(Pulse, Payload);
			}
			if (node_id == TEMPERATURE_JEENODE && len == sizeof(PayloadTemperature))
			{
				PRINT_AND_LOG(Temperature, Payload);
			}
			if (node_id == HWS_JEENODE && len == sizeof(PayloadHWS))
			{
				PRINT_AND_LOG(HWS, Payload);
			}

			if (node_id == RAIN_NODE && len == sizeof(PayloadRain))				
			{
				PRINT_AND_LOG(Rain, Payload);
			}

			if (node_id == DISPLAY_NODE && len == sizeof(PayloadDisp))
			{
				PRINT_AND_LOG(Disp, Payload);
			}

			if (node_id == WATERLEVEL_NODE)
			{
				PayloadWater* pPayload = (PayloadWater*)data;
				int packedSize = EmonSerial::UnpackWaterPayload((byte*) pPayload, pPayload);
				if( packedSize == len) 
				{
					EmonSerial::PrintWaterPayload(pPayload);
					if(file) 
					{
						file.print(dateTime);
						EmonSerial::PrintWaterPayload(file, pPayload);
					}
				}
			}

			if (node_id == SCALE_NODE && len == sizeof(PayloadScale))
			{
				PRINT_AND_LOG(Scale, Payload);
			}

			if (node_id == BATTERY_NODE && len == sizeof(PayloadBattery))
			{
				PRINT_AND_LOG(Battery, Payload);
			}
			if (node_id == INVERTER_NODE  && len == sizeof(PayloadInverter))
			{
				PRINT_AND_LOG(Inverter, Payload);
			}
			if (node_id == BEEHIVEMONITOR_NODE  && len == sizeof(PayloadBeehive) )
			{
				PRINT_AND_LOG(Beehive, Payload);
			}
			if (node_id == AIRQUALITY_NODE  && len == sizeof(PayloadAirQuality))
			{
				PRINT_AND_LOG(AirQuality, Payload);
			}
			if (node_id == LEAF_NODE  && len == sizeof(PayloadLeaf))
			{
				PRINT_AND_LOG(Leaf, Payload);
			}
			if (node_id == GPS_NODE  && len == sizeof(PayloadGPS))
			{
				PRINT_AND_LOG(GPS, Payload);
			}
			if (node_id == PRESSURE_NODE  && len == sizeof(PayloadPressure))
			{
				PRINT_AND_LOG(Pressure, Payload);
			}
			if (node_id == DALY_BMS_NODE  && len == sizeof(PayloadDalyBMS)-2)
			{
				PRINT_AND_LOG(DalyBMS, Payload);
			}
			if (node_id == DALY_BMS_NODE && len == sizeof(PayloadDalyBMS))		//has crc
			{
				PayloadDalyBMS* pPayload = (PayloadDalyBMS*)data;
				if(pPayload->crc == EmonSerial::CalcCrc((const void *) data, sizeof(PayloadDalyBMS)-2) )
				{
					PRINT_AND_LOG(DalyBMS, Payload)
				}
				else
				{
					Serial.print(F("DalyBMS - Bad CRC"));
					Serial.print(pPayload->crc);
					Serial.print(F(", calculated CRC="));
					Serial.println( EmonSerial::CalcCrc((const void *) data, sizeof(PayloadBattery)-2) );
				}
			}

			if (file)
				file.close();
		}
		

		digitalWrite(GREEN_LED, LOW);
		digitalWrite(RED_LED, LOW);
	}
} 
