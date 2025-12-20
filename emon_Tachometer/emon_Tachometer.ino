//Needed
// WS2812, NeoPixel
// PWM library
// emon shared
// RadioHead RF69
// OLED SSD1306 Adafruit GFX
// APDS9930 proximity sensor
#include <PWM.h> 
#include <Wire.h>

#include <Adafruit_GFX.h>
#include <gfxfont.h>
#include <Adafruit_SSD1306.h>
#include <APDS9930.h>
#include <RH_RF69.h>
#include <NeoPixelBus.h>
#include <EmonShared.h>


#define HOUSE_BANNER
//#define BOAT_BANNER
#ifdef HOUSE_BANNER
    #define NETWORK_FREQUENCY 915.0
#elif defined(BOAT_BANNER)
    #define NETWORK_FREQUENCY 914.0
#endif

// WS2812 LED strip definitions
const uint8_t PIXEL_PIN = 3;
const uint8_t LED_PIN = 9;  //LED on Moteino. Note that the PCB has an LED space at A3;  //Pin 17
const uint16_t NUM_PIXELS = 7;
NeoPixelBus<NeoGrbFeature, Neo800KbpsMethod> strip(NUM_PIXELS,PIXEL_PIN);


//SSD1306 OLED definitions
const int8_t OLED_RESET     = -1; // Reset pin # (or -1 if sharing Arduino reset pin)
const uint8_t SCREEN_WIDTH = 128; // OLED display width, in pixels
const uint8_t SCREEN_HEIGHT = 32; // OLED display height, in pixels
const uint8_t SCREEN_ADDRESS = 0x3C; // OLED I2C address
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// Add font headers from the Adafruit GFX "Fonts" folder.
// If these headers are not present in your installation adjust the paths/names
#include <Fonts/FreeMono24pt7b.h>
#include <Fonts/FreeSerif24pt7b.h>
#include <Fonts/FreeMonoBold24pt7b.h>
#include <Fonts/FreeMonoBoldOblique24pt7b.h>
#include <Fonts/FreeMonoOblique24pt7b.h>
#include <Fonts/FreeSans24pt7b.h>
#include <Fonts/FreeSans18pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
#include <Fonts/FreeSansBold24pt7b.h>
#include <Fonts/FreeSansBoldOblique24pt7b.h>
#include <Fonts/FreeSansOblique24pt7b.h>
#include <Fonts/FreeSerif24pt7b.h>
#include <Fonts/FreeSerifBold24pt7b.h>
#include <Fonts/FreeSerifBoldItalic24pt7b.h>
#include <Fonts/FreeSerifItalic24pt7b.h>

struct FontInfo { const GFXfont* font; const char* name; };
const FontInfo g_fonts[] = {
//    {&FreeMono24pt7b, "FreeMono24pt7b" },
//    {&FreeSerif24pt7b, "FreeSerif24pt7b" },
    //{&FreeMonoBold24pt7b, "FreeMonoBold24pt7b" },
    // {&FreeMonoBoldOblique24pt7b, "FreeMonoBoldOblique24pt7b" },
    // {&FreeMonoOblique24pt7b, "FreeMonoOblique24pt7b" },
    // {&FreeSans24pt7b, "FreeSans24pt7b" },
     {&FreeSans18pt7b, "FreeSans18pt7b" },
     //{&FreeSans12pt7b, "FreeSans12pt7b" },
    // {&FreeSansBold24pt7b, "FreeSansBold24pt7b" },
    // {&FreeSansBoldOblique24pt7b, "FreeSansBoldOblique24pt7b" },
    // {&FreeSansOblique24pt7b, "FreeSansOblique24pt7b" },
    // {&FreeSerif24pt7b, "FreeSerif24pt7b" },
    // {&FreeSerifBold24pt7b, "FreeSerifBold24pt7b" },
    // {&FreeSerifBoldItalic24pt7b, "FreeSerifBoldItalic24pt7b" },
    // {&FreeSerifItalic24pt7b, "FreeSerifItalic24pt7b" }
};
const size_t FONT_COUNT = sizeof(g_fonts) / sizeof(g_fonts[0]);


// APDS9930 proximity sensor
APDS9930 apds = APDS9930();
uint16_t proximity_data = 0;
float ambient_light = 0; // can also be an unsigned long
uint16_t ch0 = 0;
uint16_t ch1 = 1;


// RF69 network definitions
RH_RF69 g_rf69;

const uint8_t MAX_INVERTERS = 3;
PayloadGPS          g_payloadGPS;
PayloadTemperature  g_payloadTemperature;
PayloadPulse        g_payloadPulse;
PayloadBattery      g_payloadBattery;
PayloadInverter     g_payloadInverter[MAX_INVERTERS];


typedef enum {
    eFirstDisplayMode = 0, 
    eCurrentPower = 0,
	eCurrentTemperatures,
    eRailVoltage,
	eInverterIn,
    eGPSSpeed,
    eLastDisplayMode = eGPSSpeed,
}  ButtonDisplayMode;


const uint8_t tachPin = 5; //Pin 5 = OC1A


void setFont(uint8_t fontIndex)
{
    display.clearDisplay();
    //display.setTextSize(1);          // keep text size at 1 when using GFX fonts
    if( fontIndex < FONT_COUNT )
    {
        display.setFont(g_fonts[fontIndex].font);
        Serial.println("Using font: " + String(g_fonts[fontIndex].name) );
    }
    else
        display.setFont(NULL);  // restore default font
}

