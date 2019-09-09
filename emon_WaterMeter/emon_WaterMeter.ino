//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------

#define RF69_COMPAT 0

#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <eeprom.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>

#define GREEN_LED 9			// Green LED on emonTx
bool g_toggleLED = false;
bool g_lastActivity = false;

#define EEPROM_BASE 0x10	//where the water count is stored

#define TIMEOUT_PERIOD 2000		//10 seconds in ms. don't report litres/min if no tick recieved in this period
#define PULSES_PER_LITRE  1000
#define HALL_PEAK_THRESHOLD 3	//the minimum change in reading required to signal a change from rising to falling

enum calibrationStep { eStart, eWaitingForPeak, eFirstPass, eSecondPass, eCalculate, eFinished };

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
volatile unsigned long	g_lastTick = 0; 		//millis() value at last pulse
volatile unsigned long	g_period = 0;				//ms between last two pulses

RF12Init rf12Init = { WATERLEVEL_NODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP, RF69_COMPAT };

PayloadWater g_waterPayload;

ISR(WDT_vect) { Sleepy::watchdogEvent(); }


unsigned long readEEPROM(int offset)
{
	unsigned long value = 0;
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(unsigned long); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_BASE + offset + l);
	}

	return value;
}

void writeEEPROM(int offset, unsigned long value)
{
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(unsigned long); l++)
	{
		EEPROM.write(EEPROM_BASE + offset + l, *(pc + l));
	}
}


void interruptHandlerWaterFlow()
{
	digitalWrite(GREEN_LED, g_toggleLED?HIGH:LOW);		//LED has inverted logic. LOW is on, HIGH is off!
	g_toggleLED = !g_toggleLED;

	g_flowCount++;								//Update number of pulses, 1 pulse = 1 watt
	unsigned long tick = millis();
	if (tick < g_lastTick)
		g_period = tick + (g_lastTick - 0xFFFFFFFF);	//rollover occured
	else
		g_period = tick - g_lastTick;
	g_lastTick = tick;
}

unsigned short FlowRateInLitresPerMinute()
{
	unsigned long lastPeriod;
	unsigned long thisPeriod;
	unsigned long lastTick;
	unsigned long tick = millis();
	double periodfor1LitrePerMinute;	//ms petween puses that represent 1 litre/minute
	double litresPerMinute;

	uint8_t oldSREG = SREG;			// save interrupt register
	cli();							// prevent interrupts while accessing the count	

	lastPeriod = g_period;
	lastTick = g_lastTick;

	SREG = oldSREG;					// restore interrupts

	if (tick < lastTick)
		thisPeriod = tick + (lastTick - 0xFFFFFFFF);	//rollover occured
	else
		thisPeriod = tick - lastTick;

	periodfor1LitrePerMinute = 1000.0 * 60.0 / PULSES_PER_LITRE;

	if (thisPeriod < lastPeriod)
		litresPerMinute = periodfor1LitrePerMinute / lastPeriod;		//report the watts for the last tick period
	else if (thisPeriod >= TIMEOUT_PERIOD)
		litresPerMinute = 0;									// report 0 instead of tappering off slowly towards 0 over time.
	else
		litresPerMinute = periodfor1LitrePerMinute / thisPeriod;		//report the litres as if the tick occured now 


	return (unsigned short)litresPerMinute;
}


