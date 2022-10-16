//------------------------------------------------------------------------------------------------------------------------------------------------
// FlashOnATTiny85
// Use Digispark (Default - 16.5mhz)(Digistump AVR Boards) board configuration
//Follow instructions for installing and uploading to ATTiny at  https://diyusthad.com/2021/07/digispark-attiny85.html
//-------------------------------------------------------------------------------------------------------------------------------------------------
#include "SoftwareSerial.h"
#include <EEPROM.h>
#include <util/crc16.h>
#include <util/parity.h>

SoftwareSerial serial(2,3);  //rx, tx
 
//EEPROM settings stored for an individual node.
#define EEPROM_SETTINGS_BASE 0
#define EEPROM_SIZE 16						//size of stored data. Allow for new versions.
#define EEPROM_VERSION 1

typedef enum { WaitingForCommand, RequestSettings, SetSubnode, SetBeesIn, SetBeesOut, SetGramsTare} Command;

typedef struct {
	byte version;				// version number of the stored settings
	byte subnode;				// the subnode number
	unsigned long beesIn;		//total beesIn
	unsigned long beesOut;		//total beesOut
	long gramsTare;				//scale tare reading

	byte pad[EEPROM_SIZE - 16];	//pad out the struct to fill the predefined space
	word crc;						//crc checksum.
} BeehiveSettings;

BeehiveSettings g_beehiveSettings;
Command g_command;
bool g_negative;

word CalcCrc(const void* ptr, byte len)
{
	word crc = ~0;
	for (byte i = 0; i < len; ++i)
		crc = _crc16_update(crc, ((const byte*)ptr)[i]);
	return crc;
}


bool ReadBeehiveSettings(BeehiveSettings& beehiveSettings)
{
	char* pc = (char*)& beehiveSettings;

	for (long l = 0; l < sizeof(BeehiveSettings); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_SETTINGS_BASE + l);
	}
	if (beehiveSettings.crc != CalcCrc(&beehiveSettings, sizeof(BeehiveSettings) - 2))
	{
		memset(&beehiveSettings, 0, sizeof(BeehiveSettings));
		return 0;
	}
	if (beehiveSettings.version != EEPROM_VERSION)
	{
		//todo: deal with version conversion when required
	}

	return beehiveSettings.version;
}


void WriteBeehiveSettings(BeehiveSettings &beehiveSettings )
{
	char* pc = (char*)& beehiveSettings;
	beehiveSettings.crc = CalcCrc(&beehiveSettings, sizeof(BeehiveSettings) - 2);

	for (long l = 0; l < sizeof(beehiveSettings); l++)
	{
		EEPROM.write(EEPROM_SETTINGS_BASE + l, *(pc + l));
	}    
}

void SendBeehiveSettings(BeehiveSettings &beehiveSettings)
{
    char sendStr[40];
    sprintf(sendStr, "n%d", beehiveSettings.subnode);
    serial.println(sendStr);
    sprintf(sendStr, "i%ld", beehiveSettings.beesIn);
    serial.println(sendStr);
    sprintf(sendStr, "o%ld", beehiveSettings.beesOut);
    serial.println(sendStr);
    sprintf(sendStr, "g%ld", beehiveSettings.gramsTare);
    serial.println(sendStr);
}


void handleInput (char c, BeehiveSettings & beehiveSettings) 
{
    if ('0' <= c && c <= '9') 
    {
        unsigned long digit = c - '0';
        
        switch( g_command )
        {
            case WaitingForCommand:
            case RequestSettings:
            //nothing to do with digits
            break;
            case SetBeesIn:
                beehiveSettings.beesIn = beehiveSettings.beesIn * 10 + digit;
                break;
            case SetBeesOut:
                beehiveSettings.beesOut = beehiveSettings.beesOut *10 + digit;;
                break;
            case SetGramsTare:
                beehiveSettings.gramsTare = beehiveSettings.gramsTare *10 + digit;
                break;
            case SetSubnode:
                beehiveSettings.subnode = beehiveSettings.subnode *10 + digit;;
                break;
        }    
        return;
    }
    
    if (c == '-')
    {
        g_negative = true;
        return;     
    }

    if (c == '\n')
    {
        switch( g_command)
        {
            case WaitingForCommand:
                break;
            case RequestSettings:
                ReadBeehiveSettings( beehiveSettings );
                SendBeehiveSettings( beehiveSettings );
                break;
            case SetGramsTare:
                if( g_negative )
                    beehiveSettings.gramsTare = -1*beehiveSettings.gramsTare;
                WriteBeehiveSettings(beehiveSettings);
                break;
            case SetSubnode:
            case SetBeesIn:
            case SetBeesOut:
                WriteBeehiveSettings(beehiveSettings);
                break;
        }   
        g_command = WaitingForCommand; 
        g_negative = false;
        return;
    }

    switch (c)
	{
        //zero values waiting for the incoming digits
        case 'n':
            g_command = SetSubnode;
            beehiveSettings.subnode = 0;
      	    break;
        case 'r':
            g_command = RequestSettings;
      	    break;
        case 'i':
            g_command = SetBeesIn;
            beehiveSettings.beesIn = 0;
      	    break;
        case 'o':
            g_command = SetBeesOut;
            beehiveSettings.beesOut = 0;
      	    break;
        case 'g':
            g_command = SetGramsTare;
            beehiveSettings.gramsTare = 0;
      	    break;
     }
}



void setup()
{
    serial.begin(9600);
    serial.println(F("Beehive flash on ATTiny85"));
    serial.println(F("r=read values"));
    serial.println(F("set value:g[+-val]=tareGrams, i[val]=beesIn, o=[val]beesOut, n[val]=subnode"));

    memset(&g_beehiveSettings, 0, sizeof(BeehiveSettings) );

    g_beehiveSettings.subnode = 0;
    g_beehiveSettings.beesIn = 0;
    g_beehiveSettings.beesOut = 0;
    g_beehiveSettings.gramsTare = 0;
    //Initialisation of EEPROMSettings
    //WriteBeehiveSettings( g_beehiveSettings );

    ReadBeehiveSettings( g_beehiveSettings);

    g_command = WaitingForCommand;
    g_negative = false;
}
 
void loop()
{
    //read the beesIn and beesOut or gramsTare values from the SerialIn 
    if (serial.available())
        handleInput(serial.read(), g_beehiveSettings);
}