void setLedStrip(RgbColor inColour, uint8_t intensity = 255 )
{
    RgbColor col = RgbColor(inColour.R*intensity/255,inColour.G*intensity/255,inColour.B*intensity/255);

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
    uint32_t movingAverage[5];
    uint32_t pwm_frequency =  ( 5000.0 * value + 250.0); // approx

    SetPinFrequencySafe(tachPin, frequency);
    pwmWrite(tachPin, 254); // ensure pin is High

}

void setup()
{
    pinMode( LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);

    Serial.begin(9600);
    Serial.println(F("Tachometer starting"));

    // initialize the OLED object

    if(display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) 
    {
       Serial.println(F("OLED failed"));
    }
    display.setRotation(2); //upside down
    display.setTextSize(2);
    display.setFont(&FreeSans12pt7b);
    display.setTextColor(WHITE);
    display.clearDisplay();

    // Initialize APDS-9930 (configure I2C and initial values)
    if ( !apds.init() ) 
    {
        Serial.println(F("APDS-9930 failed"));
    }

    // Start running the APDS-9930 proximity sensor (no interrupts)
    apds.enableProximitySensor(false);
    apds.setProximityDiode(LED_DRIVE_12_5MA);
    apds.setProximityGain(PGAIN_2X);

    // Start running the APDS-9930 light sensor (no interrupts)
    apds.setAmbientLightGain(AGAIN_120X);
    apds.enableLightSensor(false);


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

    strip.Begin();
    strip.Show();

    digitalWrite(LED_PIN, LOW);
}



void loop()
{

    static ButtonDisplayMode displayMode = eFirstDisplayMode;
    static RgbColor ledColor = RgbColor(255, 255, 255);
    
    //Tasks
    //read APDS9930 proximity and ambient light and update displayNode
    //recevie data from RF69 nodes
    //update OLED display

	if (g_rf69.available())
	{
		//read the nodeID early to prevent overwriting before the buffer is read
		uint8_t node_id = g_rf69.headerId();

        digitalWrite(LED_PIN, HIGH);
        byte len = RH_RF69_MAX_MESSAGE_LEN;
        uint8_t buf[RH_RF69_MAX_MESSAGE_LEN];
        
		if (g_rf69.recv(buf, &len))
		{

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
        }
        digitalWrite(LED_PIN, LOW);
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
        }
        else
        {
            digitalWrite(LED_PIN, LOW);
        }
        proximityOn = !proximityOn;
    }

    display.clearDisplay();
    display.setCursor(0, 31);
    switch(displayMode)
    {
        case eGPSSpeed:
            display.print("GPS ");
            display.print(g_payloadGPS.speed);
            ledColor = RgbColor(0,0,255); // blue
            break;
        case eCurrentTemperatures:
            display.print((float)(g_payloadTemperature.temperature[0]/100.0),1);
            ledColor = RgbColor(255,0,0); // red
            break;
        case eCurrentPower:
            display.print((float)(g_payloadPulse.power[2]),1);
            ledColor = RgbColor(255,255,255); // white
            break;
        case eRailVoltage:
            display.print((float)(g_payloadBattery.voltage[0]/100.0),1);
            ledColor = RgbColor(0,255,255); // cyan
            break;
        case eInverterIn:
            {
                unsigned short inverterIn = 0;
                for(int i=0; i<MAX_INVERTERS;i++)
                {
                    inverterIn += g_payloadInverter[i].pvInputPower;
                }
                display.print(inverterIn);
                ledColor = RgbColor(0,255,0); // green
            }
            break;
    }
    display.display();

    float ambient_light;
    apds.readAmbientLightLux(ambient_light);
    setLedStrip(ledColor, map(ambient_light, 0, 1000, 20, 255) ); // adjust brightness based on ambient light
//    display.print(ambient_light);
//    display.display();

    return;

    // int fontIndex = 0;
    // for(uint8_t intensity = 255; intensity > 0 ; intensity -= 51)
    // {
    //     if(getProximityOn())
    //     {
    //     }
    //     setFont(fontIndex++%FONT_COUNT);
    //     display.clearDisplay();
    //     display.setCursor(0, 31);
    //     display.print("0125AB");
    //     display.display();
    //     Serial.print("Intensity: "); Serial.println(intensity);

    //     setLedStrip(RgbColor(0,255,0), intensity); // green
    //     delay(200);
    //     setLedStrip(RgbColor(255,255,0), intensity); // yellow
    //     delay(200);
    //     setLedStrip(RgbColor(255,0,0), intensity); // red
    //     delay(200);
    //     setLedStrip(RgbColor(0,0,255), intensity); // blue
    //     delay(200);
    // }



    // static unsigned long lastReceivedFromSevCon = millis();

    // if (g_rf69.available())
    // {
    //     digitalWrite(LED_PIN, HIGH);
    //     byte len = RH_RF69_MAX_MESSAGE_LEN;
    //     uint8_t buf[RH_RF69_MAX_MESSAGE_LEN];
    //     int node_id= -1;
        
    //     if (g_rf69.recv(buf, &len))
    //     {
    //         node_id = g_rf69.headerId();
    //     }

    //     if (node_id == SEVCON_CAN_NODE && len == sizeof(PayloadSevCon)) // === SEVCON NODE ====
    //     {
    //         g_payloadSevCon = *(PayloadSevCon*)buf;							// get payload data
    //         EmonSerial::PrintSevConPayload(&g_payloadSevCon);				// print data to serial
    //         lastReceivedFromSevCon = millis();
    //     }
    //     digitalWrite(LED_PIN, LOW);
    // }
}
