#pragma once
#include <arduino.h>

//EEPROM settings stored for an individual node.
#define EEPROM_SETTINGS_BASE 260	//set to 300 to avoid overwriting EMON_LCD history (0-258)
#define EEPROM_SIZE 16						//size of stored data. Allow for new versions.
#define EEPROM_VERSION 1

typedef struct {
	byte version;				// version number of the stored settings
	byte relayNumber;		// the RELAY_N ID if we are a relay node
	byte subnode;				// the subnode number we are, if we are a subnode
	long relayNodes;		// bitwise OR of the nodes that we can relay
	byte pad[EEPROM_SIZE - 9];	//pad out the struct to fill the predefined space
	word crc;						//crc checksum.
} EEPROMSettings;

class EmonEEPROM {
public:
	static word CalcCrc(const void* ptr, byte len);
	static const char* NodeName(word node_id);

	static bool PrintNode(Stream& stream, const long nodeID);
	static void PrintEEPROMSettings(Stream& stream, const EEPROMSettings& settings);

	static bool ReadEEPROMSettings(EEPROMSettings& settings);
	static void WriteEEPROMSettings(EEPROMSettings& settings);
};
