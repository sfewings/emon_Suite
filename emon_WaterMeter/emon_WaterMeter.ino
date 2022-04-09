//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------

#include <JeeLib.h>			// still required for sleepy::
#include <PinChangeInt.h>
#include <EEPROM.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>

#include <SPI.h>
#include <RH_RF69.h>

RH_RF69 g_rf69;

#define GREEN_LED 9			// Green LED on emonTx
#define HALL_EFFECT_PIN A1
#define FLOW_INTERRUPT_PIN 4
#define EEPROM_BASE 0x10	//where the water count is stored
#define HALL_PEAK_THRESHOLD 3	//the minimum change in reading required to signal a change from rising to falling
#define VOLTAGE_MEASURE_PIN 		A0

bool g_lastActivity = false;

//currently hard-coded flowCount[0] is water metre on hall effect A0 pin, flowCount[1] is bore pulse 
const double PulsePerDeciLitre[2] = { 0.1, 26.0 };

enum calibrationStep { eInit, eStart, eWaitingForPeak, eFirstPass, eSecondPass, eCalculate, eFinished };
typedef struct HallEffectStateType
{
	int calibrationStep;
	bool rising;
	int maxValue, minValue;
	int maxCalibration, minCalibration;
	int lastValue;
	int lValue[10];
	int lastSector;
} HallEffectStateType;

HallEffectStateType g_hallEffectState;

volatile unsigned long	g_flowCount = 0;		//number of pulses in total since installation

PayloadWater g_waterPayload;

ISR(WDT_vect) { Sleepy::watchdogEvent(); }


unsigned long readEEPROM(int offset)
{
	unsigned long value = 0;
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(unsigned long); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_BASE + offset*sizeof(unsigned long) + l);
	}

	return value;
}

void writeEEPROM(int offset, unsigned long value)
{
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(unsigned long); l++)
	{
		EEPROM.write(EEPROM_BASE + offset * sizeof(unsigned long) + l, *(pc + l));
	}
}


void interruptHandlerWaterFlow()
{
	//digitalWrite(GREEN_LED, g_toggleLED?HIGH:LOW);		//LED has inverted logic. LOW is on, HIGH is off!
	//g_toggleLED = !g_toggleLED;

	g_flowCount++;								//Update number of pulses, 1 pulse = 1 watt
}




