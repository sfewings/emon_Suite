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

EEPROMSettings  eepromSettings;
PayloadScale scalePayload;
long lastScaleValue;
long	secondsSinceActivity;		//Increment for each time the weight is transmitted. When activity is encountered, this is reset to 0


ISR(WDT_vect) { Sleepy::watchdogEvent(); }
#define SCALE_FACTOR  19.55f

Hx711 scale(A0, A1, SCALE_FACTOR); //calibration_factor = 19550000; // for 4 load-cell 200kg rating


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

	Serial.println(F("Scale sensor start"));

	//initialise the EEPROMSettings for relay and node number
	EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	if (eepromSettings.relayNumber)
		scalePayload.relay = 1 << (eepromSettings.relayNumber - 1);
	else
		scalePayload.relay = 0;

	scalePayload.grams = (long)scale.getGram();
	lastScaleValue = scale.getValue();
	secondsSinceActivity = 0;

	Serial.println("rf12_initialize");
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);
	
	delay(500);
}

//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	if (abs(scale.getValue() - lastScaleValue) > 1000)
	{
		scalePayload.grams = (long)scale.getGram();
		secondsSinceActivity = 0;
		lastScaleValue = scale.getValue();
	}
	else
	{
		secondsSinceActivity++;
	}

	if(secondsSinceActivity < 5 || secondsSinceActivity%600 == 0)	//transmit for the 5 seconds after activity and then every 10 minutes
	{
		rf12_sleep(RF12_WAKEUP);

		scalePayload.supplyV = readVcc();

		int wait = 1000;
		while (!rf12_canSend() && wait--)
			rf12_recvDone();
		if (wait)
		{
			rf12_sendStart(0, &scalePayload, sizeof scalePayload);
			rf12_sendWait(0);
			EmonSerial::PrintScalePayload(&scalePayload);
		}
		else
		{
			Serial.println(F("RF12 waiting. No packet sent"));
		}
		rf12_sleep(RF12_SLEEP);


		delay(100); //let serial buffer empty
	}
	
	Sleepy::loseSomeTime(1000); // go to sleep for longer if nothing is happening
}
