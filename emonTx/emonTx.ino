//--------------------------------------------------------------------------------------
//Interrupt pulse counting and one CT sensor 
//not low power - run emonTx from 5V USB adapter 

//Based on JeeLabs RF12 library http://jeelabs.org/2009/02/10/rfm12b-library-for-arduino/

// By Glyn Hudson and Trystan Lea: 21/9/11
// openenergymonitor.org
// GNU GPL V3

//	Modified by S Fewings.
//		1. Use power calculations from home power monitor project
//		2. Add temperature reading
//		3. Add rain gauge pulse counting. Added to Arduino IO pin 5, Jeenode Port 2. Une PinChangeInt library to add additional interrupt to Atmega328
//		4. Report line supply voltage. Only useful when powering by battery
//

// pulse input on pulse channel (top right jack)
// CT input on CT channel 2 (middle jack on RHS)

//--------------------------------------------------------------------------------------

//JeeLabs libraries 
#include <Ports.h>
#include <RF12.h>
#include <avr/eeprom.h>
#include <util/crc16.h>		//cyclic redundancy check
#include <time.h>					//required for EmonShared.h
#include <EmonShared.h>

//---------------------------------------------------------------------------------------------------
// Serial print settings - disable all serial prints if SERIAL 0 - increases long term stability 
//---------------------------------------------------------------------------------------------------
#define ENABLE_SERIAL 1
//---------------------------------------------------------------------------------------------------

//---------------------------------------------------------------------------------------------------
// RF12 settings 
//---------------------------------------------------------------------------------------------------
// 9Sep18 EMON_NODE and EMON_TEMP_NODE both transmit the same details fromthe same device type
// EMON_NODE is used for Power and Solar. EMON_TEMP_NODE is for water temperature only
RF12Init rf12Init = { EMON_NODE, RF12_915MHZ, 210 };
//RF12Init rf12Init = { EMON_TEMP_NODE, RF12_915MHZ, 210 };

//--------------------------------------------------------------------------------------------------
// CT energy monitor setup definitions 
//--------------------------------------------------------------------------------------------------
int CT_INPUT_PIN =			0;	//I/O analogue 3 = emonTx CT2 channel. Change to analogue 0 for emonTx CT1 chnnel	
int NUMBER_OF_SAMPLES =	 1480; //The period (one wavelength) of mains 50Hz is 20ms. Each samples was measured to take 0.188ms. This meas that 106.4 samples/wavelength are possible. 1480 samples takes 280.14ms which is 14 wavelengths. 
int RMS_VOLTAGE =			240;	//Assumed supply voltage (230V in UK).	Tolerance: +10%-6%
int CT_BURDEN_RESISTOR =	15;	//value in ohms of burden resistor R3 and R6
int CT_TURNS =				1500; //number of turns in CT sensor. 1500 is the vaue of the efergy CT 

//double CAL=(1.295000139 *1.6);			//*calibration coefficient* IMPORTANT - each monitor must be calibrated for maximum accuracy. See step 4 http://openenergymonitor.org/emon/node/58. Set to 1.295 for Seedstudio 100A current output CT (included in emonTx V2.0 kit)
double CAL = 5.014;		//10Sep18 For 28 Shann with new solar install
//--------------------------------------------------------------------------------------------------


//--------------------------------------------------------------------------------------------------
// LED Indicator	
//--------------------------------------------------------------------------------------------------
# define LEDpin 9			//hardwired on emonTx PCB

//--------------------------------------------------------------------------------------------------
//Temperature support - OneWire Dallas temperature sensor
//--------------------------------------------------------------------------------------------------
#include <OneWire.h>
#include <DallasTemperature.h>

#define ONE_WIRE_BUS 4													// Data wire is plugged into port 2 on the Arduino
OneWire oneWire(ONE_WIRE_BUS);											// Setup a oneWire instance to communicate with any OneWire devices (not just Maxim/Dallas temperature ICs)
DallasTemperature sensors(&oneWire);									// Pass our oneWire reference to Dallas Temperature.




PayloadEmon emonPayload;
//########################################################################################################################



