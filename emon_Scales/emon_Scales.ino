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


//#define SCALE_FACTOR  19.55f    //calibration_factor = 19.55 for 4 load-cell 200kg rating

Hx711 g_scale(A0, A1); 


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


long readVcc_WhisperNode()
{
	//see https://bitbucket.org/talk2/whisper-node-avr/src/master/#markdown-header-buttons-and-leds
	const uint8_t SAMPLES = 5;
	const uint8_t MAX_VOLTAGE = 7282;
	const uint8_t CONTROL_PIN = A0;
	const uint8_t BAT_VOLTAGE_PIN = A6;

	analogReference(INTERNAL);

	// Turn on the MOSFET via control pin
	pinMode(CONTROL_PIN, OUTPUT);
	digitalWrite(CONTROL_PIN, HIGH);

	// Read pin a couple of times and keep adding up.
	uint16_t readings = 0;
	for (uint8_t i = 0; i < SAMPLES; i++)
	{
		readings += analogRead(BAT_VOLTAGE_PIN);
	}

	// Turn off the MOSFET
	digitalWrite(CONTROL_PIN, LOW);

	return (MAX_VOLTAGE * (readings / SAMPLES) / 1023);
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
	if (g_scalePayload.subnode == 0)
		g_scale.setScale(19.55f);		//calibration_factor = 19.55 for 4 load-cell 200kg rating
	else if(g_scalePayload.subnode == 1)
		g_scale.setScale(415.43);		//calibration_factor = 415.43 for 5 kg load-cell rating


	g_lastScaleValue = g_scale.getValue();
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
	if (abs(g_scale.getValue() - g_lastScaleValue) > 1000)
	{
		g_secondsSinceActivity = 1;
		g_lastScaleValue = g_scale.getValue();
//		Serial.println(g_lastScaleValue);
	}
	else
	{
		g_secondsSinceActivity++;
	}

	//Serial.print("g_secondsSinceActivity ="); 
	//Serial.print(g_secondsSinceActivity);
	//Serial.print(", g_lastScaleValue =");
	//Serial.print(g_lastScaleValue);
	//Serial.print("Scale reading: ");
	//Serial.println(scale.getGram());
	//delay(100);

	if((g_secondsSinceActivity > 30 && g_secondsSinceActivity <=35) || g_secondsSinceActivity%600 == 0)	//transmit for the 5 seconds, 30 seconds after activity finishes. Then every 10 minutes.
	{
		g_scalePayload.grams = (long)g_scale.getGram();
		if (g_scalePayload.subnode == 0)
			g_scalePayload.supplyV = readVcc();
		else if (g_scalePayload.subnode == 1)
			g_scalePayload.supplyV = readVcc(); // readVcc_WhisperNode();

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
	
	Sleepy::loseSomeTime(1000); 
}
