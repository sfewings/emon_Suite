#ifndef EMON_SERIAL_H
#define EMON_SERIAL_H

//Note to make this available to sketches it must appear in the arduino libraries folder as a symbolic link
// mklink / J ..\..\arduino - 1.0.3\libraries\EmonShared EmonShared
//Junction created for ..\..\arduino - 1.0.3\libraries\EmonShared <<= == >> EmonShared
#ifdef MQTT_LIB
#ifdef _WIN32
	#define _CRT_SECURE_NO_WARNINGS //so we can use 'strtok' without error C4996: depricated
	#include <Windows.h>
#else
	#include <unistd.h>
#endif
typedef unsigned char uint8_t;
typedef unsigned int uint32_t; 
typedef unsigned char byte;
#include <time.h>
#else
#include <Arduino.h> //needed for Serial.println
#include <TimeLib.h>			// needed for time_t
#endif

//RF12 node ID allocation
#define BASE_JEENODE 10				//Nanode with LAN and NTP time
#define RAIN_NODE	12				//Rain gauge Jeenode with rainfall and outside temperature
#define PULSE_JEENODE 13			//JeeNode with power pulse from main switch board
#define DISPLAY_NODE 14				//Arduino with LCD display
#define TEMPERATURE_JEENODE 15		//Jeenode with multiple DS180B temperature sensors 
#define HWS_JEENODE 16				//Jeenode to connect to Heattrap solar hot water system. http://heat-trap.com.au
#define EMON_LOGGER 17				//Logger node. Not a transmitter
#define WATERLEVEL_NODE 18			//The water tank sensor
#define SCALE_NODE 19				//node that contains a load-cell
#define BATTERY_NODE 20				//Node for sending battery current and voltage readings
#define INVERTER_NODE 21			//Node for sending MPP inverter readings
#define BEEHIVEMONITOR_NODE 22		//Node for monitoring beehives
#define AIRQUALITY_NODE 23			//Node for Plantower PM7003 ar quality sensor
#define LEAF_NODE 24				//Node for Nissan Leaf sensor
#define GPS_NODE 25					//Node for GPS unit
#define PRESSURE_NODE 26			//Node for BM unit


#define MAX_SUBNODES	8			//Maximum number of disp and temp nodes supported
#define MAX_WATER_SENSORS	4		//Maximum number of water pulse and water height metres

#define PULSE_MAX_SENSORS 6			//number of pins and hence, readings on the pulse Jeenode. 6 is max for RF packet size 64 bytes
#define MAX_TEMPERATURE_SENSORS 4   //maximum number of temperature sensors on the temperature_JeeNode  
#define HWS_TEMPERATURES 7			//number of temperature readings from the hot water system
#define HWS_PUMPS 3					//number of pumps from the hot water system

#define BATTERY_SHUNTS	3			//number of battery banks in the system. Each with a shunt for measuring current in and out
#define MAX_VOLTAGES		9		//number of voltage measurements made on the battery monitoring system

#define FEWINGS_MONITOR_GROUP  211
#define TESTING_MONITOR_GROUP	 210

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
	byte subnode;							//subnode number
	int power[PULSE_MAX_SENSORS];				// power values
	unsigned long pulse[PULSE_MAX_SENSORS];	// pulse values 
	unsigned long supplyV;					// unit supply voltage
} PayloadPulse;


