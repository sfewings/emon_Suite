#ifndef EMON_SERIAL_H
#define EMON_SERIAL_H

//Note to make this available to sketches it must appear in the arduino libraries folder as a symbolic link
// mklink / J ..\..\arduino - 1.0.3\libraries\EmonShared EmonShared
//Junction created for ..\..\arduino - 1.0.3\libraries\EmonShared <<= == >> EmonShared

#ifdef MQTT_LIB
#include <Windows.h>
typedef unsigned char uint8_t;
typedef unsigned int uint32_t; 
#else
#include <Arduino.h> //needed for Serial.println
#include <TimeLib.h>			// needed for time_t
#endif

//RF12 node ID allocation
#define BASE_JEENODE 10					//Nanode with LAN and NTP time
#define RAIN_NODE	12						//Rain gauge Jeenode with rainfall and outside temperature
#define PULSE_JEENODE 13				//JeeNode with power pulse from main switch board
#define DISPLAY_NODE 14					//Arduino with LCD display
#define TEMPERATURE_JEENODE 15	//Jeenode with multiple DS180B temperature sensors 
#define HWS_JEENODE 16					//Jeenode to connect to Heattrap solar hot water system. http://heat-trap.com.au
#define EMON_LOGGER 17					//Logger node. Not a transmitter
#define WATERLEVEL_NODE 18			//The water tank sensor
#define SCALE_NODE 19					  //node that contains a load-cell

#define MAX_SUBNODES	4					//Maximum number of disp and temp nodes supported

#define PULSE_NUM_PINS 4				//number of pins and hence, readings on the pulse Jeenode
#define MAX_TEMPERATURE_SENSORS 4  //maximum number of temperature sensors on the temperature_JeeNode  
#define HWS_TEMPERATURES 7			//number of temperature readings from the hot water system
#define HWS_PUMPS 3							//number of pumps from the hot water system

#define FEWINGS_MONITOR_GROUP  211

typedef struct RF12Init {
	uint8_t node;					//Should be unique on network, node ID 30 reserved for base station
	uint8_t freq;					//frequency - match to same frequency as RFM12B module (change to RF12_868MHZ or RF12_915MHZ as appropriate)
	uint8_t group;				//network group, must be same as emonTx and emonBase
	bool rf69compat;			//set to indicate the HOPE_RF is RF69 and not eh RF12b. Only for reporting!
}RF12Init;

////Nodes that can relay packets
#define RELAY_1  (0x1)
#define RELAY_2  (0x2)
#define RELAY_3  (0x4)
#define RELAY_4  (0x8)
#define RELAY_5  (0x10)
#define RELAY_6  (0x20)
#define RELAY_7  (0x40)
#define RELAY_8  (0x80)


//base struct for all data structs
typedef struct {
	byte relay;			//OR of all the relay units that have transmitted this packet. 0=original node transmit
} PayloadRelay;

typedef struct PayloadPulse: PayloadRelay{
	int power[PULSE_NUM_PINS];					// power values
	int pulse[PULSE_NUM_PINS];					// pulse values 
	int supplyV;												// unit supply voltage
} PayloadPulse;


typedef struct PayloadRain :PayloadRelay{
	volatile unsigned long rainCount;				//The count from the rain gauge
	volatile unsigned long transmitCount;		//Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
	int temperature;												//temperature in 100ths of degrees 
	unsigned long supplyV;									// unit supply voltage
}PayloadRain;

typedef struct PayloadDisp: PayloadRelay{													// from the LCD display. Collects room temperature
	byte subnode;														//allow multiple Display nodes on the network
	int temperature;												//temperature in 100th of degrees
} PayloadDisp;

typedef struct PayloadTemperature : PayloadRelay{													// from JeeNode with many temperature sensors
	byte subnode;														//allow multiple temperature nodes on the network
	unsigned long supplyV;									// unit supply voltage
	int numSensors;
	int temperature[MAX_TEMPERATURE_SENSORS];	//temperature in 100th of degrees
}PayloadTemperature;

