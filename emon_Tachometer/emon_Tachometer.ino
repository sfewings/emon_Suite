//Libraries needed, one entry per include in this sketch. Names are as they appear in the Arduino
//Library Manager, and the versions are what this sketch was last built against (Moteino, AVR core
//1.8.8). Two of them are not in the Library Manager and have to be installed by hand.
//
// <PWM.h>                  PWM 5.0, by Sam Knight. NOT in the Library Manager, install by hand
//                          https://github.com/terryjmyers/PWM
// <Wire.h>                 Bundled with the Arduino AVR core, nothing to install
// <EEPROM.h>               Bundled with the Arduino AVR core, nothing to install
// <avr/wdt.h>              avr-libc, part of the avr-gcc toolchain, nothing to install
// <Adafruit_GFX.h>         Adafruit GFX Library 1.12.6. Also supplies <gfxfont.h> and every
// <gfxfont.h>              Fonts/ header, so it covers <Fonts/FreeSans12pt7b.h> as well
// <Fonts/FreeSans12pt7b.h> https://github.com/adafruit/Adafruit-GFX-Library
// <Adafruit_SSD1306.h>     Adafruit SSD1306 2.5.17. Pulls in Adafruit BusIO 1.17.4 as a dependency
//                          https://github.com/adafruit/Adafruit_SSD1306
// <APDS9930.h>             APDS-9930 Ambient Light and Proximity Sensor 1.5.1, by Davide Depau
//                          NOT in the Library Manager, install by hand
//                          https://github.com/Davideddu/APDS9930
// <RH_RF69.h>              RadioHead 1.143.1, by Mike McCauley
//                          https://www.airspayce.com/mikem/arduino/RadioHead/
// <NeoPixelBus.h>          NeoPixelBus by Makuna 2.8.4. The Library Manager name includes the
//                          "by Makuna". This is not Adafruit_NeoPixel, the API differs
//                          https://github.com/Makuna/NeoPixelBus
// <EmonShared.h>           This repository. emon_Suite/EmonShared is linked into the Arduino
//                          libraries folder. It includes TimeLib.h, so the Time library is
//                          needed too: Time 1.6.1, by Michael Margolis and Paul Stoffregen
//
#include <PWM.h>
#include <Wire.h>
#include <avr/wdt.h>    //watchdog timer

//Note: This sketch only just fits in the 31744 bytes of a Moteino, so it needs the library edits below.
//They live outside this repository and are lost whenever the libraries are updated, so if the build
//suddenly overflows, check these first.

//Note: To save 1016 bytes of program memory, stop the Adafruit logo being compiled in. The splash is
//drawn into the buffer by display.begin() and then immediately overwritten by clearDisplay(), so
//nothing is lost. In Adafruit_SSD1306.h (2.5.17 line 36) uncomment the define Adafruit provide:
//  #define SSD1306_NO_SPLASH
//This cannot be defined in the sketch. Adafruit_SSD1306.cpp is a separate translation unit and never
//sees it, so both splash.h and the drawBitmap calls in begin() still compile in. Measured: no change.

//Note: To stop loading the standard font and saving 1314 bytes of program memory, add the following.
//The standard font is unused because this sketch always sets a custom font with display.setFont()
// Adafruit_GFX.cpp
//  line 31:  #define DONT_USE_STANDARD_FONT
//  In function ::drawChar()
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


#include <EEPROM.h>
#define EEPROM_BASE 0x10	//where values are stored in EEPROM

#include <APDS9930.h>
#include <RH_RF69.h>
#include <NeoPixelBus.h>
#include <EmonShared.h>

//Serial diagnostics for the received payloads and the tachometer value. Left off, for two reasons.
//It costs about 1300 bytes of program memory, which this sketch does not have to spare: the payload
//dumps are large and they drag in the floating point printing code with them. It is also slow. At 9600
//baud a burst of payloads takes longer to print than the 8 second watchdog allows, and Serial.print()
//blocks once the 64 byte transmit buffer is full.
//Uncomment for bench debugging, and check the program storage still fits before flashing.
//#define SERIAL_PAYLOAD_DEBUG
#ifdef SERIAL_PAYLOAD_DEBUG
    #define PAYLOAD_DEBUG(x) x
