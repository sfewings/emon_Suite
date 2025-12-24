// NeoPixelFunLoop
// This example will move a trail of light around a series of pixels.  
// A ring formation of pixels looks best.  
// The trail will have a slowly fading tail.
// 
// This will demonstrate the use of the RotateRight method.
//
#include <EmonShared.h>

#include <SPI.h>
#include <RH_RF69.h>
#include <OneWire.h>
#include <DallasTemperature.h>

#include <NeoPixelBus.h>
#include <PinChangeInt.h>

#define HOUSE_BANNER
#undef BOAT_BANNER
#ifdef HOUSE_BANNER
    #define NETWORK_FREQUENCY 915.0
#elif BOAT_BANNER
    #define NETWORK_FREQUENCY 914.0
#endif

# define NUM_FONTS 3

const byte digits[NUM_FONTS][11][5]=
{
    {   //5*8 font
                            {0x3E,0x51,0x49,0x45,0x3E}, //0
                            {0x00,0x01,0x7F,0x21,0x00}, //1
                            {0x31,0x49,0x45,0x43,0x21}, //2
                            {0x46,0x69,0x51,0x41,0x42}, //3
                            {0x04,0x7F,0x24,0x14,0x0C}, //4
                            {0x4E,0x51,0x51,0x51,0x72}, //5
                            {0x06,0x49,0x49,0x29,0x1E}, //6
                            {0x60,0x50,0x48,0x47,0x40}, //7
                            {0x36,0x49,0x49,0x49,0x36}, //8
                            {0x3C,0x4A,0x49,0x49,0x30}, //9    
                            {0x00,0x08,0x08,0x08,0x00}, //-    
    },
    {  //5*8 but one pixel higher
                            {0x7C,0xA2,0x92,0x8A,0x7C}, //0
                            {0x00,0x02,0xFE,0x42,0x00}, //1
                            {0x62,0x92,0x8A,0x86,0x42}, //2
                            {0x8C,0xD2,0xA2,0x82,0x84}, //3
                            {0x08,0xFE,0x48,0x28,0x18}, //4
                            {0x9C,0xA2,0xA2,0xA2,0xE4}, //5
                            {0x0C,0x92,0x92,0x52,0x3C}, //6
                            {0xC0,0xA0,0x90,0x8E,0x80}, //7
                            {0x6C,0x92,0x92,0x92,0x6C}, //8
                            {0x78,0x94,0x92,0x92,0x60}, //9        
                            {0x00,0x10,0x10,0x10,0x00}, //-    
    },
    {   //4*8 font
                    //0
                   {0b00000000, 
                    0b01111100,
                    0b10000010, 
                    0b10000010, 
                    0b01111100},
                    //1
                   {0b00000000,
                    0b00000010, 
                    0b11111110, 
                    0b01000010, 
                    0b00000000},
                    //2
                   {0b00000000,
                    0b01100010,
                    0b10010010, 
                    0b10001010, 
                    0b01000110},
                    //3
                   {0b00000000,
                    0b01101100, 
                    0b10010010, 
                    0b10010010, 
                    0b01000100},
                    //4
                   {0b00000000,
                    0b00001000, 
                    0b11111110, 
                    0b01001000, 
                    0b00111000},
                    //5
                   {0b00000000,
                    0b10001100, 
                    0b10010010, 
                    0b10010010, 
                    0b11110010},
                    //6
                   {0b00000000,
                    0b01001100, 
                    0b10010010, 
                    0b10010010, 
                    0b01111100},
                    //7
                   {0b00000000,
                    0b11000000, 
                    0b10110000, 
                    0b10001100, 
                    0b10000010},
                    //8
                   {0b00000000,
                    0b01101100, 
                    0b10010010, 
                    0b10010010, 
                    0b01101100},
                    //9
                   {0b00000000,
                    0b01111100, 
                    0b10010010, 
                    0b10010010, 
                    0b01100100},
                    //-
                   {0b00000000,
                    0b00010000, 
                    0b00010000, 
                    0b00010000, 
                    0b00000000}
                  } 
};

