//Needed
// WS2812, NeoPixel
// PWM library
// emon shared
// RadioHead RF69
// OLED SSD1306 Adafruit GFX
// APDS9930 proximity sensor
#include <PWM.h> 
#include <Wire.h>
#include <avr/wdt.h>    //watchdog timer

//Note: To stop loading the standard font and saving 1314 bytes of program memory, add the following
// Adafruit_GFX.cpp
//  line 31:  #define DONT_USE_STANDARD_FONT
//  line 1266-1268: surround the line "uint8_t line = pgm_read_byte(&font[c * 5 + i]);" with
//  #ifdef DONT_USE_STANDARD_FONT
//       uint8_t line = 255;  //will write all chars as a rectangular block
//  #else
//       uint8_t line = pgm_read_byte(&font[c * 5 + i]);
//  #endif
// glcdfont.c add the following lines around the font definition
//  #ifdef DONT_USE_STANDARD_FONT
//  extern const unsigned char font[] PROGMEM;
//  #else
// <the font definition>

#include <Adafruit_GFX.h>
#include <gfxfont.h>
#include <Adafruit_SSD1306.h>
// Add font headers from the Adafruit GFX "Fonts" folder.
// If these headers are not present in your installation adjust the paths/names
// #include <Fonts/FreeMono24pt7b.h>
// #include <Fonts/FreeSerif24pt7b.h>
// #include <Fonts/FreeMonoBold24pt7b.h>
// #include <Fonts/FreeMonoBoldOblique24pt7b.h>
// #include <Fonts/FreeMonoOblique24pt7b.h>
// #include <Fonts/FreeSans24pt7b.h>
// #include <Fonts/FreeSans18pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
// #include <Fonts/FreeSansBold24pt7b.h>
// #include <Fonts/FreeSansBoldOblique24pt7b.h>
// #include <Fonts/FreeSansOblique24pt7b.h>
// #include <Fonts/FreeSerif24pt7b.h>
// #include <Fonts/FreeSerifBold24pt7b.h>
// #include <Fonts/FreeSerifBoldItalic24pt7b.h>
// #include <Fonts/FreeSerifItalic24pt7b.h>


#include <APDS9930.h>
#include <RH_RF69.h>
#include <NeoPixelBus.h>
#include <EmonShared.h>


//#define HOUSE_BANNER
#define BOAT_BANNER
#ifdef HOUSE_BANNER
    #define NETWORK_FREQUENCY 915.0
#elif defined(BOAT_BANNER)
    #define NETWORK_FREQUENCY 914.0
#endif

// WS2812 LED strip definitions
const uint8_t PIXEL_PIN = 5;
const uint8_t LED_PIN = 9;          //LED on Moteino. Note that the PCB has an LED space at A3;  //Pin 17
const uint8_t TACHOMETER_PIN = 3;
const uint16_t NUM_PIXELS = 13;
NeoPixelBus<NeoRgbwFeature, Neo800KbpsMethod> strip(NUM_PIXELS,PIXEL_PIN);

//External Instrument light. 12v through voltage divider to about 3v when instrument lights are on
const uint8_t INSTRUMENT_LIGHT_PIN = 8;

//SSD1306 OLED definitions
const int8_t OLED_RESET     = -1; // Reset pin # (or -1 if sharing Arduino reset pin)
const uint8_t SCREEN_WIDTH = 128; // OLED display width, in pixels
const uint8_t SCREEN_HEIGHT = 32; // OLED display height, in pixels
const uint8_t SCREEN_ADDRESS = 0x3C; // OLED I2C address
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// APDS9930 proximity sensor
APDS9930 apds = APDS9930();
uint16_t proximity_data = 0;
float ambient_light = 0; // can also be an unsigned long
uint16_t ch0 = 0;
uint16_t ch1 = 1;

// RF69 network definitions
RH_RF69 g_rf69;

#ifdef HOUSE_BANNER
const uint8_t MAX_INVERTERS = 3;
PayloadPulse        g_payloadPulse;
PayloadTemperature  g_payloadTemperature;
PayloadBattery      g_payloadBattery;
PayloadInverter     g_payloadInverter[MAX_INVERTERS];
PayloadGPS          g_payloadGPS;

typedef enum {
    eFirstDisplayMode = 0, 
    eCurrentPower = 0,
	eCurrentTemperatures,
    eRailVoltage,
	eInverterIn,
    eGPSSpeed,
    eLastDisplayMode = eGPSSpeed,
}  ButtonDisplayMode;