typedef struct PayloadRain :PayloadRelay{
	unsigned long rainCount;				//The count from the rain gauge
	unsigned long transmitCount;		//Increment for each time the rainCount is transmitted. When rainCount is changed, this value is 0 
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

#pragma pack(push, 1)
typedef struct PayloadWater : PayloadRelay {
	byte subnode;
	unsigned short supplyV;
	byte numSensors;															//contains num flow meters in lower 4 bits, num height meters in upper 4 bits;
	unsigned long flowCount[MAX_WATER_SENSORS];		//number of pulses since installation
	int waterHeight[MAX_WATER_SENSORS];						//water height in mm
} PayloadWater;
#pragma pack(pop)

typedef struct PayloadScale : PayloadRelay {
	byte subnode;			//allow multiple scale nodes on the network
	long grams;				//current scale readaing
	unsigned long supplyV;									// unit supply voltage
}PayloadScale;

typedef struct PayloadBattery : PayloadRelay {
	byte subnode;
	int power[BATTERY_SHUNTS];										//w
	unsigned long pulseIn[BATTERY_SHUNTS];				//wH
	unsigned long pulseOut[BATTERY_SHUNTS];				//wH
	short voltage[MAX_VOLTAGES];									//100th of v 
}PayloadBattery;

typedef struct PayloadInverter : PayloadRelay {
	byte subnode;                             // inverter number
	unsigned short activePower;               // W
	unsigned short apparentPower;             // VAR
	unsigned short batteryVoltage;            // 0.1V
	unsigned short batteryDischarge;          // A
	unsigned short batteryCharging;           // A
	unsigned short pvInputPower;              // W
	uint8_t batteryCapacity;                  // %
	unsigned long pulse;					  //total accumulated watt hours 
} PayloadInverter;

#pragma pack(push, 1)
typedef struct PayloadBeehive : PayloadRelay {
	byte subnode;                           // 
	unsigned short beeInRate;				//beesin per minute
	unsigned short beeOutRate;				//bees out per minute
	unsigned long beesIn;					//beesIn
	unsigned long beesOut;					//beesOut
	short temperatureIn;					//Temperature inside the hive
	short temperatureOut;					//temperature outside the hive
	long grams;								//current scale reading
	unsigned long supplyV;					// unit supply voltage
} PayloadBeehive;

typedef struct PayloadAirQuality : PayloadRelay {
	byte subnode;                           
	unsigned long pm0p3;                    // Particles Per Deciliter pm0.3 reading
	unsigned long pm0p5;                    // Particles Per Deciliter pm0.5 reading
	unsigned long pm1p0;                    // Particles Per Deciliter pm1.0 reading
	unsigned long pm2p5;                    // Particles Per Deciliter pm2.5 reading
	unsigned long pm5p0;                    // Particles Per Deciliter pm5.0 reading
	unsigned long pm10p0;                   // Particles Per Deciliter pm10.0 reading
} PayloadAirQuality;
#pragma pack(pop)

typedef struct PayloadLeaf : PayloadRelay {
	byte subnode;                           // 
	unsigned long   odometer;     			//odometer in KM
  	short  range;                 			//range in kilometers
  	short  batteryTemperature;    			//battery temperature in celsius
  	byte   batterySOH;            			//Battery state of health %
  	unsigned long batteryWH;      			//WH in battery
  	byte   batteryChargeBars;     			//Battery available charge bars. As displayed on the car.
	short  chargeTimeRemaining;   			//Charge time remaining in minutes
} PayloadLeaf;

typedef struct PayloadGPS : PayloadRelay {
	byte subnode;                           // 
	float latitude;
	float longitude;
	float course;
	float speed;
} PayloadGPS;

typedef struct PayloadPressure : PayloadRelay {
	byte subnode;
	float pressure;
	float temperature;
	float humidity;
} PayloadPressure;


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
	static void PrintBatteryPayload(PayloadBattery* pPayloadBattery, unsigned long timeSinceLast = 0);
	static void PrintInverterPayload(PayloadInverter* pPayloadInverter, unsigned long timeSinceLast = 0);
	static void PrintBeehivePayload(PayloadBeehive* pPayloadBeehive, unsigned long timeSinceLast = 0);
	static void PrintAirQualityPayload(PayloadAirQuality* pPayloadAirQuality, unsigned long timeSinceLast = 0);
	static void PrintLeafPayload(PayloadLeaf* pPayloadLeaf, unsigned long timeSinceLast = 0);
	static void PrintGPSPayload(PayloadGPS* pPayloadGPS, unsigned long timeSinceLast = 0);
	static void PrintPressurePayload(PayloadPressure* pPayloadPressure, unsigned long timeSinceLast = 0);
	
	static void PrintRelay(Stream& stream, PayloadRelay* pPayloadRely);

	static void PrintRainPayload(Stream& stream, PayloadRain* pPayloadRain, unsigned long timeSinceLast = 0);
	static void PrintBasePayload(Stream& stream, PayloadBase* pPayloadBase, unsigned long timeSinceLast = 0);
	static void PrintDispPayload(Stream& stream, PayloadDisp* pPayloadDisp, unsigned long timeSinceLast = 0);
	static void PrintPulsePayload(Stream& stream, PayloadPulse* pPayloadPulse, unsigned long timeSinceLast = 0);
	static void PrintTemperaturePayload(Stream& stream, PayloadTemperature* pPayloadTemperature, unsigned long timeSinceLast = 0);
	static void PrintHWSPayload(Stream& stream, PayloadHWS* pPayloadHWS, unsigned long timeSinceLast = 0);
	static void PrintWaterPayload(Stream& stream, PayloadWater* pPayloadWater, unsigned long timeSinceLast = 0);
	static void PrintScalePayload(Stream& stream, PayloadScale* pPayloadWater, unsigned long timeSinceLast = 0);
	static void PrintBatteryPayload(Stream& stream, PayloadBattery* pPayloadBattery, unsigned long timeSinceLast = 0);
	static void PrintInverterPayload(Stream& stream, PayloadInverter* pPayloadInverter, unsigned long timeSinceLast = 0);
	static void PrintBeehivePayload(Stream& stream, PayloadBeehive* pPayloadBeehive, unsigned long timeSinceLast = 0);
	static void PrintAirQualityPayload(Stream& stream, PayloadAirQuality* pPayloadAirQuality, unsigned long timeSinceLast = 0);
	static void PrintLeafPayload(Stream& stream, PayloadLeaf* pPayloadLeaf, unsigned long timeSinceLast = 0);
	static void PrintGPSPayload(Stream& stream, PayloadGPS* pPayloadGPS, unsigned long timeSinceLast = 0);
	static void PrintPressurePayload(Stream& stream, PayloadPressure* pPayloadPressure, unsigned long timeSinceLast = 0);
	

#endif
	static int PackWaterPayload(PayloadWater* pPayloadWater, byte* ptr);
	static int UnpackWaterPayload(byte* ptr, PayloadWater* pPayloadWater);

	static void ParseRelay(PayloadRelay* pPayloadRelay, char* pch);
	static int ParseRainPayload(char* str, PayloadRain *pPayloadRain);
	static int ParseBasePayload(char* str, PayloadBase *pPayloadBase);
	static int ParseDispPayload(char* str, PayloadDisp *pPayloadDisp);
	static int ParsePulsePayload(char* str, PayloadPulse *pPayloadPulse);
	static int ParseTemperaturePayload(char* str, PayloadTemperature *pPayloadTemperature);
	static int ParseHWSPayload(char* str, PayloadHWS *pPayloadHWS);
	static int ParseWaterPayload(char* str, PayloadWater *pPayloadWater);
	static int ParseScalePayload(char* str, PayloadScale* pPayloadScale);
	static int ParseBatteryPayload(char* str, PayloadBattery* pPayloadBattery);
	static int ParseInverterPayload(char* str, PayloadInverter* pPayloadInverter);
	static int ParseBeehivePayload(char* str, PayloadBeehive* pPayloadBeehive);
	static int ParseAirQualityPayload(char* str, PayloadAirQuality* pPayloadAirQuality);
	static int ParseLeafPayload(char* str, PayloadLeaf* pPayloadLeaf);
	static int ParseGPSPayload(char* str, PayloadGPS* pPayloadGPS);
	static int ParsePressurePayload(char* str, PayloadPressure* pPayloadPressure);
};


#endif //EMON_SERIAL_H