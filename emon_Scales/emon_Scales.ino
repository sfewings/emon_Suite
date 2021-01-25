//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------
#undef USE_JEELIB

#include <JeeLib.h>			// needed for Sleepy, ports and RFM12 - used for RFM12B wireless

#ifdef USE_JEELIB
	#define RF69_COMPAT 1

	RF12Init rf12Init = { SCALE_NODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP };
#else
	#include <SPI.h>
	#include <RH_RF69.h>
	// Singleton instance of the radio driver
	RH_RF69 g_rf69;
#endif

#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <hx711.h>



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
	const uint32_t MAX_VOLTAGE = 7282;
	const uint8_t CONTROL_PIN = A0;
	const uint8_t BAT_VOLTAGE_PIN = A6;

	analogReference(INTERNAL);

	// Turn on the MOSFET via control pin
	pinMode(CONTROL_PIN, OUTPUT);
	digitalWrite(CONTROL_PIN, HIGH);

	// Read pin a couple of times and keep adding up.
	uint32_t readings = 0;
	for (uint8_t i = 0; i < SAMPLES; i++)
	{
		readings += analogRead(BAT_VOLTAGE_PIN);
	}

	// Turn off the MOSFET
	digitalWrite(CONTROL_PIN, LOW);

	return (MAX_VOLTAGE * (readings / SAMPLES) / 1023);
}

void SerialOut()
{
	Serial.print("g_secondsSinceActivity =");
	Serial.print(g_secondsSinceActivity);
	Serial.print(", g_lastScaleValue =");
	Serial.print(g_lastScaleValue);
	Serial.print("Scale reading: ");
	Serial.print(g_scale.getGram());
	Serial.println("g");
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

	Serial.print("Scales calibrated, ");
	SerialOut();
#ifdef USE_JEELIB	
	Serial.print("rf12_initialize:");
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);
#else
	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(SCALE_NODE);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	Serial.print("RF69 initialise node: ");
	Serial.print(SCALE_NODE);
	Serial.println(" Freq: 915MHz");
#endif

	EmonSerial::PrintScalePayload(NULL);

	delay(100);
}

//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	//Serial.print("Whisper voltage ");
	//Serial.println(readVcc_WhisperNode());
	//Serial.print("MCU voltage     ");
	//Serial.println(readVcc());

	if (abs(g_scale.getValue() - g_lastScaleValue) > 1000)
	{
		g_secondsSinceActivity = 1;
		g_lastScaleValue = g_scale.getValue();
		Serial.print("g_lastScaleValue =");
		Serial.println(g_lastScaleValue);

	}
	else
	{
		g_secondsSinceActivity++;
	}

	//SerialOut();

	if((g_secondsSinceActivity > 30 && g_secondsSinceActivity <=35) || g_secondsSinceActivity%600 == 0)	//transmit for the 5 seconds, 30 seconds after activity finishes. Then every 10 minutes.
	{
		g_scalePayload.grams = (long)g_scale.getGram();
		if (g_scalePayload.subnode == 0)
			g_scalePayload.supplyV = readVcc();
		else if (g_scalePayload.subnode == 1)
			g_scalePayload.supplyV = readVcc_WhisperNode();

#ifdef USE_JEELIB
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
#else
		g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
		g_rf69.send((const uint8_t*) &g_scalePayload, sizeof(g_scalePayload));
		if( g_rf69.waitPacketSent() )
		{
			EmonSerial::PrintScalePayload(&g_scalePayload);
		}
		else
		{
			Serial.println(F("No packet sent"));
		}
		g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
#endif

	}

	//let serial buffer empty
	//see http://www.gammon.com.au/forum/?id=11428
	while (!(UCSR0A & (1 << UDRE0)))  // Wait for empty transmit buffer
		UCSR0A |= 1 << TXC0;  // mark transmission not complete
	while (!(UCSR0A & (1 << TXC0)));   // Wait for the transmission to complete
	
	Sleepy::loseSomeTime(1000); 
}