void setup()
{
	Serial.begin(9600);					//fast serial 
	pinMode(LEDpin, OUTPUT);
	digitalWrite(LEDpin, HIGH);	//turn on LED 

	delay(1000);
	
	Serial.println(F("Fewings emonTx. Based on openenergymonitor.org"));
	
	delay(10);	
	//-----------------------------------------
	// RFM12B Initialize
	//------------------------------------------
	rf12_initialize(rf12Init.node, rf12Init.freq, rf12Init.group,1600);	 //Initialize RFM12 with settings defined above, use pin 10 as SSelect
	EmonSerial::PrintRF12Init(rf12Init);
	//------------------------------------------
	
	delay(20);
	
	if (ENABLE_SERIAL==0) {
	Serial.println("serial disabled"); 
	Serial.end();
	}

	SetupPulseCount();


	//temperature
	sensors.begin();

	DeviceAddress tmp_address;
	int numberOfDevices = sensors.getDeviceCount();
	
	for(int i=0;i<numberOfDevices; i++)
	{
		sensors.getAddress(tmp_address, i);
		Serial.print(F("Temperature sensor address "));
		Serial.print(i+1);
		Serial.print(F(": "));
		printAddress(tmp_address);
		Serial.println();
	}

	// Initialise 
	emonPayload.pulse = 0;		
	emonPayload.ct1 = 0;
	emonPayload.supplyV = 0;
	emonPayload.temperature = 0;
	emonPayload.rainGauge = 0;

	EmonSerial::PrintEmonPayload(NULL);

	digitalWrite(LEDpin, LOW);				//turn off LED
}


void loop()
{	
	//--------------------------------------------------------------------------------------------------
	// 1. Read current supply voltage and get current CT energy monitoring reading 
	//--------------------------------------------------------------------------------------------------
	emonPayload.power = MeterCurrentWatts();
	emonPayload.pulse = MeterPulseLog();					//as well as sending power we also send pulse increments inorder to accuratly calculate kwhr
	emonPayload.supplyV = readVcc();					//read emonPayload supply voltage
	emonPayload.ct1 = int(emon(CT_INPUT_PIN, CAL, RMS_VOLTAGE, NUMBER_OF_SAMPLES, CT_BURDEN_RESISTOR, CT_TURNS, emonPayload.supplyV));
	emonPayload.rainGauge = MeterRainGauge();			//return the raingauge counts. 
	sensors.requestTemperatures();	
	emonPayload.temperature = sensors.getTempCByIndex(0) * 100;

	//--------------------------------------------------------------------------------------------------
	// 2. Send data via RF 
	//--------------------------------------------------------------------------------------------------
	while (!rf12_canSend())
	rf12_recvDone();
	rf12_sendStart(0, &emonPayload, sizeof emonPayload);
	//--------------------------------------------------------------------------------------------------	
	EmonSerial::PrintEmonPayload(&emonPayload);


	digitalWrite(LEDpin, HIGH);	 //flash LED - very quickly each time a pluse occus	
	delay(1);
	digitalWrite(LEDpin, LOW);	 //flash LED - very quickly each time a pluse occus	

	delay(1000);		//1s delay	
}



void printAddress(uint8_t deviceAddress[8])
{
	Serial.print("{ ");
	for (uint8_t i = 0; i < 8; i++)
	{
	// zero pad the address if necessary
	Serial.print("0x");
	if (deviceAddress[i] < 16) Serial.print("0");
	Serial.print(deviceAddress[i], HEX);
	if (i<7) Serial.print(", ");
	
	}
	Serial.print(" }");
}


//--------------------------------------------------------------------------------------------------
// Read current emonTx battery voltage - not main supplyV!
//--------------------------------------------------------------------------------------------------
long readVcc() {
	long result;
	// Read 1.1V reference against AVcc
	ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
	delay(2); // Wait for Vref to settle
	ADCSRA |= _BV(ADSC); // Convert
	while (bit_is_set(ADCSRA,ADSC));
	result = ADCL;
	result |= ADCH<<8;
	result = 1126400L / result; // Back-calculate AVcc in mV
	return result;
}
//--------------------------------------------------------------------------------------------------