int ServiceHallEffectSensor(struct HallEffectStateType &state)
{
	int litresReturn = 0;
	int value = analogRead(HALL_EFFECT_PIN);

	//Calibration process
	if (state.calibrationStep == eInit )
	{
		//Print the header of log details during calibration
		Serial.println(F("Caliration,step,enter routine rising(+)/falling(-),exit routine rising(+)/falling(-),analogue reading,number of litres"));
		state.calibrationStep = eStart;
		return 0;
	}
	else if (state.calibrationStep != eFinished)
	{
		Serial.print("Calibrating step,");
		switch(state.calibrationStep)
		{
			case eStart: 			Serial.print(F("start           "));break;
			case eWaitingForPeak:	Serial.print(F("waiting for peak"));break;
			case eFirstPass:		Serial.print(F("first pass      "));break;
			case eSecondPass:		Serial.print(F("second pass     "));break;
			case eCalculate:		Serial.print(F("calculating     "));break;
			case eFinished:			Serial.print(F("finished        "));break;
		}
		
		Serial.print(",");
		Serial.print((state.rising?"+":"-"));
		Serial.print(",");

		switch (state.calibrationStep)
		{
		case eStart:
			state.minCalibration = value;
			state.maxCalibration = value;
			if (value < state.lastValue)
			{
				state.rising = false;
				state.calibrationStep = eWaitingForPeak;
			}
			else if (value > state.lastValue)
			{
				state.rising = true;
				state.calibrationStep = eWaitingForPeak;
			}
			break;
		case eWaitingForPeak:
		case eFirstPass:
		case eSecondPass:
			if (state.rising)
			{
				if (value > state.maxCalibration)
				{
					state.maxCalibration = value;
				}
				else if (value < state.lastValue && fabs(value - state.maxCalibration) > HALL_PEAK_THRESHOLD)  //be sure that the fall is more than 5/1024 of range to remove noise at top of readings
				{
					state.rising = false;
					state.calibrationStep++;
				}
			}
			else //falling
			{
				if (value < state.minCalibration)
				{
					state.minCalibration = value;
				}
				else if (value > state.lastValue && fabs(value - state.minCalibration) > HALL_PEAK_THRESHOLD)
				{
					state.rising = true;
					state.calibrationStep++;
				}
			}
			break;
		case eCalculate:
			{
				if (state.maxCalibration - state.minCalibration > 40) //40 of range 0 - 1024 (100/1024 * 5v)
				{
					Serial.println("Calibration values: ");
					Serial.print(" minCalibration=");
					Serial.print(state.minCalibration);
					Serial.print(" maxCalibration=");
					Serial.println(state.maxCalibration);
					for (int i = 0; i < 10; i++)
					{
						state.lValue[i] = (state.maxCalibration + state.minCalibration)/2 + (state.maxCalibration - state.minCalibration)/2 * sin((-72 + (double)i * 36.0)*PI/180);  //9, 27, 45, 63, 81, 99, 117, 135, 153, 171  degrees
						//Serial.print((int)(-81 + (double)i * 36.0));
						Serial.print("(");
						Serial.print(i);
						Serial.print(")");
						Serial.print(state.lValue[i]);
						Serial.print(", ");
					}
					Serial.println();
					state.calibrationStep = eFinished;
					state.maxValue = (state.rising? value:0);
					state.minValue = (state.rising? 1024 : value);
					state.lastSector = (state.rising ? 0: 5); //set the sector we are in at end of calibration
				}
				else
					state.calibrationStep = eStart;		//start calibration process again!
				litresReturn = 12;		//Somewhere between 10 and 15 litres should have passed during the calibration process
				break;
			}
		}
		Serial.print((state.rising ? "+" : "-"));
		Serial.print(",");
		state.lastValue = value;
	}
	else  //monitoring process
	{
		int lThisSector = state.lastSector;

		//iterate the 9 sectors past the last reported sector. We don't iterate the 10th sector as we want to avoid a noisy signal moving us 10 sectors ahead
		//Find out how far we have moved through the cycle
		for (int i = state.lastSector; i < 9 + state.lastSector; i++)
		{
			int sector = i % 10;
			if (sector == 0 )
			{
				if (value <= state.lValue[0])
				{
					lThisSector = sector;
					break;
				}
			}
			else if ( sector == 5)
			{
				if (value >= state.lValue[4])
				{
					lThisSector = sector;
					break;
				}
			}
			else if (sector > 0 && sector < 5)
			{
				if (value > state.lValue[sector-1] && value <= state.lValue[sector])
				{
					lThisSector = sector;
					break;
				}
			}
			else if (sector > 5 && sector < 10)
			{
				if (value <= state.lValue[sector-1] && value >= state.lValue[sector])
				{
					lThisSector = sector;
					break;
				}
			}
		}

		if (lThisSector < state.lastSector)
		{
			//passed end of sectors (full 360 degree)
			litresReturn = 10 + lThisSector - state.lastSector;
		}
		else
		{
			litresReturn = lThisSector - state.lastSector;
		}

		if (litresReturn)
		{
			Serial.print(state.lastSector);
			Serial.print(",");
			Serial.print(lThisSector);
			Serial.print(",");
		}

		state.lastSector = lThisSector;
	}

	if (state.calibrationStep != eFinished || litresReturn)
	{
		Serial.print(value);
		Serial.print(",");
		Serial.println(litresReturn);
	}

	return litresReturn;
}