const uint8_t g_fontWidth[NUM_FONTS] = {5,5,4};
const uint8_t LDR_PIN = A0;
const uint8_t VOLTAGE_MEASURE_PIN = A5;
const uint8_t TEMPERATURE_PIN = 4;
const uint8_t PIXEL_PIN = 3;
const uint8_t LED_PIN = A3;  //Pin 17
const uint8_t NUM_BUTTONS = 2;
const uint8_t  g_buttons[NUM_BUTTONS] = { A2, A1 };	//pin number for each input A1, A2.  Pins 15 & 16
const uint16_t NUM_PIXELS = 256;
const uint8_t MAX_INVERTERS = 3;

volatile unsigned long	g_lastButtonPush[NUM_BUTTONS]	= { 0,0 };

volatile uint8_t g_displayMode = 1; //0 is off, 1 is dimmed text, 2 is white light
volatile uint8_t g_fontIndex = 0;

volatile uint8_t g_numInterupts = 0;

NeoPixelBus<NeoGrbFeature, Neo800KbpsMethod> strip(NUM_PIXELS,PIXEL_PIN);

RH_RF69 g_rf69;

PayloadGPS          g_payloadGPS;
PayloadTemperature  g_payloadTemperature;
PayloadBase         g_payloadBase;
PayloadPulse        g_payloadPulse;
PayloadRain         g_payloadRain;
PayloadBattery      g_payloadBattery;
PayloadInverter     g_payloadInverter[MAX_INVERTERS];

time_t	g_startTime = 0;
int    g_currentDay = 0;
unsigned long g_rainStartOfToday = 0;


OneWire oneWire(4); //Pin 4
DallasTemperature temperatureSensor(&oneWire);


uint8_t readLDR()
{
    const int NUM_LOOPS = 10;
    long l = 0;
    for(int i=0; i <NUM_LOOPS; i++)
        l += analogRead( LDR_PIN );
    float value = l/NUM_LOOPS;
    uint8_t intensity = 1+(uint8_t) sqrt(62.5*value);
    //Serial.print(value);Serial.print(", ");Serial.println(intensity);
    return intensity;    
}

// routine called when external interrupt is triggered
void interruptHandlerIR() 
{
    /* Pin to interrupt map, ATmega328:
    * D0-D7 = PCINT 16-23 = PCIR2 = PD = PCIE2 = pcmsk2
    * D8-D13 = PCINT 0-5 = PCIR0 = PB = PCIE0 = pcmsk0
    * A0-A5 (D14-D19) = PCINT 8-13 = PCIR1 = PC = PCIE1 = pcmsk1
    */
    g_numInterupts = PCintPort::arduinoPin;
    
    uint8_t button = 0;
    while(g_buttons[button] != PCintPort::arduinoPin)
    {
        if( ++button == NUM_BUTTONS)
            return;		// we only support 3 buttons though we could get an interrupt for more!
    }
    unsigned long msSinceLastButton = millis()- g_lastButtonPush[button];
    g_lastButtonPush[button] = millis();

    if(msSinceLastButton <20)
        return;     //button debounce

    if( button == 1)
    {
        g_fontIndex = ((g_fontIndex+1) % NUM_FONTS);
    }

    if( button == 0)
    {
        g_displayMode = ( (g_displayMode+1) % 3);
    }
}



void bannerDigit(int digit, int offset, RgbColor colour)
{
    if(digit <0 || digit>10)
        return;

    for(int i=0; i <5;i++)
    {
        if(offset+i >= 0 )
        {
            int index = (offset+i)*8;
            for(int b=0; b<8;b++)
            {
                // RgbColor onColour = g_displayMode==2? RgbColor(0, 0, 0) : colour;
                // RgbColor offColour = g_displayMode==2? colour : RgbColor(0, 0, 0);
                RgbColor onColour = colour;
                RgbColor offColour = g_displayMode==2? RgbColor(255, 255, 255) : RgbColor(0, 0, 0);
                RgbColor pixelColour;
                if( (offset+i) %2 == 0)
                    pixelColour = digits[g_fontIndex][digit][i] & 1<<b ? onColour : offColour;
                else
                    pixelColour = digits[g_fontIndex][digit][i] & 1<<(7-b) ? onColour : offColour;
                strip.SetPixelColor(index+b, pixelColour);
            }
        }
    }
}

