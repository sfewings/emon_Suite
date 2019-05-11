#ifndef EMON_SERIAL_H
#define EMON_SERIAL_H

//Note to make this available to sketches it must appear in the arduino libraries folder as a symbolic link
// mklink / J ..\..\arduino - 1.0.3\libraries\EmonShared EmonShared
//Junction created for ..\..\arduino - 1.0.3\libraries\EmonShared <<= == >> EmonShared

#include <Arduino.h> //needed for Serial.println
#include <Time.h>			// needed for time_t
//#include <string.h> //needed for memcpy


//RF12 node ID allocation
#define EMON_NODE	10						//Emon Tx with Power and Solar readings
#define RAIN_NODE	11						//Rain gauge Jeenode with rainfall and outside temperature
#define PULSE_JEENODE 12				//JeeNode with power pulse from main switch board
#define BASE_JEENODE 16					//Nanode with LAN and NTP time
#define DISPLAY_NODE 20					//Arduino with LCD display
#define TEMPERATURE_JEENODE 21	//Jeenode with multiple DS180B temperature sensors 
#define HWS_JEENODE 22					//Jeenode to connect to Heattrap solar hot water system. http://heat-trap.com.au
#define HWS_JEENODE_RELAY 23		//Relay packet HWS_JEENODE
#define EMON_LOGGER 24					//Logger node. Not a transmitter
#define TEMPERATURE_JEENODE_2 25	//Jeenode with multiple DS180B temperature sensors 
#define WATERLEVEL_NODE 26			//The water tank sensor

#define PULSE_NUM_PINS 4				//number of pins and hence, readings on the pulse Jeenode
#define MAX_TEMPERATURE_SENSORS 10  //maximum number of temperature sensors on the temperature_JeeNode  
#define HWS_TEMPERATURES 7			//number of temperature readings from the hot water system
#define HWS_PUMPS 3							//number of pumps from the hot water system

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
	int power[PULSE_NUM_PINS];					// power values
	int pulse[PULSE_NUM_PINS];					// pulse values 
	int supplyV;												// unit supply voltage
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

typedef struct {													// from JeeNode with many temperature sensors
	int numSensors;
	int temperature[MAX_TEMPERATURE_SENSORS+1];	//temperature in 100th of degrees. +1 for supplyV
} PayloadTemperature;

typedef struct PayloadHWS {   // from JeeNode
	byte temperature[HWS_TEMPERATURES];			//temperature in degrees only
	bool pump[HWS_PUMPS];										//pump on or off
};

typedef struct {
	time_t time; 
} PayloadBase;

typedef struct
{
	int waterHeight;
	uint32_t sensorReading;
} PayloadWater;

////Nodes that can relay packets
//#define EMON_RELAY_DISP 0x1
//#define EMON_RELAY_NODE 0x2
//#define EMON_RELAY_DISP2 0x4;
//
//typedef struct {
//	byte relay;
//} PayloadRelay;
//
//typedef struct PayloadHWSRelay : PayloadRelay, PayloadHWS { };


class EmonSerial{
public:
	static void PrintRF12Init(const RF12Init &rf12Init);
	
	static void PrintEmonPayload(PayloadEmon* pPayloadEmon, unsigned long timeSinceLast = 0);
	static void PrintRainPayload(PayloadRain* pPayloadRain, unsigned long timeSinceLast = 0);
	static void PrintBasePayload(PayloadBase* pPayloadBase, unsigned long timeSinceLast = 0);
	static void PrintDispPayload(PayloadDisp* pPayloadDisp, unsigned long timeSinceLast = 0);
	static void PrintPulsePayload(PayloadPulse* pPayloadPulse, unsigned long timeSinceLast = 0);
	static void PrintTemperaturePayload(PayloadTemperature* pPayloadTemperature, unsigned long timeSinceLast = 0);
	static void PrintHWSPayload(PayloadHWS* pPayloadHWS, unsigned long timeSinceLast = 0);
	static void PrintWaterPayload(PayloadWater* pPayloadWater, unsigned long timeSinceLast = 0);

	static String PrintBasePayload(String &str, PayloadBase *pPayloadBase, unsigned long timeSinceLast = 0);

	static void PrintEmonPayload(Stream& stream, PayloadEmon* pPayloadEmon, unsigned long timeSinceLast = 0);
	static void PrintRainPayload(Stream& stream, PayloadRain* pPayloadRain, unsigned long timeSinceLast = 0);
	static void PrintBasePayload(Stream& stream, PayloadBase* pPayloadBase, unsigned long timeSinceLast = 0);
	static void PrintDispPayload(Stream& stream, PayloadDisp* pPayloadDisp, unsigned long timeSinceLast = 0);
	static void PrintPulsePayload(Stream& stream, PayloadPulse* pPayloadPulse, unsigned long timeSinceLast = 0);
	static void PrintTemperaturePayload(Stream& stream, PayloadTemperature* pPayloadTemperature, unsigned long timeSinceLast = 0);
	static void PrintHWSPayload(Stream& stream, PayloadHWS* pPayloadHWS, unsigned long timeSinceLast = 0);
	static void PrintWaterPayload(Stream& stream, PayloadWater* pPayloadWater, unsigned long timeSinceLast = 0);


	static int ParseEmonPayload(char* str, PayloadEmon *pPayloadEmon);
	static int ParseRainPayload(char* str, PayloadRain *pPayloadRain);
	static int ParseBasePayload(char* str, PayloadBase *pPayloadBase);
	static int ParseDispPayload(char* str, PayloadDisp *pPayloadDisp);
	static int ParsePulsePayload(char* str, PayloadPulse *pPayloadPulse);
	static int ParseTemperaturePayload(char* str, PayloadTemperature *pPayloadTemperature);
	static int ParseHWSPayload(char* str, PayloadHWS *pPayloadHWS);
	static int ParseWaterPayload(char* str, PayloadWater *pPayloadWater);
};


#endif //EMON_SERIAL_H