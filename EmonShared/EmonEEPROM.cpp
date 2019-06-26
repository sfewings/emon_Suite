#include <EEPROM.h>
#include <util/crc16.h>
#include <util/parity.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>


word EmonEEPROM::CalcCrc(const void* ptr, byte len)
{
	word crc = ~0;
	for (byte i = 0; i < len; ++i)
		crc = _crc16_update(crc, ((const byte*)ptr)[i]);
	return crc;
}

//uses 62 bytes of precious RAM!
const char rain_str[] PROGMEM = "rain";
const char base_str[] PROGMEM = "base";
const char pulse_str[] PROGMEM = "pulse";
const char disp_str[] PROGMEM = "disp";
const char temp_str[] PROGMEM = "temp";
const char hws_str[] PROGMEM = "hws";
const char log_str[] PROGMEM = "log";
const char wtr_str[] PROGMEM = "wtr";
const char scl_str[] PROGMEM = "scl";
const char empty_str[] PROGMEM = "";
char nodeNameBuf[8];	//make sure none of the names are more than 8 chars. Including NULL termination

const char* EmonEEPROM::NodeName(word nodeID)
{
	switch (nodeID)
	{
	case RAIN_NODE:	strcpy_P(nodeNameBuf, rain_str); break;
	case PULSE_JEENODE: strcpy_P(nodeNameBuf, pulse_str); break;
	case BASE_JEENODE: strcpy_P(nodeNameBuf, base_str); break;
	case DISPLAY_NODE: strcpy_P(nodeNameBuf, disp_str); break;
	case TEMPERATURE_JEENODE: strcpy_P(nodeNameBuf, temp_str); break;
	case HWS_JEENODE: strcpy_P(nodeNameBuf, hws_str); break;
	case EMON_LOGGER: strcpy_P(nodeNameBuf, log_str); break;
	case WATERLEVEL_NODE: strcpy_P(nodeNameBuf, wtr_str); break;
	case SCALE_NODE: strcpy_P(nodeNameBuf, scl_str); break;
	default: strcpy_P(nodeNameBuf, empty_str);
	}
	return nodeNameBuf;
}

bool EmonEEPROM::PrintNode(Stream& stream, const long nodeID)
{
	if (strlen(NodeName(nodeID)) == 0)
		return false;
	else
		stream.print(NodeName(nodeID));
	return true;
}

void EmonEEPROM::PrintEEPROMSettings(Stream& stream, const EEPROMSettings& settings)
{
	stream.print(F("EEPROM Settings. version :"));
	stream.print(settings.version);
	stream.print(F(", relay:"));
	stream.print(settings.relayNumber);
	stream.print(F(", subnode:"));
	stream.print(settings.subnode);
	stream.print(F(", relayNodes:("));
	stream.print(settings.relayNodes);
	stream.print(F(")"));
	bool first = true;
	for (long l = 0; l < 32; l++)
	{
		if (settings.relayNodes & ((long)1 << l))
		{
			if (first)
				first = false;
			else
				stream.print(F("|"));
			if( !PrintNode(stream, l) )
				stream.print(F("?"));
		}
	}
	stream.println();
}

bool EmonEEPROM::ReadEEPROMSettings(EEPROMSettings& settings)
{
	char* pc = (char*)& settings;

	for (long l = 0; l < sizeof(settings); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_SETTINGS_BASE + l);
	}
	if (settings.crc != CalcCrc(&settings, sizeof(settings) - 2))
	{
		//no settings. Set to defaults; relayNumber = 0, subnode = 0;
		memset(&settings, 0, sizeof(settings));
		return 0;
	}
	if (settings.version != EEPROM_VERSION)
	{
		//todo: deal with version conversion when required
	}

	return settings.version;
}

void EmonEEPROM::WriteEEPROMSettings(EEPROMSettings & settings)
{
	char* pc = (char*)& settings;
	settings.version = EEPROM_VERSION;
	settings.crc = CalcCrc(&settings, sizeof settings - 2);

	for (long l = 0; l < sizeof(settings); l++)
	{
		EEPROM.write(EEPROM_SETTINGS_BASE + l, *(pc + l));
	}
}