#else
    #define PAYLOAD_DEBUG(x)
#endif


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

//Brightness limits for the LED strip. The upper limit keeps the strip supply current, and so the
//regulator temperature, in check. 13 RGBW pixels at full white made from R+G+B draws about 780mA
const uint8_t LED_MIN_INTENSITY = 3;            //leave at least some glow when it is otherwise dark
const uint8_t LED_MAX_INTENSITY = 96;
const uint8_t LED_INSTRUMENT_INTENSITY = 8;     //instrument lights are on, so it is dark outside

//External Instrument light. 12v through voltage divider to about 3v when instrument lights are on
const uint8_t INSTRUMENT_LIGHT_PIN = 8;

//SSD1306 OLED definitions
const int8_t OLED_RESET     = -1; // Reset pin # (or -1 if sharing Arduino reset pin)
const uint8_t SCREEN_WIDTH = 128; // OLED display width, in pixels
const uint8_t SCREEN_HEIGHT = 32; // OLED display height, in pixels
const uint8_t SCREEN_ADDRESS = 0x3C; // OLED I2C address
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
bool g_displayOk = false;   //false if display.begin() failed. The framebuffer is malloc'd, so on a
                            //failure it is NULL and every display call writes through address 0

// APDS9930 proximity sensor
APDS9930 apds = APDS9930();
uint16_t proximity_data = 0;
float g_ambientLight = 255.0;   //last good ambient light reading, clamped to 0-255
//Separate on and off thresholds so sensor noise can't step through the display modes
const uint16_t PROXIMITY_ON_THRESHOLD = 150;
const uint16_t PROXIMITY_OFF_THRESHOLD = 80;

// RF69 network definitions
RH_RF69 g_rf69;

#ifdef HOUSE_BANNER
const uint8_t MAX_INVERTERS = 3;
PayloadPulse        g_payloadPulse;
PayloadTemperature  g_payloadTemperature;
PayloadBattery      g_payloadBattery;
PayloadInverter     g_payloadInverter[MAX_INVERTERS];
//PayloadGPS          g_payloadGPS;

typedef enum {
    eFirstDisplayMode = 0, 
    eCurrentPower = 0,
	eCurrentTemperatures,
    eRailVoltage,
	eInverterIn,
//    eGPSSpeed,
    eLastDisplayMode = eInverterIn,
}  ButtonDisplayMode;

const char* g_displayModeNames[][2] = {
    "Power", "W x100",
    "Temp", "Deg C",
    "Rail", "V /4",
    "Inv", "W x100",
//    "GPS", "kts",
};
#elif defined(BOAT_BANNER)
PayloadSevCon       g_payloadSevCon;
PayloadGPS          g_payloadGPS;
PayloadAnemometer   g_payloadAnemometer;
PayloadDalyBMS      g_payloadDalyBMS;

typedef enum {
    eFirstDisplayMode = 0, 
	eWindSpeed =0,
    eBatterySoC,
    eRPM,
    eGPSSpeed,
    eLastDisplayMode = eGPSSpeed,
}  ButtonDisplayMode;

const char* g_displayModeNames[][2] = {
    "Wind", "Wind - kts",
    "Battery", "% SoC /4",
    "RPM", "RPM x100",
    "Speed", "Speed - kts",
};
#endif
ButtonDisplayMode g_displayMode = eFirstDisplayMode;


const uint8_t MOVING_AVERAGE_COUNT = 3;
float g_tachometer_movingAverage[MOVING_AVERAGE_COUNT] = {0};
uint8_t g_movingAverageIndex = 0;

//Tachometer PWM output. value 0.0-1.0 maps onto TACHOMETER_MIN_HZ..TACHOMETER_MIN_HZ+TACHOMETER_SPAN_HZ
const float TACHOMETER_MIN_HZ = 100.0;
const float TACHOMETER_SPAN_HZ = 5000.0;
const uint8_t TACHOMETER_DUTY = 254;    //pin is high for 254/255 of the duty cycle