int ServiceHallEffectSensor(struct HallEffectStateType &state)
{
	int litresReturn = 0;
	int value = analogRead(A0);

	//Calibration process
	if (state.calibrationStep != eFinished)
	{
		Serial.print("Calibrating step(");
		Serial.print(state.calibrationStep);
		Serial.print(") ");
		Serial.print((state.rising?"^":"|"));

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
		Serial.print((state.rising ? "^" : "|"));
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

		//work out if we need to recalibrate the sensor. If the min or max is more than 10% of range outside of last calibration values
		//if( litresReturn)
		//	Serial.print((state.rising ? "^" : "|"));
		//if (state.rising)
		//{
		//	//update rising/falling state
		//	if (value >= state.maxValue)
		//	{
		//		state.maxValue = value;
		//	}
		//	else if (fabs(value - state.maxValue) > HALL_PEAK_THRESHOLD)		//changing from rising to falling
		//	{
		//		if (fabs(state.maxValue - state.maxCalibration) > (state.maxCalibration - state.minCalibration) /10)// no longer claibrated
		//		{
		//			state.calibrationStep = eStart;
		//		}
		//		else
		//		{
		//			state.rising = false;
		//			state.maxValue = 0; //reset
		//		}
		//	}
		//}
		//else //falling
		//{
		//	//update rising/falling state
		//	if (value <= state.minValue)
		//	{
		//		state.minValue = value;
		//	}
		//	else if (fabs(value - state.minValue) > HALL_PEAK_THRESHOLD)		//changing from falling to rising
		//	{
		//		if (fabs(state.minValue - state.minCalibration) > (state.maxCalibration - state.minCalibration) / 10)// no longer claibrated
		//		{
		//			state.calibrationStep = eStart;
		//		}
		//		else
		//		{
		//			state.rising = true;
		//			state.minValue = 1024; //reset
		//		}
		//	}
		//}
		//if (litresReturn)
		//	Serial.print((state.rising ? "^" : "|"));
	}

	if (state.calibrationStep != eFinished || litresReturn)
	{
		Serial.print(value);
		Serial.print(": ");
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


	Serial.println("rf12_initialize");
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);


	//initialise the EEPROMSettings for relay and node number
	EEPROMSettings eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);

	g_waterPayload.subnode = eepromSettings.subnode;

	//water flow rate setup
	//writeEEPROM(0, 0);					//reset the flash
	g_flowCount = readEEPROM(0);	//read last reading from flash

	g_period = millis() - TIMEOUT_PERIOD;
	g_waterPayload.flowRate = 0;
	g_waterPayload.flowCount = g_flowCount;


	//Hall effect sensor AH3503
	pinMode(A0, INPUT);
	g_hallEffectState.calibrationStep = eStart;
	g_hallEffectState.lastValue = analogRead(A0);

//	pinMode(3, INPUT_PULLUP);
//	attachInterrupt(digitalPinToInterrupt(3), interruptHandlerWaterFlow, CHANGE);

	delay(100);
	
	digitalWrite(GREEN_LED, LOW);		//LED has inverted logic. LOW is on, HIGH is off!
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
	
	g_flowCount += litres;

	bool activity = ( litres != 0 );

	if(activity)
	{
		digitalWrite(GREEN_LED, HIGH);
		writeEEPROM(0, g_flowCount);
	}

	g_waterPayload.flowCount = g_flowCount;
	g_waterPayload.flowRate = 0;// FlowRateInLitresPerMinute();
	g_waterPayload.waterHeight = 0;

	//don't transmit while calibrating
	if (g_hallEffectState.calibrationStep == eFinished)
	{
		rf12_sleep(RF12_WAKEUP);

		int wait = 1000;
		while (!rf12_canSend() && wait--)
			rf12_recvDone();
		if (wait)
		{
			rf12_sendStart(0, &g_waterPayload, sizeof g_waterPayload);
			rf12_sendWait(0);
			EmonSerial::PrintWaterPayload(&g_waterPayload);
		}
		else
		{
			Serial.println(F("RF12 waiting. No packet sent"));
		}
		rf12_sleep(RF12_SLEEP);
	}

	digitalWrite(GREEN_LED, LOW);
	
	//see http://www.gammon.com.au/forum/?id=11428
	while (!(UCSR0A & (1 << UDRE0)))  // Wait for empty transmit buffer
		UCSR0A |= 1 << TXC0;  // mark transmission not complete
	while (!(UCSR0A & (1 << TXC0)));   // Wait for the transmission to complete



	if (g_hallEffectState.calibrationStep != eFinished)
		Sleepy::loseSomeTime(100);
	else if (activity || g_lastActivity)
	{
		Sleepy::loseSomeTime(2000);
	}
	else
	{
		Sleepy::loseSomeTime(10000);		//10 seconds. If water flows faster than 54l/min then we have a problem! 
	}

	g_lastActivity = activity;
}