const char* g_displayModeNames[][2] = {
    "Power", "W x100",
    "Temp", "Deg C",
    "Rail", "V /4",
    "Inv", "W x100",
    "GPS", "kts",
};
#elif defined(BOAT_BANNER)
const uint8_t MAX_INVERTERS = 3;
PayloadSevCon       g_payloadSevCon;
PayloadGPS          g_payloadGPS;
PayloadAnemometer   g_payloadAnemometer;
PayloadDalyBMS      g_payloadDalyBMS;

typedef enum {
    eFirstDisplayMode = 0, 
    eRPM = 0,
    eGPSSpeed,
	eWindSpeed,
    eBatterySoC,
    eLastDisplayMode = eBatterySoC,
}  ButtonDisplayMode;

const char* g_displayModeNames[][2] = {
    "RPM", "RPM x100",
    "Speed", "Speed - kts",
    "Wind", "Wind - kts",
    "Battery", "% SoC /4",
};
#endif



const uint8_t MOVING_AVERAGE_COUNT = 5;
float g_tachometer_movingAverage[MOVING_AVERAGE_COUNT] = {0};
uint8_t g_movingAverageIndex = 0;


void setLedStrip(RgbwColor inColour, uint8_t intensity = 255 )
{
    RgbwColor col = RgbwColor(inColour.R*intensity/255,inColour.G*intensity/255,inColour.B*intensity/255,0);

    for (uint16_t i = 0; i < NUM_PIXELS; ++i)
    {
        strip.SetPixelColor(i, col);
    }
    strip.Show();
}

bool getProximityOn()
{
    uint16_t proximityData;
    apds.readProximity(proximity_data);
   // Serial.print("Proximity: "); Serial.println(proximity_data);
    return proximity_data > 100; //tune threshold as needed
}

void setTachometer(float value)
{
    g_movingAverageIndex = (g_movingAverageIndex + 1) % MOVING_AVERAGE_COUNT;
    g_tachometer_movingAverage[g_movingAverageIndex] = value;
    float sum = 0;
    for(int i=0;i<MOVING_AVERAGE_COUNT;i++)
    {
        sum += g_tachometer_movingAverage[i];
    }
    value = sum / MOVING_AVERAGE_COUNT;
    uint32_t pwm_frequency =  ( 5000.0 * value + 100.0); // approx  250
    Serial.print("Tachometer: "); Serial.print(value,3); Serial.print(" PWM frequency: "); Serial.println(pwm_frequency);
    SetPinFrequencySafe(TACHOMETER_PIN, pwm_frequency);
    pwmWrite(TACHOMETER_PIN, 254); // ensure pin is High for 254/255 of duty cycle
}

