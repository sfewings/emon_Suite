//------------------------------------------------------------------------------------------------------------------------------------------------
//  emon Terra load cell
//	Receives serial data from the load cell output and transmits when there is a change, or every fixed interval
//-------------------------------------------------------------------------------------------------------------------------------------------------

#include <SPI.h>
#include <RH_RF69.h>
#include <SoftwareSerial.h>

#include <EmonShared.h>
#include <EmonEEPROM.h>

#include <avr/wdt.h>    //watchdog timer

#define VOLTAGE_MEASURE_PIN 		A4
#define SERIAL_RX 					4
#define SERIAL_TX			 		3	//unused
#define LED_PIN						9

//#define HOUSE_BANNER
#define BOAT_BANNER
#ifdef HOUSE_BANNER
    #define NETWORK_FREQUENCY 915.0
#elif defined(BOAT_BANNER)
    #define NETWORK_FREQUENCY 914.0
#endif


RH_RF69 g_rf69;
SoftwareSerial g_sensorSerial(SERIAL_RX, SERIAL_TX);

PayloadScale g_scalePayload;

long g_lastScaleValue;
unsigned long g_lastActivityMillis;


//--------------------------------------------------------------------------------------------------
// Read current battery voltage - not main supplyV!
//--------------------------------------------------------------------------------------------------
// long readVcc()
// {
// 	long result;
// 	// Read 1.1V reference against AVcc
// 	ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
// 	delay(2); // Wait for Vref to settle
// 	ADCSRA |= _BV(ADSC); // Convert
// 	while (bit_is_set(ADCSRA, ADSC));
// 	result = ADCL;
// 	result |= ADCH << 8;
// 	result = 1126400L / result; // Back-calculate AVcc in mV
// 	return result;
// }


void SerialOut(long reading)
{
	Serial.print("g_secondsSinceActivity=");
	Serial.print( (unsigned long) ((g_lastActivityMillis-millis())/1000) );
	Serial.print(", g_lastScaleValue=");
	Serial.print( g_lastActivityMillis-millis() );
	Serial.print(", g_lastScaleValue=");
	Serial.print(g_lastScaleValue/1000.0, 3);
	Serial.print(", Scale reading=");
	Serial.print( reading/1000.0,3);
	Serial.println();
}


bool readFromSerial(long& reading) 
{
	const uint16_t BUF_SIZE = 255;
	char buffer[BUF_SIZE];
	size_t pos = 0;

	memset(buffer,0,BUF_SIZE);

	int wait = 0;
	unsigned long start = millis();
	bool eol = false;
	while(millis() < start+1000 && !eol) ///wait for answer or timeout
	{
		while (g_sensorSerial.available() > 0 )   ///wait for answer or timeout
		{
			char c = g_sensorSerial.read();
			//Serial.print((byte)c,HEX);

			buffer[pos++] = c;
			if( pos == BUF_SIZE )
			{
				Serial.println(F("overflow"));
				return false;  //overflow
			}
			if( c == 0x0d )
			{
				pos--;
			}
			if( c == 0x0a )
			{
				pos--;
				eol = true; //end of line
//				Serial.println("eol");
			}
		}    
	}

	if( pos == 0 )
	{
		Serial.println("timeout");
		return false;
	}
	else
	{
		if( buffer[0] != '=')	// a full reading needs to start with an '=' char
		{
			return false;
		}
		Serial.print(buffer);
		float value = atof(buffer+1);	//Recived as '=-000.0'. Skip the '='
		reading = (long) (value*1000.0); //value in kg, reading in grams
	}

	return true;
}

void SendPayload()
{
	digitalWrite(LED_PIN, HIGH);
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
	digitalWrite(LED_PIN, LOW);
}

//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup()
{
	pinMode(LED_PIN, OUTPUT);
	digitalWrite(LED_PIN, HIGH);
	Serial.begin(9600);

	Serial.println(F("Scale sensor"));
		
	//initialise the EEPROMSettings for relay and node number
	// EEPROMSettings  eepromSettings;
	// EmonEEPROM::ReadEEPROMSettings(eepromSettings);
	// EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
	//g_scalePayload.subnode = eepromSettings.subnode;
	g_scalePayload.subnode = 1;
	g_scalePayload.grams = 0;
	g_scalePayload.supplyV = 0;
	g_scalePayload.relay = 0;

	g_lastScaleValue = 0;
	g_lastActivityMillis = millis();

	g_sensorSerial.begin(9600);

	Serial.print("Scales started, ");
	SerialOut(0);

	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(SCALE_NODE);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

	Serial.print("RF69 initialise node: ");
	Serial.print(SCALE_NODE);
	Serial.print(" Freq: ");Serial.print(NETWORK_FREQUENCY,1); Serial.println("MHz");

	EmonSerial::PrintScalePayload(NULL);


	SendPayload();

	delay(100);

	digitalWrite(LED_PIN, LOW);

  	wdt_enable(WDTO_2S);
}

//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop()
{
	wdt_reset();

	long reading;
	if( readFromSerial(reading) && ( reading != g_lastScaleValue) )
	{
		SerialOut(reading);
		g_lastActivityMillis = millis();
		g_lastScaleValue = reading;
	}

	if((g_lastActivityMillis - millis() < 1000 || ((g_lastActivityMillis - millis())/1000)%60==0) )	//for 2 seconds after activity, then every minute
	{
		digitalWrite(LED_PIN, HIGH);
		
		g_scalePayload.grams = g_lastScaleValue;
		//g_scalePayload.supplyV = readVcc();

		//add the current supply voltage at the end
		//voltage divider is 1M and 1M. Jeenode reference voltage is 3.3v. AD range is 1024
		//voltage divider current draw is 29 uA
		float measuredvbat = analogRead(VOLTAGE_MEASURE_PIN);
		measuredvbat = (measuredvbat/1024.0 * 3.3) * (1000000.0+1000000.0)/1000000.0;
		g_scalePayload.supplyV =(unsigned long) (measuredvbat*1000);//sent in mV

		SendPayload();
		digitalWrite(LED_PIN, LOW);
	}


	//flash the LED in 100ms on/off when power is below 3400mA. This gives about 
	if( g_scalePayload.supplyV <= 3400 )
	{
		digitalWrite(LED_PIN, (millis()/100) %2 );
	}	

	//let serial buffer empty
	//see http://www.gammon.com.au/forum/?id=11428
	// while (!(UCSR0A & (1 << UDRE0)))  // Wait for empty transmit buffer
	// 	UCSR0A |= 1 << TXC0;  // mark transmission not complete
	// while (!(UCSR0A & (1 << TXC0)));   // Wait for the transmission to complete
}
