#ifndef EMON_SERIAL_H
#define EMON_SERIAL_H

//Note to make this available to sketches it must appear in the arduino libraries folder as a symbolic link
// mklink / J ..\..\arduino - 1.0.3\libraries\EmonShared EmonShared
//Junction created for ..\..\arduino - 1.0.3\libraries\EmonShared <<= == >> EmonShared

#include <Arduino.h> //needed for Serial.println
#include <Time.h>			// needed for time_t
//#include <string.h> //needed for memcpy

//RF12 node ID allocation
#define EMON_NODE	10				//Emon Tx with Power and Solar readings
#define RAIN_NODE	11				//Rain gauge Jeenode with rainfall and outside temperature
#define PULSE_JEENODE 12				//JeeNode with power pulse from main switch board
#define EMON_TEMP_NODE	15			//Emon Tx with Temperature of hot water system
#define BASE_JEENODE 16				//Nanode with LAN and NTP time
#define DISPLAY_NODE 20				//Arduino with LCD display

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
	int power1;					// power value
	int pulse1;					//pulse increments 
	int power2;					// power value
	int pulse2;					//pulse increments 
	int supplyV;				// unit supply voltage
} PayloadPulse;



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
	static void PrintPulsePayload(PayloadPulse* pPayloadPulse, unsigned long timeSinceLast = 0);

	//String PrintEmonPayload(String &str, PayloadEmon *pPayloadEmon, unsigned long timeSinceLast = 0);
	//String PrintRainPayload(String &str, PayloadRain *pPayloadRain, unsigned long timeSinceLast = 0);
	static String PrintBasePayload(String &str, PayloadBase *pPayloadBase, unsigned long timeSinceLast = 0);

	static int ParseEmonPayload(char* str, PayloadEmon *pPayloadEmon);
	static int ParseRainPayload(char* str, PayloadRain *pPayloadRain);
	static int ParseBasePayload(char* str, PayloadBase *pPayloadBase);
	static int ParseDispPayload(char* str, PayloadDisp *pPayloadDisp);
	//static int ParsePulsePayload(char* str, PayloadPulse *pPayloadPulse);
};

#endif //EMON_SERIAL_H