typedef struct PayloadHWS : PayloadRelay {   // from JeeNode
	byte temperature[HWS_TEMPERATURES];			//temperature in degrees only
	bool pump[HWS_PUMPS];										//pump on or off
}PayloadHWS;

typedef struct PayloadBase: PayloadRelay {
	time_t time; 
}PayloadBase;

typedef struct PayloadWater: PayloadRelay {
	byte subnode;
	int waterHeight;
	int flowRate;			//water flowrate in l/min
	unsigned long flowCount;		//number of pulses since installation
} PayloadWater;

typedef struct PayloadScale : PayloadRelay {
	byte subnode;			//allow multiple scale nodes on the network
	long grams;				//current scale readaing
	unsigned long supplyV;									// unit supply voltage
}PayloadScale;



class EmonSerial{
public:
#ifndef MQTT_LIB
	static void PrintRF12Init(const RF12Init &rf12Init);

	static void PrintRainPayload(PayloadRain* pPayloadRain, unsigned long timeSinceLast = 0);
	static void PrintBasePayload(PayloadBase* pPayloadBase, unsigned long timeSinceLast = 0);
	static void PrintDispPayload(PayloadDisp* pPayloadDisp, unsigned long timeSinceLast = 0);
	static void PrintPulsePayload(PayloadPulse* pPayloadPulse, unsigned long timeSinceLast = 0);
	static void PrintTemperaturePayload(PayloadTemperature* pPayloadTemperature, unsigned long timeSinceLast = 0);
	static void PrintHWSPayload(PayloadHWS* pPayloadHWS, unsigned long timeSinceLast = 0);
	static void PrintWaterPayload(PayloadWater* pPayloadWater, unsigned long timeSinceLast = 0);
	static void PrintScalePayload(PayloadScale* pPayloadScale, unsigned long timeSinceLast = 0);

	//static String PrintBasePayload(String &str, PayloadBase *pPayloadBase, unsigned long timeSinceLast = 0);

	static void PrintRelay(Stream& stream, PayloadRelay* pPayloadRely);

	static void PrintRainPayload(Stream& stream, PayloadRain* pPayloadRain, unsigned long timeSinceLast = 0);
	static void PrintBasePayload(Stream& stream, PayloadBase* pPayloadBase, unsigned long timeSinceLast = 0);
	static void PrintDispPayload(Stream& stream, PayloadDisp* pPayloadDisp, unsigned long timeSinceLast = 0);
	static void PrintPulsePayload(Stream& stream, PayloadPulse* pPayloadPulse, unsigned long timeSinceLast = 0);
	static void PrintTemperaturePayload(Stream& stream, PayloadTemperature* pPayloadTemperature, unsigned long timeSinceLast = 0);
	static void PrintHWSPayload(Stream& stream, PayloadHWS* pPayloadHWS, unsigned long timeSinceLast = 0);
	static void PrintWaterPayload(Stream& stream, PayloadWater* pPayloadWater, unsigned long timeSinceLast = 0);
	static void PrintScalePayload(Stream& stream, PayloadScale* pPayloadWater, unsigned long timeSinceLast = 0);

#endif

	static void ParseRelay(PayloadRelay* pPayloadRelay, char* pch);
	static int ParseRainPayload(char* str, PayloadRain *pPayloadRain);
	static int ParseBasePayload(char* str, PayloadBase *pPayloadBase);
	static int ParseDispPayload(char* str, PayloadDisp *pPayloadDisp);
	static int ParsePulsePayload(char* str, PayloadPulse *pPayloadPulse);
	static int ParseTemperaturePayload(char* str, PayloadTemperature *pPayloadTemperature);
	static int ParseHWSPayload(char* str, PayloadHWS *pPayloadHWS);
	static int ParseWaterPayload(char* str, PayloadWater *pPayloadWater);
	static int ParseScalePayload(char* str, PayloadScale* pPayloadScale);
};


#endif //EMON_SERIAL_H