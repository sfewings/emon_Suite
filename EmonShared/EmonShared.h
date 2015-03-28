#ifndef EMON_SERIAL_H
#define EMON_SERIAL_H

//Note to make this available to sketches it must appear in the arduino libraries folder as a symbolic link
// mklink / J ..\..\arduino - 1.0.3\libraries\EmonShared EmonShared
//Junction created for ..\..\arduino - 1.0.3\libraries\EmonShared <<= == >> EmonShared

#include <Arduino.h> //needed for Serial.println
#include <Time.h>			// needed for time_t
//#include <string.h> //needed for memcpy


typedef struct {
	uint8_t node;					//Should be unique on network, node ID 30 reserved for base station
	uint8_t freq;					//frequency - match to same frequency as RFM12B module (change to RF12_868MHZ or RF12_915MHZ as appropriate)
	uint8_t group;				//network group, must be same as emonTx and emonBase
}RF12Init;

typedef struct {
	int power;					// power value
	int pulse;					//pulse increments 
	int ct1;						//CT reading 
	int supplyV;				// unit supply voltage
	int temperature;		//DB1820 temperature
	int rainGauge;			//rain gauge pulse
} PayloadEmon;

typedef struct {
	volatile unsigned long rainCount;				//The count from the rain gauge
	volatile unsigned long transmitCount;		//Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
	unsigned long supplyV;									// unit supply voltage
} PayloadRain;

typedef struct {
	time_t time; 
} PayloadBase;


class EmonSerial{
public:
	static void PrintRF12Init(const RF12Init &rf12Init);
	
	static void PrintEmonPayload(PayloadEmon* pPayloadEmon, unsigned long timeSinceLast = 0);
	static void PrintRainPayload(PayloadRain* pPayloadRain, unsigned long timeSinceLast = 0);
	static void PrintBasePayload(PayloadBase* pPayloadBase, unsigned long timeSinceLast = 0);
};

#endif //EMON_SERIAL_H