//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup()
{
	Serial.begin(9600);

	Serial.println(F("Water sensor start - Hall effect on A0"));

	pinMode(GREEN_LED, OUTPUT);
	digitalWrite(GREEN_LED, HIGH);		//LED has inverted logic. LOW is on, HIGH is off!


	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(WATERLEVEL_NODE);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	Serial.print("RF69 initialise node: ");
	Serial.print(WATERLEVEL_NODE);
	Serial.println(" Freq: 915MHz");


	//initialise the EEPROMSettings for relay and node number
	EEPROMSettings eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);

	g_waterPayload.subnode = eepromSettings.subnode;

	//water flow rate setup
	//writeEEPROM(1, 0);					//reset the flash
	//writeEEPROM(0, 1540850);				
	//writeEEPROM(1, 988990);

	g_waterPayload.numSensors = 2;
	g_waterPayload.flowCount[0] = readEEPROM(0); 
	g_waterPayload.flowCount[1] = readEEPROM(1);
	g_flowCount =  g_waterPayload.flowCount[1] * PulsePerDeciLitre[1];

	Serial.print("Flow count: "); Serial.print(g_waterPayload.flowCount[0]); Serial.print(","); Serial.println(g_waterPayload.flowCount[1]);

	//Hall effect sensor AH3503
	pinMode(HALL_EFFECT_PIN, INPUT);

	g_hallEffectState.calibrationStep = eInit;
	g_hallEffectState.lastValue = analogRead(HALL_EFFECT_PIN);

	pinMode(FLOW_INTERRUPT_PIN, INPUT_PULLUP);
	attachPinChangeInterrupt(FLOW_INTERRUPT_PIN, interruptHandlerWaterFlow, CHANGE);
	//attachInterrupt(digitalPinToInterrupt(FLOW_INTERRUPT_PIN), interruptHandlerWaterFlow, CHANGE);

	EmonSerial::PrintWaterPayload(NULL);

	delay(100);
	
	digitalWrite(GREEN_LED, LOW);		//LED has inverted logic. LOW is on, HIGH is off!
}


long readVcc()
{
	//voltage divider is 1M and 1M. Jeenode reference voltage is 3.3v. AD range is 1024
	//voltage divider current draw is 29 uA
	float measuredvbat = analogRead(VOLTAGE_MEASURE_PIN);
	measuredvbat = (measuredvbat/1024.0 * 3.3) * (1000000.0+1000000.0)/1000000.0;
	return (measuredvbat*1000);//sent in mV
}



//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	if (g_hallEffectState.calibrationStep != eFinished)
	{
		digitalWrite(GREEN_LED, HIGH);
	}

	int litres = ServiceHallEffectSensor(g_hallEffectState);

	uint8_t oldSREG = SREG;			// save interrupt register
	cli();											// prevent interrupts while accessing the count	
	unsigned long boreFlowCount = g_flowCount;
	SREG = oldSREG;							// restore interrupts

	bool activity = (litres != 0) || g_waterPayload.flowCount[1] != (unsigned long)((double)boreFlowCount / PulsePerDeciLitre[1]);

	g_waterPayload.flowCount[0] += (unsigned long) ((double)litres/ PulsePerDeciLitre[0]);
	g_waterPayload.flowCount[1] = (unsigned long)((double)boreFlowCount/ PulsePerDeciLitre[1]);
	g_waterPayload.supplyV = readVcc();


	if(activity)
	{
		digitalWrite(GREEN_LED, HIGH);
		writeEEPROM(0, g_waterPayload.flowCount[0]);
		writeEEPROM(1, g_waterPayload.flowCount[1]);
	}

	digitalWrite(GREEN_LED, LOW);

	//don't transmit while calibrating
	if (g_hallEffectState.calibrationStep == eFinished)
	{
		g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
		PayloadWater packed;
		int len = EmonSerial::PackWaterPayload(&g_waterPayload, (byte*) &packed);
		g_rf69.send((const uint8_t*) &packed, len);
		if( g_rf69.waitPacketSent() )
		{
			EmonSerial::PrintWaterPayload(&g_waterPayload);
		}
		else
		{
			Serial.println(F("No packet sent"));
		}
		g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
	}

	
	//see http://www.gammon.com.au/forum/?id=11428
	while (!(UCSR0A & (1 << UDRE0)))  // Wait for empty transmit buffer
		UCSR0A |= 1 << TXC0;  // mark transmission not complete
	while (!(UCSR0A & (1 << TXC0)));   // Wait for the transmission to complete


	byte wakeNormally = 1;		//1 if woken by an interrupt rather than the sleep whatchdog timer
	if (g_hallEffectState.calibrationStep != eFinished)
	{
		wakeNormally = Sleepy::loseSomeTime(100);
	}
	else if (activity || g_lastActivity)
	{
		wakeNormally = Sleepy::loseSomeTime(2000);
	}
	else
	{
		wakeNormally = Sleepy::loseSomeTime(10000);		//10 seconds. If water flows faster than 54l/min then we have a problem! 
	}
	if (!wakeNormally)
	{
		delay(2000);		//teh bore sensor is interrupting. Just wait out 2 seconds of normal processor operation rather than mcu sleep
	}
	g_lastActivity = activity;
}
