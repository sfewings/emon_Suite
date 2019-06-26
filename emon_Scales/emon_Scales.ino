//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------

#define RF69_COMPAT 1

#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <eeprom.h>
#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <hx711.h>


RF12Init rf12Init = { SCALE_NODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };

PayloadScale g_scalePayload;
long g_lastScaleValue;
long g_secondsSinceActivity;		//Increment for each time the weight is transmitted. When activity is encountered, this is reset to 0


#define SCALE_FACTOR  19.55f

Hx711 scale(A0, A1, SCALE_FACTOR); //calibration_factor = 19.55 for 4 load-cell 200kg rating


//--------------------------------------------------------------------------------------------------
// Sleepy interrupt service routine callback
//--------------------------------------------------------------------------------------------------
ISR(WDT_vect) { Sleepy::watchdogEvent(); }


//--------------------------------------------------------------------------------------------------
// Read current battery voltage - not main supplyV!
//--------------------------------------------------------------------------------------------------
long readVcc()
{
	long result;
	// Read 1.1V reference against AVcc
	ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
	delay(2); // Wait for Vref to settle
	ADCSRA |= _BV(ADSC); // Convert
	while (bit_is_set(ADCSRA, ADSC));
	result = ADCL;
	result |= ADCH << 8;
	result = 1126400L / result; // Back-calculate AVcc in mV
	return result;
}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup()
{
	Serial.begin(9600);

	Serial.println(F("Scale sensor"));
		
	//initialise the EEPROMSettings for relay and node number
	EEPROMSettings  eepromSettings;
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	
	g_scalePayload.subnode = eepromSettings.subnode;
	
	g_lastScaleValue = scale.getValue();
	g_secondsSinceActivity = 0;

	Serial.print("rf12_initialize:");
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);
	EmonSerial::PrintScalePayload(NULL);

	delay(100);
}

//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	if (abs(scale.getValue() - g_lastScaleValue) > 1000)
	{
		g_secondsSinceActivity = 1;
		g_lastScaleValue = scale.getValue();
	}
	else
	{
		g_secondsSinceActivity++;
	}

	//Serial.print("g_secondsSinceActivity ="); 
	//Serial.print(g_secondsSinceActivity);
	//Serial.print(", g_lastScaleValue =");
	//Serial.print(g_lastScaleValue);
	//Serial.print(", Scale reading: ");
	//Serial.println(scale.getGram());
	//delay(100);

	if((g_secondsSinceActivity > 15 && g_secondsSinceActivity <=20) || g_secondsSinceActivity%600 == 0)	//transmit for the 5 seconds, 15 seconds after activity finishes. Then every 10 minutes.
	{
		g_scalePayload.grams = (long)scale.getGram();
		g_scalePayload.supplyV = readVcc();

		rf12_sleep(RF12_WAKEUP);
		int wait = 1000;
		while (!rf12_canSend() && wait--)
			rf12_recvDone();
		if (wait)
		{
			rf12_sendStart(0, &g_scalePayload, sizeof g_scalePayload);
			rf12_sendWait(0);
			EmonSerial::PrintScalePayload(&g_scalePayload);
		}
		else
		{
			Serial.println(F("RF12 waiting. No packet sent"));
		}
		rf12_sleep(RF12_SLEEP);


		delay(50); //let serial buffer empty
	}
	
	Sleepy::loseSomeTime(1000); // go to sleep for longer if nothing is happening
}