const unsigned long PACKET_TIMEOUT_MS = 60000; // 60 seconds
#ifdef HOUSE_BANNER
unsigned long g_lastPayloadPulseTime = 0;
unsigned long g_lastPayloadTemperatureTime = 0;
unsigned long g_lastPayloadBatteryTime = 0;
unsigned long g_lastPayloadInverterTime = 0;
#elif defined(BOAT_BANNER)
unsigned long g_lastPayloadSevConTime = 0;
unsigned long g_lastPayloadAnemometerTime = 0;
unsigned long g_lastPayloadGPSTime = 0;
unsigned long g_lastPayloadDalyBMSTime = 0;
#endif


uint8_t readEEPROM(int offset)
{
	uint8_t value = 0;
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(uint8_t); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_BASE + offset * sizeof(uint8_t) + l);
	}

	return value;
}

void writeEEPROM(int offset, uint8_t value)
{
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(uint8_t); l++)
	{
		EEPROM.write(EEPROM_BASE + offset * sizeof(uint8_t) + l, *(pc + l));
	}
}



void setLedStrip(RgbwColor inColour, uint8_t intensity = 255 )
{
    //Note the uint16_t casts. uint8_t*uint8_t promotes to a 16 bit signed int on AVR, and 255*255
    //overflows it. Pass the white channel through so that white can use the strip's W element
    RgbwColor col = RgbwColor((uint16_t)inColour.R*intensity/255,
                              (uint16_t)inColour.G*intensity/255,
                              (uint16_t)inColour.B*intensity/255,
                              (uint16_t)inColour.W*intensity/255);

    for (uint16_t i = 0; i < NUM_PIXELS; ++i)
    {
        strip.SetPixelColor(i, col);
    }
    strip.Show();
}

//Hysteresis around the threshold, so currentState is needed to decide which one applies
bool getProximityOn(bool currentState)
{
    if( !apds.readProximity(proximity_data) )
        return currentState;    //the I2C read failed. Leave the state alone
   // Serial.print("Proximity: "); Serial.println(proximity_data);
    if( currentState )
        return proximity_data > PROXIMITY_OFF_THRESHOLD;
    return proximity_data > PROXIMITY_ON_THRESHOLD;
}

void setTachometer(float value)
{
    //Clamp before the value reaches the PWM hardware. The payload values arrive over RF and some of
    //them are signed or floats, so a bad packet could otherwise ask for a nonsense frequency
    if( isnan(value) || value < 0.0 )
        value = 0.0;
    if( value > 1.0 )
        value = 1.0;

    g_movingAverageIndex = (g_movingAverageIndex + 1) % MOVING_AVERAGE_COUNT;
    g_tachometer_movingAverage[g_movingAverageIndex] = value;
    float sum = 0;
    for(int i=0;i<MOVING_AVERAGE_COUNT;i++)
    {
        sum += g_tachometer_movingAverage[i];
    }
    value = sum / MOVING_AVERAGE_COUNT;
    uint32_t pwm_frequency =  ( TACHOMETER_SPAN_HZ * value + TACHOMETER_MIN_HZ); // approx  250
    //included in the payload debug because printing the float here is what pulls in the ~440 byte
    //floating point print code, so it has to go with the payload dumps to realise the saving
    PAYLOAD_DEBUG(Serial.print("Tachometer: "); Serial.print(value,3); Serial.print(" PWM frequency: "); Serial.println(pwm_frequency));
    if( !SetPinFrequencySafe(TACHOMETER_PIN, pwm_frequency) )
    {
        Serial.print(F("SetPinFrequencySafe failed: ")); Serial.println(pwm_frequency);
        return;
    }
    pinMode(TACHOMETER_PIN, OUTPUT);
    pwmWrite(TACHOMETER_PIN, TACHOMETER_DUTY); // ensure pin is High for 254/255 of duty cycle
}

//No data to display, so stop driving the tachometer. Sitting at a 254/255 duty cycle indefinitely is
//near DC into the gauge, and if the load is inductive the flyback on each edge injects current into
//the pin. Released to a high impedance input, which the gauge reads as zero.
//Change this to pwmWrite(TACHOMETER_PIN, 0) or a steady high if the gauge needs a defined idle level
void setTachometerOff()
{
    for(int i=0;i<MOVING_AVERAGE_COUNT;i++)
    {
        g_tachometer_movingAverage[i] = 0.0;
    }
    pinMode(TACHOMETER_PIN, INPUT);
}