void printValue(float value, int decimals, RgbColor inColour, int offset = 0, uint8_t intensity = 255)
{
    RgbColor colour = RgbColor(inColour.R*intensity/255,inColour.G*intensity/255,inColour.B*intensity/255);

    for(uint16_t pixel=0; pixel <NUM_PIXELS; pixel++)
    {
        strip.SetPixelColor(pixel, (g_displayMode==2?RgbColor(255, 255, 255):RgbColor(0, 0, 0)));
    }

    if( g_displayMode != 0 )
    {

        bool negative = value < 0.0;
        int places = log10(fabs(value)) + decimals;
        if( (int)value == 0 )
            places = 1+decimals;

        int whole = (int) fabs(value);
        int fraction = (int) fabs(( value - (float)whole)*pow(10.0,decimals));

        // Serial.print("value:   "); Serial.println(value);
        // Serial.print("whole:   "); Serial.println(whole);
        // Serial.print("fraction:"); Serial.println(fraction);
        // Serial.print("places:  "); Serial.println(places);
        // Serial.print("decimals:"); Serial.println(decimals);
        // Serial.print("negative:"); Serial.println(negative);
        
        //use -1 as indication to align to centre
        if(offset == -1)
            offset = NUM_PIXELS/8/2 - (places + negative + 1)*(g_fontWidth[g_fontIndex]+1)/2;

        if(decimals > 0)
        {
            for (int i = 0; i < decimals; i++)
            {
                int digit = fraction % 10;
                bannerDigit(digit, offset, colour);
                fraction = fraction/10;
                offset += g_fontWidth[g_fontIndex]+1;
            }
            
            //decimal point
            int pos = offset*8;
            if( offset %2 == 1)
                pos+= 7;
            strip.SetPixelColor(pos, colour);
            offset += 2;
        }

        if(whole == 0)
            places = 1;
        else
            places = log10(whole)+1;

        for (int i=0; i<places; i++)
        {
            int digit = whole % 10;
            bannerDigit(digit, offset, colour);
            whole = whole/10;
            offset += g_fontWidth[g_fontIndex]+1;
        }

        if(negative)
        {
            bannerDigit(10, offset, colour);
            offset += g_fontWidth[g_fontIndex]+1;
        }
    }

    strip.Show();
}

void printValue(int value, RgbColor inColour, int offset = 0, uint8_t intensity = 255)
{
    RgbColor colour = RgbColor(inColour.R*intensity/255,inColour.G*intensity/255,inColour.B*intensity/255);

    for(uint16_t pixel=0; pixel <NUM_PIXELS; pixel++)
    {
        strip.SetPixelColor(pixel, (g_displayMode==2?RgbColor(255, 255, 255):RgbColor(0, 0, 0)));
    }

    if( g_displayMode != 0 )
    {
        int places = log10(abs(value));

        //use -1 as indication to align to centre
        if(offset == -1)
            offset = NUM_PIXELS/8/2 - (places+1)*(g_fontWidth[g_fontIndex]+1)/2;

        for (int i = 0; i <= places; i++)
        {
            int digit = value % 10;
            bannerDigit(digit, offset, colour);
            value = value/10;
            offset += g_fontWidth[g_fontIndex]+1;
        }
    }
    strip.Show();
}

void testBanner()
{

    for(int digit=0; digit<10;digit++)
    {
        for(int offset=0;offset<NUM_PIXELS/8;offset++)
        {
            bannerDigit( digit, offset, readLDR() );
            strip.Show();
            delay(20);
        }
    }

    for(int offset = 0; offset<NUM_PIXELS/8;offset++)
    {  
        bannerDigit( 0, offset+0, readLDR());
        bannerDigit( 1, offset+5, readLDR());
        bannerDigit( 2, offset+10, readLDR());
        bannerDigit( 3, offset+15, readLDR() );
        bannerDigit( 4, offset+20, readLDR() );
        bannerDigit( 5, offset+25, readLDR() );
        bannerDigit( 6, offset+30, readLDR() );
        bannerDigit( 7, offset+35, readLDR() );
        bannerDigit( 8, offset+40, readLDR() );
        bannerDigit( 9, offset+45, readLDR() );
        strip.Show();
        delay(20);
    }
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
		if (i<7) Serial.print(", ");
	}
	Serial.print(" }");
}