void setup()
{
    pinMode( LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);

    Serial.begin(9600);
    Serial.println("Tachometer starting");

    // initialize the OLED object

    if(!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) 
    {
       Serial.println("OLED begin failed");
    }
    display.setRotation(2); //upside down
    display.setTextSize(1);
    display.setFont(&FreeSans12pt7b);
    display.setTextColor(WHITE);
    display.ssd1306_command(SSD1306_SETCONTRAST);
    display.ssd1306_command(1);  //set the contrast to the lowest possible. Still seems quite bright in the dark
    display.clearDisplay();

    // Initialize APDS-9930 (configure I2C and initial values)
    if ( !apds.init() ) 
    {
        Serial.println("APDS-9930 failed");
    }

    // Start running the APDS-9930 proximity sensor (no interrupts)
    apds.enableProximitySensor(false);
    apds.setProximityDiode(LED_DRIVE_12_5MA);
    apds.setProximityGain(PGAIN_2X);

    // Start running the APDS-9930 light sensor (no interrupts)
    apds.setAmbientLightGain(AGAIN_120X);
    apds.enableLightSensor(false);

    pinMode( INSTRUMENT_LIGHT_PIN, INPUT);


	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(BASE_JEENODE);    //doesn't matter which node as we don't transmit
    g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
	Serial.print(F("RF69 initialised Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println("MHz");

#ifdef HOUSE_BANNER
    EmonSerial::PrintGPSPayload(NULL);
    EmonSerial::PrintTemperaturePayload(NULL);
    EmonSerial::PrintPulsePayload(NULL);
	EmonSerial::PrintBatteryPayload(NULL);
    EmonSerial::PrintInverterPayload(NULL);

    memset( &g_payloadGPS,0, sizeof(PayloadGPS));
    memset( &g_payloadTemperature,0, sizeof(PayloadTemperature));
    memset( &g_payloadPulse,0, sizeof(PayloadPulse));
    memset( &g_payloadBattery,0, sizeof(PayloadBattery));
    for(int i=0; i<MAX_INVERTERS;i++)
    {
        memset( &g_payloadInverter[i],0, sizeof(PayloadInverter) );        
    }
#elif defined(BOAT_BANNER)
    // EmonSerial::PrintSevConPayload(NULL);
    // EmonSerial::PrintGPSPayload(NULL);
    // EmonSerial::PrintAnemometerPayload(NULL);
	// EmonSerial::PrintBatteryPayload(NULL);

    memset( &g_payloadGPS,0, sizeof(PayloadGPS));
    memset( &g_payloadSevCon,0, sizeof(PayloadSevCon));
    memset( &g_payloadAnemometer,0, sizeof(PayloadAnemometer));
    memset( &g_payloadDalyBMS,0, sizeof(PayloadDalyBMS));
#endif

    //initialize LED strip
    strip.Begin();
    strip.Show();

    //initialise PWM timers for tachometer output
    InitTimersSafe();

  	wdt_enable(WDTO_1S);    //watchdog timer 1 second

    digitalWrite(LED_PIN, LOW);
}



void loop()
{
    const unsigned long DISPLAY_UPDATE_INTERVAL_MS = 250;
    const unsigned long DISPLAYMODE_PERIOD_MS = 2000;
    static unsigned long lastDisplayUpdateTime = millis();
    static unsigned long lastDisplayModeChangeTime = millis();
    static ButtonDisplayMode displayMode = eFirstDisplayMode;
    static RgbwColor ledColor = RgbwColor(255, 255, 255, 255);

	wdt_reset();

	if (g_rf69.available())
	{
		//read the nodeID early to prevent overwriting before the buffer is read
		uint8_t node_id = g_rf69.headerId();

        //digitalWrite(LED_PIN, HIGH);
        byte len = RH_RF69_MAX_MESSAGE_LEN;
        uint8_t buf[RH_RF69_MAX_MESSAGE_LEN];
        
		if (g_rf69.recv(buf, &len))
		{
#ifdef HOUSE_BANNER
            if (node_id == GPS_NODE && len == sizeof(PayloadGPS))
            {
                g_payloadGPS = *(PayloadGPS*)buf;							// get payload data
                EmonSerial::PrintGPSPayload(&g_payloadGPS);				// print data to serial
            }
            else if (node_id == PULSE_JEENODE && len == sizeof(PayloadPulse)) // === PULSE NODE ====
            {
                g_payloadPulse = *(PayloadPulse*)buf;							// get payload data

                EmonSerial::PrintPulsePayload(&g_payloadPulse);
            }
            else if ( node_id == BATTERY_NODE && len == sizeof(PayloadBattery))						// jeenode base Receives the time
            {
                PayloadBattery payloadBattery = *((PayloadBattery*)buf);
                if( payloadBattery.crc == EmonSerial::CalcCrc(buf, sizeof(PayloadBattery)-2) && payloadBattery.subnode == 0 )
                {
                    //we only get the voltage from battery node 0
                    g_payloadBattery = *((PayloadBattery*)buf);
                    EmonSerial::PrintBatteryPayload(&g_payloadBattery);
                }
            }
            else if ( node_id == INVERTER_NODE && len == sizeof(PayloadInverter))
            {
                PayloadInverter inv = *((PayloadInverter*)buf);
                byte subnode = inv.subnode;
                if (subnode >= MAX_INVERTERS)
                {
                    //Serial.print(F("Invalid inverter subnode. Exiting"));
                    return;
                }
                memcpy(&g_payloadInverter[subnode], &inv, sizeof(PayloadInverter));
                EmonSerial::PrintInverterPayload(&g_payloadInverter[subnode]);			 // print data to serial
            }
            else if( node_id == TEMPERATURE_JEENODE && len == sizeof(PayloadTemperature)) // === TEMPERATURE NODE ====
            {
                g_payloadTemperature = *(PayloadTemperature*)buf;							// get payload data
                EmonSerial::PrintTemperaturePayload(&g_payloadTemperature);				// print data to serial
            }
#elif defined(BOAT_BANNER)
            if (node_id == GPS_NODE && len == sizeof(PayloadGPS))
            {
                PayloadGPS payloadGPS = *(PayloadGPS*)buf;
                if(payloadGPS.subnode == 0)
                {
                    g_payloadGPS = *(PayloadGPS*)buf;
                    EmonSerial::PrintGPSPayload(&g_payloadGPS);
                }
            }
			else if (node_id == DALY_BMS_NODE  && (len == sizeof(PayloadDalyBMS)-2 || len == sizeof(PayloadDalyBMS)) )		//some Daly BMS don't send the crc
			{
                g_payloadDalyBMS = *(PayloadDalyBMS*)buf;
                EmonSerial::PrintDalyBMSPayload(&g_payloadDalyBMS);
			}
            else if ( node_id == SEVCON_CAN_NODE && len == sizeof(PayloadSevCon))
            {
                g_payloadSevCon = *(PayloadSevCon*)buf;
                EmonSerial::PrintSevConPayload(&g_payloadSevCon);
            }
            else if ( node_id == ANEMOMETER_NODE && len == sizeof(PayloadAnemometer))
            {
                PayloadAnemometer payloadAnemometer = *(PayloadAnemometer*)buf;
                if( payloadAnemometer.subnode == 2) //True wind is published on node 2
                {    
                    g_payloadAnemometer = *(PayloadAnemometer*)buf;
                    EmonSerial::PrintAnemometerPayload(&g_payloadAnemometer);
                }
            }
#endif
        }
        //digitalWrite(LED_PIN, LOW);
    }

    static bool proximityOn = false;
    if(proximityOn != getProximityOn())
    {
        if( !proximityOn ) //was off, now on
        {
            digitalWrite(LED_PIN, HIGH);
            if( displayMode == eLastDisplayMode)
                displayMode = eFirstDisplayMode;
            else
                displayMode = (ButtonDisplayMode)((int)displayMode + 1);
                lastDisplayModeChangeTime = millis();
        }
        else
        {
            digitalWrite(LED_PIN, LOW);
        }
        proximityOn = !proximityOn;
    }


    if( lastDisplayUpdateTime + DISPLAY_UPDATE_INTERVAL_MS < millis() )
    {
        lastDisplayUpdateTime = millis();
        
        //centre the text to the OLED display
        uint8_t textOffset = (millis() - lastDisplayModeChangeTime) > DISPLAYMODE_PERIOD_MS;
        int16_t x1, y1, w, h;
        display.getTextBounds(g_displayModeNames[displayMode][textOffset], 0, SCREEN_HEIGHT, &x1, &y1, &w, &h);
        display.clearDisplay();
        display.setCursor((SCREEN_WIDTH-w)/2,SCREEN_HEIGHT - ((SCREEN_HEIGHT-h)/2));
        display.print(g_displayModeNames[displayMode][textOffset]);
        display.display();

        switch(displayMode)
        {
#ifdef HOUSE_BANNER
            case eCurrentPower:
                setTachometer((float)(g_payloadPulse.power[2]/2500.0));
                ledColor = RgbwColor(255,255,255,255); // white
                break;
            case eCurrentTemperatures:
                setTachometer((float)(g_payloadTemperature.temperature[0]/100.0/25.0));
                ledColor = RgbwColor(255,0,0,0); // red
                break;
            case eRailVoltage:
                setTachometer((float)(g_payloadBattery.voltage[0]/100.0/100.0));
                ledColor = RgbwColor(0,255,255,0); // cyan
                break;
            case eInverterIn:
                {
                    unsigned short inverterIn = 0;
                    for(int i=0; i<MAX_INVERTERS;i++)
                    {
                        inverterIn += g_payloadInverter[i].pvInputPower;
                    }
                    setTachometer((float)(inverterIn/2500.0));
                    ledColor = RgbwColor(0,255,0,0); // green
                }
                break;
            case eGPSSpeed:
                setTachometer(g_payloadGPS.speed/10.0);
                ledColor = RgbwColor(0,0,255,0); // blue
                break;

#elif defined(BOAT_BANNER)
            case eRPM:
                setTachometer(fabs((float)(g_payloadSevCon.rpm/2500.0))); //engin RPM
                ledColor = RgbwColor(255,255,255,255); // white
                break;
            case eWindSpeed:
                setTachometer(g_payloadAnemometer.windSpeed/25.0);  //speed in knots
                ledColor = RgbwColor(0,255,0,0); // green
                break;
            case eGPSSpeed:
                setTachometer(g_payloadGPS.speed/25.0);             //speed in knots
                ledColor = RgbwColor(0,0,255,0); // blue
                break;
            case eBatterySoC:
                setTachometer((float)(g_payloadDalyBMS.batterySoC/1000.0)); //SoC is in 0.1% units
                ledColor = RgbwColor(255,0,0,0); // red
                break;
#endif
        }
    }

    //do the lighting based on ambient light and whether the external instrument lights are switched on
    uint8_t intensity = 0;
    if( digitalRead(INSTRUMENT_LIGHT_PIN) == HIGH )
    {
        intensity = 4;
    }
    else
    {
        // Get the intensity of the ambient light. 
        float ambient_light;
        apds.readAmbientLightLux(ambient_light);
        ambient_light = constrain(ambient_light, 0, 255.0);
        intensity = map(ambient_light, 0, 255.0, 0, 255);   //0 turns off when light is very low!
        //Serial.print(ambient_light);Serial.print(",");Serial.println(intensity);
    }
    setLedStrip(ledColor, intensity ); // adjust brightness based on ambient light

    return;
}
