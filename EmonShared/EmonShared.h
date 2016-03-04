#ifndef EMON_SERIAL_H
#define EMON_SERIAL_H

//Note to make this available to sketches it must appear in the arduino libraries folder as a symbolic link
// mklink / J ..\..\arduino - 1.0.3\libraries\EmonShared EmonShared
//Junction created for ..\..\arduino - 1.0.3\libraries\EmonShared <<= == >> EmonShared

#include <Arduino.h> //needed for Serial.println
#include <Time.h>			// needed for time_t
//#include <string.h> //needed for memcpy

//RF12 node ID allocation
#define EMON_NODE	10
#define RAIN_NODE	11
#define BASE_NODE	15
#define BASE_JEENODE 16
#define DISPLAY_NODE 20

#define FEWINGS_MONITOR_GROUP  210

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
	int temperature;												//temperature in 100ths of degrees 
	unsigned long supplyV;									// unit supply voltage
} PayloadRain;

typedef struct {													// from the LCD display. Collects room temperature
	int temperature;												//temperature in 100th of degrees
} PayloadDisp;




typedef struct {
	time_t time; 
} PayloadBase;


class EmonSerial{
public:
	static void PrintRF12Init(const RF12Init &rf12Init);
	
	static void PrintEmonPayload(PayloadEmon* pPayloadEmon, unsigned long timeSinceLast = 0);
	static void PrintRainPayload(PayloadRain* pPayloadRain, unsigned long timeSinceLast = 0);
	static void PrintBasePayload(PayloadBase* pPayloadBase, unsigned long timeSinceLast = 0);
	static void PrintDispPayload(PayloadDisp* pPayloadDisp, unsigned long timeSinceLast = 0);

	//String PrintEmonPayload(String &str, PayloadEmon *pPayloadEmon, unsigned long timeSinceLast = 0);
	//String PrintRainPayload(String &str, PayloadRain *pPayloadRain, unsigned long timeSinceLast = 0);
	static String PrintBasePayload(String &str, PayloadBase *pPayloadBase, unsigned long timeSinceLast = 0);

	static int ParseEmonPayload(char* str, PayloadEmon *pPayloadEmon);
	static int ParseRainPayload(char* str, PayloadRain *pPayloadRain);
	static int ParseBasePayload(char* str, PayloadBase *pPayloadBase);
	static int ParseDispPayload(char* str, PayloadDisp *pPayloadDisp);
};

#endif //EMON_SERIAL_H