//------------------------------------------------------------------------------------------------------------------------------------------------
// emon WaterLevel
//-------------------------------------------------------------------------------------------------------------------------------------------------

#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <PortsLCD.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <DS1603L.h>
#include <EmonShared.h>
#include <SoftwareSerial.h>

SoftwareSerial sensorSerial(A1, A0);	//A1=rx, A0=tx

// If your sensor is connected to Serial, Serial1, Serial2, AltSoftSerial, etc. pass that object to the sensor constructor.
DS1603L waterHeightSensor(sensorSerial);

LiquidCrystal lcd(A2,4, 8,7,6,5);


RF12Init rf12Init = { WATERLEVEL_NODE, RF12_915MHZ, 210 };


PayloadWater payloadWater;

//---------------------------------------------------------------------------------------------------
// Dallas temperature sensor	on pin 5, Jeenode port 2
//---------------------------------------------------------------------------------------------------
OneWire oneWire(A4);
DallasTemperature temperatureSensor(&oneWire);
int numberOfTemperatureSensors = 0;
bool toggle = true;

static void lcdSerialReading(uint32_t reading)
{
	lcd.setCursor(0, 1);
	for (int i = 3; i >= 0; i--)
	{
		lcd.print((reading >> (8 * i)) & 0xFF);
		if (i)
			lcd.print(",");
	}
}

String TemperatureString(String& str, int temperature )
{
	int t = temperature;
	if( t < 0 )
	{
		str = "-";
		t *= -1;
		str += t/100;
	}
	else
		str = String(t/100);
	str +=".";
 
	str += (t/10)%10;

	return str;
}


void PrintAddress(uint8_t deviceAddress[8])
{
	Serial.print("{ ");
	for (uint8_t i = 0; i < 8; i++)
	{
		// zero pad the address if necessary
		Serial.print("0x");
		if (deviceAddress[i] < 16) Serial.print("0");
		Serial.print(deviceAddress[i], HEX);
		if (i < 7) Serial.print(", ");
	}
	Serial.print(" }");
}


//--------------------------------------------------------------------------------------------
// Setup
//--------------------------------------------------------------------------------------------
void setup () 
{
	Serial.begin(9600);
	
	lcd.begin(16, 2);
	lcd.setCursor(0, 0);

	lcd.print(F("Water sensor"));
	lcd.setCursor(0, 1);
	lcd.print(F("Monitor 2.0"));

	Serial.println(F("Water sensor start"));

	Serial.println("rf12_initialize");
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group);
	EmonSerial::PrintRF12Init(rf12Init);


	//Temperature sensor setup
	temperatureSensor.begin();
	numberOfTemperatureSensors = temperatureSensor.getDeviceCount();
	if (numberOfTemperatureSensors)
	{
		Serial.print(F("Temperature sensors "));

		for (int i = 0; i< numberOfTemperatureSensors; i++)
		{
			uint8_t tmp_address[8];
			temperatureSensor.getAddress(tmp_address, i);
			Serial.print(F("Sensor address "));
			Serial.print(i + 1);
			Serial.print(F(": "));
			PrintAddress(tmp_address);
			Serial.println();
		}
	}

	sensorSerial.begin(9600);     // Sensor transmits its data at 9600 bps.
	waterHeightSensor.begin();               // Initialise the sensor library.

	//let the startup LCD display for a while!
	delay(2000);
	lcd.clear();
}

//--------------------------------------------------------------------------------------------
// Loop
//--------------------------------------------------------------------------------------------
void loop () 
{
	char s[16];


		//toggle a "*" every read
		lcd.setCursor(15, 1);
		lcd.print((toggle = !toggle)? "*": " ");

		if (numberOfTemperatureSensors)
		{
			temperatureSensor.requestTemperatures();
			float t = temperatureSensor.getTempCByIndex(0);
			sprintf(s,  "T=%d.%dc", (int)t, ((int)(t*10)%10));
			lcd.setCursor(10, 1);
			lcd.print(s);
			Serial.println(s);
		}

		payloadWater.waterHeight = waterHeightSensor.readSensor();
		payloadWater.sensorReading = waterHeightSensor.SerialData();

		switch (waterHeightSensor.getStatus())
		{
		case DS1603L_NO_SENSOR_DETECTED:                // No sensor detected: no valid transmission received for >10 seconds.
			strncpy(s,"No sensor",16);
			break;

		case DS1603L_READING_CHECKSUM_FAIL:             // Checksum of the latest transmission failed.
			snprintf(s, 16, "CRC %d mm       ", payloadWater.waterHeight);
			break;

		case DS1603L_READING_SUCCESS:                   // Latest reading was valid and received successfully.
			snprintf(s, 16, "Water %d mm     ", payloadWater.waterHeight);
			break;
		}
		
		lcd.setCursor(0, 0);
		lcd.print(s);
		lcd.setCursor(0, 1);
		lcdSerialReading(payloadWater.sensorReading);

		Serial.println(s);
		waterHeightSensor.printReading();
		
		rf12_sleep(RF12_WAKEUP);
		while (!rf12_canSend())
			rf12_recvDone();
		rf12_sendStart(0, &payloadWater, sizeof payloadWater);
		rf12_sendWait(0);
		rf12_sleep(RF12_SLEEP);

		//Sleepy::loseSomeTime(2000); // go to sleep for n
		delay(2000);
}