//A reset part way through an I2C transfer can leave a slave holding SDA low, which stops the master
//generating a START for ever after. Clock SCL by hand until the slave lets go, then issue a STOP
void i2cBusClear()
{
    pinMode(SDA, INPUT_PULLUP);
    pinMode(SCL, INPUT_PULLUP);
    delayMicroseconds(10);

    for (uint8_t i = 0; i < 9 && digitalRead(SDA) == LOW; i++)
    {
        digitalWrite(SCL, LOW);      //clears the pull up before the pin becomes an output
        pinMode(SCL, OUTPUT);
        delayMicroseconds(5);
        pinMode(SCL, INPUT_PULLUP);  //release, the pull up takes it high
        delayMicroseconds(5);
    }

    //STOP condition. SDA low to high while SCL is high
    digitalWrite(SDA, LOW);
    pinMode(SDA, OUTPUT);
    delayMicroseconds(5);
    pinMode(SDA, INPUT_PULLUP);
    delayMicroseconds(5);
}

void setup()
{
    //Capture the reset cause and get the watchdog out of the way before anything else. After a watchdog
    //reset the AVR re-enables the watchdog at its 16ms minimum, and if the bootloader does not clear it
    //the chip resets again before setup() can finish. That is an endless reset loop which looks exactly
    //like a dead board, and the reset button does not help either
    uint8_t mcusr = MCUSR;
    MCUSR = 0;
    wdt_disable();

    pinMode( LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);

  	wdt_enable(WDTO_8S);    //watchdog timer 8 seconds, as used by the other emon nodes

    Serial.begin(9600);
    Serial.println("Tachometer starting");
    Serial.print(F("Reset cause MCUSR=0x")); Serial.println(mcusr, HEX);   //0 if the bootloader cleared it
    if( mcusr & _BV(WDRF) )  Serial.println(F(" watchdog reset"));
    if( mcusr & _BV(BORF) )  Serial.println(F(" brown out reset"));
    if( mcusr & _BV(EXTRF) ) Serial.println(F(" external reset"));
    if( mcusr & _BV(PORF) )  Serial.println(F(" power on reset"));

    //Recover the I2C bus before touching Wire, otherwise display.begin() can block for ever
    i2cBusClear();
    Wire.begin();
    //Without this the Wire library busy waits with no timeout, so one stuck slave hangs the sketch for
    //ever. Needs Arduino AVR core 1.8.4 or later, which is where setWireTimeout() was added
    Wire.setWireTimeout(25000, true);   //25ms, and reset the TWI hardware on a timeout

    // initialize the OLED object

    g_displayOk = display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS);
    if(!g_displayOk)
    {
        //Do not touch display after this. The 512 byte framebuffer is malloc'd, so on a failure it is
        //NULL and clearDisplay() would memset through address 0, over the whole AVR I/O register space
        Serial.println("OLED begin failed");
    }
    else
    {
        display.setRotation(2); //upside down
        display.setTextSize(1);
        display.setFont(&FreeSans12pt7b);
        display.setTextColor(WHITE);
        display.ssd1306_command(SSD1306_SETCONTRAST);
        display.ssd1306_command(1);  //set the contrast to the lowest possible. Still seems quite bright in the dark
        display.clearDisplay();
    }

	wdt_reset();

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

	wdt_reset();

	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
		Serial.println("rf69 setFrequency failed");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(BASE_JEENODE);    //doesn't matter which node as we don't transmit
    //setIdleMode(RH_RF69_OPMODE_MODE_SLEEP) is deliberately not used. Waking from sleep makes every
    //available() call wait on MODEREADY while the radio's crystal restarts, and RH_RF69::setOpMode()
    //spins on that flag with no timeout. This node is not battery powered, so idle in standby instead
	Serial.print(F("RF69 initialised Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println("MHz");


    uint8_t displayMode = readEEPROM(0);
    if (displayMode >= eFirstDisplayMode && displayMode <= eLastDisplayMode)
    {
        g_displayMode = (ButtonDisplayMode)displayMode;
    }
    else
    {
        g_displayMode = eFirstDisplayMode;
    }
#ifdef HOUSE_BANNER
    // EmonSerial::PrintGPSPayload(NULL);
    // EmonSerial::PrintTemperaturePayload(NULL);
    // EmonSerial::PrintPulsePayload(NULL);
	// EmonSerial::PrintBatteryPayload(NULL);
    // EmonSerial::PrintInverterPayload(NULL);

    //memset( &g_payloadGPS,0, sizeof(PayloadGPS));
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

	wdt_reset();

    //initialize LED strip
    strip.Begin();
    strip.Show();

    //initialise PWM timers for tachometer output
    InitTimersSafe();
    setTachometerOff();     //leave the output high impedance until there is something to display

    digitalWrite(LED_PIN, LOW);
}



void loop()
{
    const unsigned long DISPLAY_UPDATE_INTERVAL_MS = 250;
    const unsigned long DISPLAYMODE_PERIOD_MS = 2000;
    const unsigned long PROXIMITY_INTERVAL_MS = 50;
    const unsigned long EEPROM_COMMIT_DELAY_MS = 5000;
    const uint8_t PROXIMITY_DEBOUNCE_COUNT = 3;
    static unsigned long lastDisplayUpdateTime = millis();
    static unsigned long lastDisplayModeChangeTime = millis();
    static unsigned long lastProximityTime = millis();
    static RgbwColor ledColor = RgbwColor(0, 0, 0, 255);

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
            // if (node_id == GPS_NODE && len == sizeof(PayloadGPS))
            // {
            //     g_payloadGPS = *(PayloadGPS*)buf;							// get payload data
            //     EmonSerial::PrintGPSPayload(&g_payloadGPS);				// print data to serial
            // }
            // else
             if (node_id == PULSE_JEENODE && len == sizeof(PayloadPulse)) // === PULSE NODE ====
            {
                g_payloadPulse = *(PayloadPulse*)buf;							// get payload data
                g_lastPayloadPulseTime = millis();

                PAYLOAD_DEBUG(EmonSerial::PrintPulsePayload(&g_payloadPulse));
            }
            else if ( node_id == BATTERY_NODE && len == sizeof(PayloadBattery))						// jeenode base Receives the time
            {
                PayloadBattery payloadBattery = *((PayloadBattery*)buf);
                if( payloadBattery.crc == EmonSerial::CalcCrc(buf, sizeof(PayloadBattery)-2) && payloadBattery.subnode == 0 )
                {
                    //we only get the voltage from battery node 0
                    g_payloadBattery = *((PayloadBattery*)buf);
                    g_lastPayloadBatteryTime = millis();
                    PAYLOAD_DEBUG(EmonSerial::PrintBatteryPayload(&g_payloadBattery));
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
                g_lastPayloadInverterTime = millis();
                PAYLOAD_DEBUG(EmonSerial::PrintInverterPayload(&g_payloadInverter[subnode]));			 // print data to serial
            }
            else if( node_id == TEMPERATURE_JEENODE && len == sizeof(PayloadTemperature)) // === TEMPERATURE NODE ====
            {
                g_payloadTemperature = *(PayloadTemperature*)buf;							// get payload data
                g_lastPayloadTemperatureTime = millis();
                PAYLOAD_DEBUG(EmonSerial::PrintTemperaturePayload(&g_payloadTemperature));				// print data to serial
            }
#elif defined(BOAT_BANNER)
            if (node_id == GPS_NODE && len == sizeof(PayloadGPS))
            {
                PayloadGPS payloadGPS = *(PayloadGPS*)buf;
                if(payloadGPS.subnode == 0)
                {
                    g_payloadGPS = *(PayloadGPS*)buf;
                    g_lastPayloadGPSTime = millis();
                    PAYLOAD_DEBUG(EmonSerial::PrintGPSPayload(&g_payloadGPS));
                }
            }
			else if (node_id == DALY_BMS_NODE  && (len == sizeof(PayloadDalyBMS)-2 || len == sizeof(PayloadDalyBMS)) )		//some Daly BMS don't send the crc
			{
                g_payloadDalyBMS = *(PayloadDalyBMS*)buf;
                g_lastPayloadDalyBMSTime = millis();
                PAYLOAD_DEBUG(EmonSerial::PrintDalyBMSPayload(&g_payloadDalyBMS));
			}
            else if ( node_id == SEVCON_CAN_NODE && len == sizeof(PayloadSevCon))
            {
                g_payloadSevCon = *(PayloadSevCon*)buf;
                g_lastPayloadSevConTime = millis();
                PAYLOAD_DEBUG(EmonSerial::PrintSevConPayload(&g_payloadSevCon));
            }
            else if ( node_id == ANEMOMETER_NODE && len == sizeof(PayloadAnemometer))
            {
                PayloadAnemometer payloadAnemometer = *(PayloadAnemometer*)buf;
                if( payloadAnemometer.subnode == 2) //True wind is published on node 2
                {    
                    g_payloadAnemometer = *(PayloadAnemometer*)buf;
                    g_lastPayloadAnemometerTime = millis();
                    PAYLOAD_DEBUG(EmonSerial::PrintAnemometerPayload(&g_payloadAnemometer));
                }
            }
#endif
        }
        //digitalWrite(LED_PIN, LOW);
    }

    //Sample the proximity sensor on its own tick rather than on every pass through loop(). Each read is
    //an I2C transaction, and the Wire library will hang if the bus ever sticks
    static bool proximityOn = false;
    static uint8_t proximityDebounceCount = 0;
    static bool displayModePending = false;
    if( millis() - lastProximityTime > PROXIMITY_INTERVAL_MS )
    {
        lastProximityTime = millis();

        bool proximity = getProximityOn(proximityOn);
        if( proximity != proximityOn )
        {
            //require several consecutive samples so a noisy reading cannot step through the modes
            if( ++proximityDebounceCount >= PROXIMITY_DEBOUNCE_COUNT )
            {
                proximityDebounceCount = 0;
                proximityOn = proximity;
                if( proximityOn ) //was off, now on
                {
                    digitalWrite(LED_PIN, HIGH);
                    if( g_displayMode == eLastDisplayMode)
                        g_displayMode = eFirstDisplayMode;
                    else
                        g_displayMode = (ButtonDisplayMode)((int)g_displayMode + 1);
                    lastDisplayModeChangeTime = millis();
                    displayModePending = true;  //saved to EEPROM once the mode has settled
                }
                else
                {
                    digitalWrite(LED_PIN, LOW);
                }
            }
        }
        else
        {
            proximityDebounceCount = 0;
        }
    }

    //Save the display mode to EEPROM so it is retained after power loss, but only once it has stopped
    //changing. EEPROM cells are only good for 100,000 writes and EEPROM.write() blocks for ~3.4ms
    if( displayModePending && millis() - lastDisplayModeChangeTime > EEPROM_COMMIT_DELAY_MS )
    {
        displayModePending = false;
        if( readEEPROM(0) != (uint8_t)g_displayMode )
            writeEEPROM(0, (uint8_t)g_displayMode);
    }


    if( millis() - lastDisplayUpdateTime > DISPLAY_UPDATE_INTERVAL_MS )
    {
        lastDisplayUpdateTime = millis();

        if( g_displayOk )
        {
            //centre the text to the OLED display
            uint8_t textOffset = (millis() - lastDisplayModeChangeTime) > DISPLAYMODE_PERIOD_MS;
            int16_t x1, y1, w, h;
            display.getTextBounds(g_displayModeNames[g_displayMode][textOffset], 0, SCREEN_HEIGHT, &x1, &y1, &w, &h);
            display.clearDisplay();
            display.setCursor((SCREEN_WIDTH-w)/2,SCREEN_HEIGHT - ((SCREEN_HEIGHT-h)/2));
            display.print(g_displayModeNames[g_displayMode][textOffset]);
            display.display();
        }

        switch(g_displayMode)
        {
#ifdef HOUSE_BANNER
            case eCurrentPower:
                if (millis() - g_lastPayloadPulseTime > PACKET_TIMEOUT_MS)
                    setTachometerOff();
                else
                    setTachometer((float)(g_payloadPulse.power[2]/2500.0));
                ledColor = RgbwColor(0,0,0,255); // white, from the strip's W element
                break;
            case eCurrentTemperatures:
                if (millis() - g_lastPayloadTemperatureTime > PACKET_TIMEOUT_MS)
                    setTachometerOff();
                else
                    setTachometer((float)(g_payloadTemperature.temperature[0]/100.0/25.0));
                ledColor = RgbwColor(255,0,0,0); // red
                break;
            case eRailVoltage:
                if (millis() - g_lastPayloadBatteryTime > PACKET_TIMEOUT_MS)
                    setTachometerOff();
                else
                    setTachometer((float)(g_payloadBattery.voltage[0]/100.0/100.0));
                ledColor = RgbwColor(0,255,255,0); // cyan
                break;
            case eInverterIn:
                {
                    if (millis() - g_lastPayloadInverterTime > PACKET_TIMEOUT_MS)
                        setTachometerOff();
                    else
                    {
                        unsigned short inverterIn = 0;
                        for(int i=0; i<MAX_INVERTERS;i++)
                        {
                            inverterIn += g_payloadInverter[i].pvInputPower;
                        }
                        setTachometer((float)(inverterIn/2500.0));
                    }
                    ledColor = RgbwColor(0,255,0,0); // green
                }
                break;
            // case eGPSSpeed:
            //     setTachometer(g_payloadGPS.speed/10.0);
            //     ledColor = RgbwColor(0,0,255,0); // blue
            //     break;

#elif defined(BOAT_BANNER)
            case eRPM:
                if (millis() - g_lastPayloadSevConTime > PACKET_TIMEOUT_MS)
                    setTachometerOff();
                else
                    setTachometer(fabs((float)(g_payloadSevCon.rpm/2500.0))); //engin RPM
                ledColor = RgbwColor(0,0,0,255); // white, from the strip's W element
                break;
            case eWindSpeed:
                if (millis() - g_lastPayloadAnemometerTime > PACKET_TIMEOUT_MS)
                    setTachometerOff();
                else
                    setTachometer(g_payloadAnemometer.windSpeed/25.0);  //speed in knots
                ledColor = RgbwColor(0,255,0,0); // green
                break;
            case eGPSSpeed:
                if (millis() - g_lastPayloadGPSTime > PACKET_TIMEOUT_MS)
                    setTachometerOff();
                else
                    setTachometer(g_payloadGPS.speed/25.0);             //speed in knots
                ledColor = RgbwColor(0,0,255,0); // blue
                break;
            case eBatterySoC:
                if (millis() - g_lastPayloadDalyBMSTime > PACKET_TIMEOUT_MS)
                    setTachometerOff();
                else
                    setTachometer((float)(g_payloadDalyBMS.batterySoC/1000.0)); //SoC is in 0.1% units
                ledColor = RgbwColor(255,0,0,0); // red
                break;
#endif
        }

        //do the lighting based on ambient light and whether the external instrument lights are switched on
        //Kept on the display tick. Every ambient light read is an I2C transaction, and strip.Show() holds
        //interrupts off for ~520us, which delays the radio and I2C interrupts if it is called flat out
        uint8_t intensity = LED_INSTRUMENT_INTENSITY;
        if( digitalRead(INSTRUMENT_LIGHT_PIN) != HIGH )
        {
            // Get the intensity of the ambient light. Keep the last good value if the read fails
            float lux = 0.0;
            if( apds.readAmbientLightLux(lux) && !isnan(lux) )
                g_ambientLight = lux;
            //clamp before the cast to long. constrain() passes NaN and out of range floats straight through
            if( g_ambientLight < 0.0 )
                g_ambientLight = 0.0;
            if( g_ambientLight > 255.0 )
                g_ambientLight = 255.0;
            intensity = map((long)g_ambientLight, 0, 255, LED_MIN_INTENSITY, LED_MAX_INTENSITY);
            //Serial.print(g_ambientLight);Serial.print(",");Serial.println(intensity);
        }
        setLedStrip(ledColor, intensity ); // adjust brightness based on ambient light
    }

    return;
}