void setup()
{
    Serial.begin(9600);

	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(TEMPERATURE_JEENODE);

    g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

    pinMode( LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);


	Serial.print("RF69 initialise node: ");
	Serial.print(TEMPERATURE_JEENODE);
	Serial.print(" Freq: ");Serial.print(NETWORK_FREQUENCY,1); Serial.println("MHz");
	EmonSerial::PrintGPSPayload(NULL);
    memset(&g_payloadGPS, 0, sizeof(PayloadGPS));

    EmonSerial::PrintBasePayload(NULL);
    EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBatteryPayload(NULL);

    for(uint8_t button = 0; button < NUM_BUTTONS; button++)
    {
        attachPinChangeInterrupt(g_buttons[button], interruptHandlerIR, RISING);
    }


    memset( &g_payloadGPS,0, sizeof(PayloadGPS));
    memset( &g_payloadTemperature,0, sizeof(PayloadTemperature));
    memset( &g_payloadBase,0, sizeof(PayloadBase));
    memset( &g_payloadPulse,0, sizeof(PayloadPulse));
    memset( &g_payloadRain,0, sizeof(PayloadRain));
    memset( &g_payloadBattery,0, sizeof(PayloadBattery));
    for(int i=0; i<MAX_INVERTERS;i++)
    {
        memset( &g_payloadInverter[i],0, sizeof(PayloadInverter) );        
    }

    strip.Begin();
    strip.Show();

	//Temperature sensor setup
    g_payloadTemperature.subnode = 0;
	temperatureSensor.begin();
    g_payloadTemperature.numSensors = min(temperatureSensor.getDeviceCount(), MAX_TEMPERATURE_SENSORS);
	if (g_payloadTemperature.numSensors)
	{
		Serial.print(F("Temperature sensors "));

		for (int i = 0; i< g_payloadTemperature.numSensors; i++)
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
	else
	{
		Serial.println(F("No temperature sensors found"));
	}
}


void loop()
{
	//--------------------------------------------------------------------------------------------
	// 1. On RF recieve
	//--------------------------------------------------------------------------------------------	
    static int displayToggle = 0;
    static unsigned long displayToggleTime = millis();
    static unsigned long temperatureUpdateTime = millis();

	if (g_rf69.available())
	{
        digitalWrite(LED_PIN, HIGH);
        byte len = RH_RF69_MAX_MESSAGE_LEN;
        uint8_t buf[RH_RF69_MAX_MESSAGE_LEN];
        int node_id= -1;
        
		if (g_rf69.recv(buf, &len))
		{
			node_id = g_rf69.headerId();
		}

		if (node_id == GPS_NODE && len == sizeof(PayloadGPS))
		{
			g_payloadGPS = *(PayloadGPS*)buf;							// get payload data
			EmonSerial::PrintGPSPayload(&g_payloadGPS);				// print data to serial
		}

		if (node_id == PULSE_JEENODE && len == sizeof(PayloadPulse)) // === PULSE NODE ====
		{
			g_payloadPulse = *(PayloadPulse*)buf;							// get payload data

			EmonSerial::PrintPulsePayload(&g_payloadPulse);
		}

		if (node_id == RAIN_NODE && len == sizeof(PayloadRain))						// ==== RainGauge Jeenode ====
		{
			g_payloadRain = *(PayloadRain*)buf;	// get emonbase payload data
			
			if (g_rainStartOfToday == 0)
			{
				g_rainStartOfToday = g_payloadRain.rainCount;
			}
			EmonSerial::PrintRainPayload(&g_payloadRain);
		}

		if ( node_id == BASE_JEENODE && len == sizeof(PayloadBase))						// jeenode base Receives the time
		{
			g_payloadBase = *((PayloadBase*)buf);
			setTime(g_payloadBase.time);
			if (g_currentDay == -1)
			{
				//first time received from base
				g_currentDay = day();
			}
			EmonSerial::PrintBasePayload(&g_payloadBase);
		}
		if ( node_id == BATTERY_NODE && len == sizeof(PayloadBattery))						// jeenode base Receives the time
		{
            PayloadBattery payloadBattery = *((PayloadBattery*)buf);
            if( payloadBattery.crc == EmonSerial::CalcCrc(buf, sizeof(PayloadBattery)-2) && payloadBattery.subnode == 0 )
            {
                //we only get the voltage from battery node 0
                g_payloadBattery = *((PayloadBattery*)buf);
                EmonSerial::PrintBatteryPayload(&g_payloadBattery);
            }
		}
        if ( node_id == INVERTER_NODE && len == sizeof(PayloadInverter))
        {
            PayloadInverter inv = *((PayloadInverter*)buf);
			byte subnode = inv.subnode;
			if (subnode >= MAX_INVERTERS)
			{
				Serial.print(F("Invalid inverter subnode. Exiting"));
				return;
			}
			memcpy(&g_payloadInverter[subnode], &inv, sizeof(PayloadInverter));
			EmonSerial::PrintInverterPayload(&g_payloadInverter[subnode]);			 // print data to serial
        }
    }

    if( millis()-temperatureUpdateTime > 60000 && g_payloadTemperature.numSensors !=0 )
	{
        digitalWrite(LED_PIN, HIGH);

        temperatureUpdateTime = millis();
		//get the temperature of this unit (inside temperature)
		temperatureSensor.requestTemperatures();
        for(int i=0; i< g_payloadTemperature.numSensors; i++ )
        {
		    g_payloadTemperature.temperature[i] = temperatureSensor.getTempCByIndex(0) * 100;
        }
		//voltage divider is 1M and 1M. Reference voltage is 3.3v. AD range is 1024
		//voltage divider current draw is 29 uA
		float measuredvbat = analogRead(VOLTAGE_MEASURE_PIN);
		measuredvbat = (measuredvbat/1024.0 * 3.3) * (1000000.0+1000000.0)/1000000.0;
		g_payloadTemperature.supplyV =(unsigned long) (measuredvbat*1000);//sent in mV

		g_rf69.send((const uint8_t*) &g_payloadTemperature, sizeof(PayloadTemperature));
		if( g_rf69.waitPacketSent() )
		{
			EmonSerial::PrintTemperaturePayload(&g_payloadTemperature);
		}
		else
		{
			Serial.println(F("No packet sent"));
		}
        delay(500); //So the LED stays on a little longer 
	}

    if( millis()-displayToggleTime > 3000)
    {
		//update 24hr tallies
		if ((timeStatus() == timeSet))
		{
            if (day() != g_currentDay)
            {
				//reset the rain for the new day
                g_rainStartOfToday = g_payloadRain.rainCount;
                g_currentDay = day();
			}
		}        
        
        
        displayToggle++;
        displayToggleTime = millis();
        if( g_displayMode == 0)
        {
            //flash every three seconds when turned off. Remind to turn on!
            digitalWrite(LED_PIN, HIGH);
            delay(100);
        }
        //Serial.print("g_displayMode:");Serial.println(g_displayMode);
    }

    if( millis()-g_lastButtonPush[1] > 3600000 && g_displayMode == 2)
    {
        //Automatically turn off the while light after 1 hour (3600000ms)
        Serial.println("Auto turn off from full light mode");
        g_displayMode = 0;
    }
#ifdef HOUSE_BANNER
    if( displayToggle %2 == 0)
    {
        int totalPower = 0;
        for(int i=0; i<MAX_INVERTERS;i++)
        {
            totalPower += g_payloadInverter[i].pvInputPower;
        }

        if (g_payloadRain.rainCount - g_rainStartOfToday != 0)
        {
            //rainfall is blue
            printValue((float)(g_payloadRain.rainCount - g_rainStartOfToday)/5.0, 1, RgbColor(0,0,255),-1, readLDR());
        }
        else if( totalPower > 100 )
        {
            //Produced is green
            printValue( totalPower, RgbColor(0,255,0), -1, readLDR());
        }
        else
        {
            //print the battery voltage. Red
            printValue( (float) g_payloadBattery.voltage[0]/100.0, 1, RgbColor(255,0,0), -1, readLDR());
        }
    }    
    else
    {
        //Consumed is pink
        printValue(g_payloadPulse.power[2], RgbColor(255,128,128), -1, readLDR());
    }
#else
    if( displayToggle %2 == 0)
    {
        //Course is green
        printValue( g_payloadGPS.course, 1, RgbColor(0,255,0), -1, readLDR());
    }    
    else
    {
        //speed is blue
        printValue(g_payloadGPS.speed, 2, RgbColor(0,0,255), -1, readLDR());
    }
#endif
    
    //Serial.print(F("Num interrupts=")); Serial.println(g_numInterupts);

    digitalWrite(LED_PIN, LOW);
    if( g_displayMode == 0)
    {
        g_rf69.sleep();
        for(int i=0; i<300 && g_displayMode ==0;i++)
        {
            delay(10);
        }
    }
	else
    {
        delay(10);
    }

}
