#include<EmonShared.h>
//#include <util/crc16.h>
//#include <util/parity.h>
#include <crc16.h>
#include <parity.h>

#include<SPIMemory.h>

SPIFlash flash(8);

#define EEPROM_VERSION  1

typedef struct BeehiveState
{
    byte version;
    unsigned long beesIn;					//beesIn
	unsigned long beesOut;					//beesOut
    long          tareGrams;
    word crc;
} BeehiveState;

BeehiveState beehiveState;

word CalcCrc(const void* ptr, byte len)
{
	word crc = ~0;
	for (byte i = 0; i < len; ++i)
		crc = _crc16_update(crc, ((const byte*)ptr)[i]);
	return crc;
}


bool writeBeehiveStateToSRAM(BeehiveState& beehiveState, uint32_t offset)
{
	uint8_t* pc = (uint8_t*)& beehiveState;
	beehiveState.version = EEPROM_VERSION;
	beehiveState.crc = CalcCrc(&beehiveState, sizeof(BeehiveState) - 2);

    flash.eraseSector(offset);

    bool ok = true;
	for (uint32_t l = 0; l < sizeof(BeehiveState); l++)
	{
        ok &= flash.writeByte(offset+l, *(pc + l));
	}
    if( !ok )   
        Serial.println("Write failed");
    return ok;
}

bool readBeehiveStateFromSRAM(BeehiveState & beehiveState, uint32_t offset)
{
	uint8_t* pc = (uint8_t*)& beehiveState;

    Serial.println((unsigned long) sizeof(BeehiveState));

	for (uint32_t l = 0; l < sizeof(BeehiveState); l++)
	{
		*(pc + l) = flash.readByte(offset + l);
	}
	if (beehiveState.crc != CalcCrc(&beehiveState, sizeof(BeehiveState) - 2))
	{
		//no settings. Set to defaults; relayNumber = 0, subnode = 0;
		memset(&beehiveState, 0, sizeof(BeehiveState));
        Serial.println("CRC error. beehiveState.crc=");
        Serial.println(beehiveState.crc);
		return 0;
	}
	if (beehiveState.version != EEPROM_VERSION)
	{
		//todo: deal with version conversion when required
	}

	return beehiveState.version;
}

void printBeehiveState(BeehiveState& beehiveState)
{
    Serial.print("version:   "); Serial.println(beehiveState.version);
    Serial.print("beesIn:    "); Serial.println(beehiveState.beesIn);
    Serial.print("beesOut:   "); Serial.println(beehiveState.beesOut);
    Serial.print("tareGrams: "); Serial.println(beehiveState.tareGrams);
    Serial.print("crc:       "); Serial.println(beehiveState.crc);
}

bool getID()
{
  Serial.println();
  Serial.print("Beehive SPI memory test");
  uint32_t JEDEC = flash.getJEDECID();
  if (!JEDEC) 
  {
    Serial.println("No comms. Check wiring. Is chip supported? If unable to fix, raise an issue on Github");
    return false;
  }
  else 
  {
    Serial.print("JEDEC ID: 0x");
    Serial.println(JEDEC, HEX);
    Serial.print("Man ID: 0x");
    Serial.println(uint8_t(JEDEC >> 16), HEX);
    Serial.print("Memory ID: 0x");
    Serial.println(uint8_t(JEDEC >> 8), HEX);
    Serial.print("Capacity: ");
    Serial.println(flash.getCapacity());
    Serial.print("Max Pages: ");
    Serial.println(flash.getMaxPage());
    long long _uniqueID = flash.getUniqueID();
    if (_uniqueID) 
    {
        Serial.print("Unique ID: ");
        Serial.print(uint32_t(_uniqueID / 1000000L));
        Serial.print(uint32_t(_uniqueID % 1000000L));
        Serial.print(", ");
        Serial.print("0x");
        Serial.print(uint32_t(_uniqueID >> 32), HEX);
        Serial.print(uint32_t(_uniqueID), HEX);
        Serial.println();
    }
  }
  return true;
}


void setup()
{
    Serial.begin(9600);

    if (flash.error()) 
    {
        Serial.println(flash.error(VERBOSE));
    }

    flash.begin();

    getID();

    beehiveState.beesIn = 0;
    beehiveState.beesOut = 0;
    beehiveState.tareGrams = 0;

    readBeehiveStateFromSRAM(beehiveState, 100);
    printBeehiveState(beehiveState);

    beehiveState.beesIn += 1;
    beehiveState.beesOut += 10;
    beehiveState.tareGrams += 100;

    writeBeehiveStateToSRAM(beehiveState, 100);
    printBeehiveState(beehiveState);
} 


void loop()
{

}