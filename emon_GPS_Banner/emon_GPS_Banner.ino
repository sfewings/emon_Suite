#include <Time.h>

/*--------------------------- Libraries ----------------------------------*/
//#define GPS_EMBEDDED
#undef GPS_EMBEDDED

#ifdef GPS_EMBEDDED

    #include <AltSoftSerial.h>
    //#include <SoftwareSerial.h>           // Allows PMS to avoid the USB serial port
    #include <TinyNMEA.h>

    #include <SPI.h>
    //#include <avr/wdt.h>
    #include <TimeLib.h>
    #include <BME280I2C.h>
    #include <Wire.h>

    #define     GPS_RX_PIN              8               // Rx from GPS (== GPS Tx)
    #define     GPS_TX_PIN              9               // Tx to GPS (== GPS Rx)
    #define     GPS_BAUD_RATE         9600              // GPS uses 9600bps

    // Software serial port
    //SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);
    AltSoftSerial gpsSerial;  //pin 8 and 9

    BME280I2C bme;    // Default : forced mode, standby time = 1000 ms
                    // Oversampling = pressure ×1, temperature ×1, humidity ×1, filter off,
    TinyNMEA gpsNMEA;
#else

    //#define HOUSE_BANNER
    #undef HOUSE_BANNER
    #ifdef HOUSE_BANNER
        #define NETWORK_FREQUENCY 915.0
    #else // BOAT_BANNER
        #define NETWORK_FREQUENCY 914.0
    #endif

    #include <EmonShared.h>

    #include <SPI.h>
    #include <RH_RF69.h>
    #include <OneWire.h>
    #include <DallasTemperature.h>

    RH_RF69 g_rf69;

    PayloadGPS          g_payloadGPS;
    PayloadTemperature  g_payloadTemperature;
    PayloadBase         g_payloadBase;
    PayloadPulse        g_payloadPulse;
    PayloadRain         g_payloadRain;
    PayloadBattery      g_payloadBattery;
    PayloadPressure     g_payloadPressure;

    OneWire oneWire(4); //Pin 4
    DallasTemperature temperatureSensor(&oneWire);

    time_t	g_startTime = 0;
    int    g_currentDay = 0;
    unsigned long g_rainStartOfToday = 0;
    
    const uint8_t VOLTAGE_MEASURE_PIN = A5;

    const uint8_t LDR_MOVING_AVERAGE_WINDOWN_SIZE = 20; 
    uint8_t g_LDR_movingAverage[LDR_MOVING_AVERAGE_WINDOWN_SIZE];
    uint8_t g_LDR_movingAverage_index = 0;

#endif


#include <NeoPixelBus.h>
#include <PinChangeInt.h>

#include <EEPROM.h>
#include <util/crc16.h>
#include <util/parity.h>



#include "font_6x8.h"

/////////////////////////////////////////
#define     LED                     13              // Built-in LED pin


enum eDisplayType { eAutoRotate = 0,
                    eTime, 
                    eTemp, 
                    ePressure, 
                    eSpeed, 
                    eHeading,
                    eEndDisplayType
                };

enum eDisplayMode { eOff = 0,
                    eText, 
                    eEightLight,
                    eQuarterLight,
                    eHalfLight, 
                    eFullLight,
                    eEndDisplayMode
                };

typedef struct {
  unsigned long pinDownTime;
  bool pinDown;
  bool settingMode;
  unsigned long settingModeTimeout;
} SettingMode;

//Setting stored to EEPROM
//EEPROM settings stored for an individual node.
const uint8_t EEPROM_SETTINGS_BASE = 100;
const uint8_t EEPROM_VERSION = 1;     
typedef struct {
    uint8_t version;
    uint8_t gmtOffsetHours;
    uint8_t displayType;
    uint8_t displayMode;
	word crc;						//crc checksum.
} EEPROMConfig;

const char displayTypeName[][eDisplayType::eEndDisplayType] PROGMEM = 
{
    "All", "Time", "Temp", "Press", "Speed", "COG" 
};

const RgbColor displayTypeColor[eDisplayType::eEndDisplayType] = 
{ 
    RgbColor(128,128,128),      // eAutoRotate  Grey
    RgbColor(255,0,255),        // eTime        cyan
    RgbColor(255,0,0),          // eTemp        red
    RgbColor(0,255,0),          // ePressure    green
    RgbColor(0,0,255),          // eSpeed       blue
    RgbColor(255,255,0)         // eHeading     yellow
};

const uint8_t LDR_PIN = A0;
const uint8_t PIXEL_PIN = 3;
const uint8_t LED_PIN = A3;  //Pin 17
const uint8_t NUM_BUTTONS = 2;
const uint8_t  g_buttons[NUM_BUTTONS] = { A1, A2 };	//pin number for each input A1, A2.  Pins 15 & 16
const uint16_t NUM_PIXELS = 256;

volatile unsigned long	g_lastButtonPush[NUM_BUTTONS]	= { 0,0 };
volatile unsigned long	g_changeDisplayTypePushTime = 0;
volatile bool g_configChanged = false;
volatile SettingMode g_settingTime = { 0, false, false, 0 };
volatile SettingMode g_settingLight = { 0, false, false, 0 };

EEPROMConfig g_config = {0,0,0,0};


float g_course = 0;
float g_speed = 0;
float g_pressure = 0;
float g_temperature = 0;
float g_humidity = 0;
bool g_clockSet = false;

//storing the last 4 hours of pressures
const int PRESURE_UPDATE_PERIOD = 5000; //ms
const uint8_t PRESSURE_HISORY_SIZE = 4;
float g_pressureHistory[PRESSURE_HISORY_SIZE];
int8_t g_pressureHistoryIndex = 0;
int g_thisHour;


NeoPixelBus<NeoGrbFeature, Neo800KbpsMethod> strip(NUM_PIXELS,PIXEL_PIN);

extern char *__brkval;

int freeMemory()
{
  char top;
  return &top - __brkval;
}

// routine called when external interrupt is triggered
void interruptHandlerIR() 
{
    /* Pin to interrupt map, ATmega328:
    * D0-D7 = PCINT 16-23 = PCIR2 = PD = PCIE2 = pcmsk2
    * D8-D13 = PCINT 0-5 = PCIR0 = PB = PCIE0 = pcmsk0
    * A0-A5 (D14-D19) = PCINT 8-13 = PCIR1 = PC = PCIE1 = pcmsk1
    */

    uint8_t button = 0;
    while(g_buttons[button] != PCintPort::arduinoPin)
    {
        if( ++button == NUM_BUTTONS)
            return;		// we only support 2 buttons though we could get an interrupt for more!
    }


    if( PCintPort::pinState == HIGH)
    {
        unsigned long msSinceLastButton = millis()- g_lastButtonPush[button];
        g_lastButtonPush[button] = millis();

        if(msSinceLastButton <20)
            return;     //button debounce
    }

    if( button == 1 && PCintPort::pinState == HIGH )
    {
        g_config.displayMode = ( (g_config.displayMode+1) % eDisplayMode::eEndDisplayMode);
        g_configChanged = true;
    }

    if( button == 0)
    {
        bool incDisplayType=false;
        if( PCintPort::pinState == HIGH )
        {
            if(g_config.displayType == eDisplayType::eTime )
            {
                if( g_settingTime.settingMode )
                {
                    //increment the hour on a button down while setting time
                    g_config.gmtOffsetHours = (g_config.gmtOffsetHours+1)%12;   //we only do a 12 hour clock!
                    g_settingTime.settingModeTimeout = millis();    //reset on each button press
                    g_configChanged = true;
                }
                else
                {
                    //start the timer for holding hte button down to setTime mode
                    g_settingTime.pinDownTime = millis();
                    g_settingTime.pinDown = true;
                }
            }
            else
            {
                incDisplayType = true;
            }
        }
        else //LOW
        {
            if(g_config.displayType == eDisplayType::eTime && !g_settingTime.settingMode &&  millis() - g_settingTime.pinDownTime <1000)
                 incDisplayType = true;
            //stop any chance of moving into setTime mode
            g_settingTime.pinDown = false;
        }

        if( incDisplayType )
        {
            if(g_config.displayMode == eDisplayMode::eOff)
                g_config.displayMode++; //turn the unit on when either button is pressed!
            else
                g_config.displayType = ((g_config.displayType+1)% eDisplayType::eEndDisplayType);
            g_configChanged = true;
            g_changeDisplayTypePushTime = millis();
        }
    }
}

word CalcCrc(const void* ptr, byte len)
{
	word crc = ~0;
	for (byte i = 0; i < len; ++i)
		crc = _crc16_update(crc, ((const byte*)ptr)[i]);
	return crc;
}

bool ReadEEPROMSettings(EEPROMConfig& config)
{
	char* pc = (char*)& config;

	for (long l = 0; l < sizeof(config); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_SETTINGS_BASE + l);
	}
	if (config.crc != CalcCrc(&config, sizeof(config) - 2))
	{
		//no config. Set to defaults
		memset(&config, 0, sizeof(config));
        config.version = EEPROM_VERSION;
        config.displayType = eDisplayType::eAutoRotate;
        config.gmtOffsetHours = 8;      //default to AWST (Perth) offset
		return 0;
	}
	if (config.version != EEPROM_VERSION)
	{
		//todo: deal with version conversion when required
	}

	return config.version;
}

void WriteEEPROMSettings(EEPROMConfig & config)
{
	char* pc = (char*)& config;
	config.version = EEPROM_VERSION;
	config.crc = CalcCrc(&config, sizeof(config) - 2);

	for (long l = 0; l < sizeof(config); l++)
	{
		EEPROM.write(EEPROM_SETTINGS_BASE + l, *(pc + l));
	}

#ifndef ARDUINO_ARCH_AVR
	EEPROM.commit();
#endif
}


uint8_t  readLDR()
{
    //note the moving average contrast timing depends on readLDR() being read at regular intervals
    const int NUM_LOOPS = 10;
    long l = 0;
    for(int i=0; i <NUM_LOOPS; i++)
        l += analogRead( LDR_PIN );
    float value = l/NUM_LOOPS;
    uint8_t intensity = 1+(uint8_t) sqrt(62.5*value);
    //Serial.print(value);Serial.print(", ");Serial.println(intensity);
    g_LDR_movingAverage[g_LDR_movingAverage_index] = intensity;
    g_LDR_movingAverage_index = (g_LDR_movingAverage_index +1 ) % LDR_MOVING_AVERAGE_WINDOWN_SIZE;
    uint16_t sum = 0;
    for(int i=0; i<LDR_MOVING_AVERAGE_WINDOWN_SIZE; i++)
        sum+=g_LDR_movingAverage[i];

    return (uint8_t) (sum/LDR_MOVING_AVERAGE_WINDOWN_SIZE);
}

uint8_t GetCharIntensity()
{
    switch( g_config.displayMode)
    {
        case eDisplayMode::eOff:
            return 0;
        case eDisplayMode::eEightLight:
            return 2;
        case eDisplayMode::eQuarterLight:
            return 4;
        case eDisplayMode::eHalfLight:
            return 32;
        case eDisplayMode::eFullLight:
            return 255;
        case eDisplayMode::eText:
            return readLDR();
    }
}


RgbColor GetBackgroundColour()
{
    switch( g_config.displayMode)
    {
        case eDisplayMode::eEightLight:
            return RgbColor(2, 2, 2);
        case eDisplayMode::eQuarterLight:
            return RgbColor(4, 4, 4);
        case eDisplayMode::eHalfLight:
            return RgbColor(32, 32, 32);
        case eDisplayMode::eFullLight:
            return RgbColor(255, 255, 255);
        case eDisplayMode::eOff:    //note: We shouldn't get here if "off"!
        case eDisplayMode::eText:
        default:
            return RgbColor(0, 0, 0);
    }
}

void clearBanner()
{
    RgbColor colour = GetBackgroundColour();
    for(uint16_t pixel=0; pixel <NUM_PIXELS; pixel++)
    {
        strip.SetPixelColor(pixel, colour);
    }
}

short charWidth(char ch)
{
    if( ch == ' ')
        return 1;   //special case. Make a space 1 chars wide
   
    //OR all the rows of the char into columnsUsed
    unsigned char columnsUsed = 0;
    unsigned char fontRowBits;
    for(int i=0; i < 8;i++)
    {
        memcpy_P(&fontRowBits, &console_font_6x8[ (int) ch*8+i ], sizeof(unsigned char));
        columnsUsed |= fontRowBits>>2; //the right two bits are not used in a font 6 wide
    }

    //count the columns backwards for the char until we reach a "1"
    short width;
    for(width=6; width>=0; width--)
    {
        if(columnsUsed & 1<<width)
            break;
    }
    return width + 1;
}

short bannerChar(char ch, int offset, RgbColor colour)
{
    RgbColor onColour = colour;
    RgbColor offColour = GetBackgroundColour();

    //Serial.print(F("char="));Serial.print(ch);
    //Serial.print(F(","));Serial.print(offset);

    for(int i=0; i < 7;i++) //each row of the font. We ignore the bottom row!
    {
        unsigned char fontRowBits;
        int fontOffset = (int) ch*8+i;
        memcpy_P(&fontRowBits, &console_font_6x8[fontOffset], sizeof(unsigned char));
        fontRowBits = fontRowBits>>2;   //the right two bits are not used in a font 6 wide
        //Serial.print(F(","));Serial.print(fontOffset);
        //Serial.print(F(","));Serial.print(fontRowBits,BIN);

        for(int b=0; b<6;b++)       //each bit (column) of the row
        {
            RgbColor pixelColour = (fontRowBits & (1<<b) ? onColour: offColour);
            int ledColumn = offset-b;
            int ledIndex = ledColumn*8 + (ledColumn%2==0?i+1:(7-i-1)); //+1,-1 to more the font down 1 row
            if( ledIndex >= 0 && ledIndex < NUM_PIXELS )
            {
                strip.SetPixelColor(ledIndex, pixelColour);
            }
        }
    }
    short width = charWidth(ch);
    //Serial.print(F(",")); Serial.println(width);

    return width;
}

short bannerDigit(uint8_t digit, int offset, RgbColor colour)
{
    return bannerChar('0'+digit, offset, colour);
}

void printString(char* str, RgbColor inColour, uint8_t intensity = 255, short offset = -1)
{
    clearBanner();
    if( g_config.displayMode != eDisplayMode::eOff)
    {
        RgbColor colour = RgbColor(inColour.R*intensity/255,inColour.G*intensity/255,inColour.B*intensity/255);

        if(offset == -1)        //center text on banner
        {
            short width = 0;
            for(int i=0; i< strlen(str); i++)
            {
                width += charWidth(str[i]);
                width += 1;
            }
            offset = 16 + width/2 - 1;

            // Serial.print(F("str,l,w,o="));
            // Serial.print(str);
            // Serial.print(F(","));
            // Serial.print(strlen(str));
            // Serial.print(F(","));
            // Serial.print(width);
            // Serial.print(F(","));
            // Serial.println(offset);

        }
        for(short i=strlen(str)-1;i>=0; i--)
        {
            offset -= bannerChar(str[i], offset, colour);
            offset -= 1;
        }
    }    
    strip.Show();
}

char* my_dtostrf(float val, signed char width, unsigned char prec, char* str)
{
    dtostrf( val, width, prec, str );
    //assume width is -ve. i.e. strip from end
    for(signed char i=(-1*width)-1;i>=0;i--)
    {
        if(str[i]==' ' || str[i]=='\0')
            str[i] = '\0';
        else
            break;
    }
    return str;
}

void Blink(byte PIN, byte DELAY_MS, byte loops) 
{
  for (byte i=0; i<loops; i++)  
  {
    digitalWrite(PIN,HIGH);
    delay(DELAY_MS);
    digitalWrite(PIN,LOW);
    delay(DELAY_MS);
  }
}
#ifdef GPS_EMBEDDED

    void SelectSentences(bool RMC, bool GGA, bool GSA, bool GLL, bool VTG, bool GSV)
    {
        // See http://cdn.sparkfun.com/datasheets/Sensors/GPS/760.pdf
        // Also https://www.roboticboat.uk/Microcontrollers/Uno/GPS-PAM7Q/GPS-PAM7Q.html for enable/disable NMEA strings

        // NMEA_GLL output interval - Geographic Position - Latitude longitude
        // NMEA_RMC output interval - Recommended Minimum Specific GNSS Sentence
        // NMEA_VTG output interval - Course Over Ground and Ground Speed
        // NMEA_GGA output interval - GPS Fix Data
        // NMEA_GSA output interval - GNSS DOPS and Active Satellites
        // NMEA_GSV output interval - GNSS Satellites in View

        if( RMC )
            gpsSerial.println(F("$PUBX,40,RMC,0,1,0,0*46"));
        else
            gpsSerial.println(F("$PUBX,40,RMC,0,0,0,0*47"));
        delay(100);

        if( GGA )
            gpsSerial.println(F("$PUBX,40,GGA,0,1,0,0*5B"));
        else
            gpsSerial.println(F("$PUBX,40,GGA,0,0,0,0*5A"));
        delay(100);

        if( GLL )
            gpsSerial.println(F("$PUBX,40,GLL,0,1,0,0*5D"));
        else
            gpsSerial.println(F("$PUBX,40,GLL,0,0,0,0*5C"));
        delay(100);

        if( VTG )
            gpsSerial.println(F("$PUBX,40,VTG,0,1,0,0*5F"));
        else
            gpsSerial.println(F("$PUBX,40,VTG,0,0,0,0*5E"));
        delay(100);

        if( GSA )
            gpsSerial.println(F("$PUBX,40,GSA,0,1,0,0*4F"));
        else
            gpsSerial.println(F("$PUBX,40,GSA,0,0,0,0*4E"));
        delay(100);  

        if( GSV )
            gpsSerial.println(F("$PUBX,40,GSV,0,5,0,0*5C"));
        else
            gpsSerial.println(F("$PUBX,40,GSV,0,0,0,0*59"));
        delay(100);
    
    }
#else
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
#endif

void SetPressureHistory(float pressure)
{
    if( g_clockSet )
    {
        g_pressureHistory[g_pressureHistoryIndex] = pressure;
        if(g_thisHour != hour())
        {
            //Every hour, move the index along 1
            g_pressureHistoryIndex = (g_pressureHistoryIndex+1)% PRESSURE_HISORY_SIZE;
            
            //initialise 4 hour history of readings with the current reading.
            // For the first 4 hours of operation, the change will be relative to the power-on time
            for(int i=0; i<PRESSURE_HISORY_SIZE;i++)
            {
                if(g_pressureHistory[i] == __FLT_MAX__ )
                {
                    g_pressureHistory[i] = pressure;
                }
            }
            g_thisHour = hour();
        }
        // else //for testing
        // {
        //     static bool toggleTestPressure = true;
        //     if( fabs(g_pressure - g_pressureHistory[(g_pressureHistoryIndex+1)% PRESSURE_HISORY_SIZE]) > 4 )
        //         toggleTestPressure = !toggleTestPressure;
        //     if( toggleTestPressure )
        //         g_pressureHistory[(g_pressureHistoryIndex+1)% PRESSURE_HISORY_SIZE] -= 1.0;
        //     else
        //         g_pressureHistory[(g_pressureHistoryIndex+1)% PRESSURE_HISORY_SIZE] += 1.0;
        //     Serial.print(F("LastPressure="));
        //     Serial.println(g_pressureHistory[(g_pressureHistoryIndex+1)% PRESSURE_HISORY_SIZE],1);
        // }
    }
}


void setup()
{
    pinMode(LED, OUTPUT);    
    Blink(LED, 50, 3);

    pinMode( LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);


    Serial.begin(9600); 
    Serial.println(F("GPS sketch"));

    ReadEEPROMSettings( g_config );
    
    Serial.print(F("EEPROM version="));
    Serial.print(g_config.version);
    Serial.print(F(",DisplayType="));
    Serial.print( g_config.displayType);
    Serial.print(F(",DisplayMode="));
    Serial.print( g_config.displayMode);
    Serial.print(F(",GMT offset="));
    Serial.print( g_config.gmtOffsetHours);
    Serial.println();

#ifdef GPS_EMBEDDED
    //Note: To reduce the RAM used, change TX_BUFFER_SIZE from 68 to 32 in AltSoftSerial.cpp
    gpsSerial.begin(GPS_BAUD_RATE);
    delay(100);
    SelectSentences(true, false, false, false, false, false);

    Wire.begin();

    if(bme.begin())
    switch(bme.chipModel())
    {
      case BME280::ChipModel_BME280:
        Serial.println(F("Found BME280 sensor! Success."));
        break;
      case BME280::ChipModel_BMP280:
        Serial.println(F("Found BMP280 sensor! No Humidity available."));
        break;
      default:
        Serial.println(F("Found UNKNOWN sensor! Error!"));
    }
    else
    {
      Serial.println(F("Could not find BME280 sensor!"));
    }
#else
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

	Serial.print("RF69 initialise node: ");
	Serial.print(TEMPERATURE_JEENODE);
	Serial.print(" Freq: ");Serial.print(NETWORK_FREQUENCY,1); Serial.println("MHz");

    memset( &g_payloadGPS,0, sizeof(PayloadGPS));
    memset( &g_payloadTemperature,0, sizeof(PayloadTemperature));
    memset( &g_payloadBase,0, sizeof(PayloadBase));
    memset( &g_payloadPulse,0, sizeof(PayloadPulse));
    memset( &g_payloadRain,0, sizeof(PayloadRain));
    memset( &g_payloadBattery,0, sizeof(PayloadBattery));
    memset( &g_payloadPressure,0, sizeof(PayloadPressure));


	EmonSerial::PrintGPSPayload(NULL);
    EmonSerial::PrintBasePayload(NULL);
    EmonSerial::PrintRainPayload(NULL);
	EmonSerial::PrintBatteryPayload(NULL);
	EmonSerial::PrintTemperaturePayload(NULL);
	EmonSerial::PrintPressurePayload(NULL);

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
#endif

    strip.Begin();
    for(uint16_t ui=0; ui<NUM_PIXELS; ui++)
        strip.SetPixelColor(ui, RgbColor(0,0,0));
    strip.Show();

    for(uint8_t button = 0; button < NUM_BUTTONS; button++)
    {
        attachPinChangeInterrupt(g_buttons[button], interruptHandlerIR, CHANGE);
    }

    //initialise pressure history
    for(int i=0; i<PRESSURE_HISORY_SIZE;i++)
        g_pressureHistory[i] = __FLT_MAX__;
    g_thisHour = -1;
    g_pressureHistoryIndex = 0;

    //initialise the LDR history to 0
    for(int i=0; i<LDR_MOVING_AVERAGE_WINDOWN_SIZE; i++)
        g_LDR_movingAverage[i] = 0;


    Serial.println("Exit setup()");
}



void loop()
{    
    //reset the watchdog timer
    //wdt_reset();
    #define BUF_SIZE 8
    static char chVal[BUF_SIZE];
    static char str[BUF_SIZE];
    static uint32_t lastSendPressureTime = millis() - PRESURE_UPDATE_PERIOD;
    static int displayToggle = eDisplayType::eTemp;
    static unsigned long displayRotateTime = millis();
    char ch;

    //deal with the time setting mode. 
    //  Hold button down for 3000 ms to enter into mode
    //  Move out of mode if no button pressed for 10 seconds
    if( g_settingTime.pinDown && millis() - g_settingTime.pinDownTime > 3000 && !g_settingTime.settingMode)
    {
        //move into the setTime mode
        g_settingTime.settingMode = true;
        g_settingTime.settingModeTimeout = millis();
        //Serial.println(F("Setting time"));
    }
    if(g_settingTime.settingMode && millis() - g_settingTime.settingModeTimeout >10000)
    {
        //move out of setTime mode after 10 seconds without a button press
        g_settingTime.settingMode = false;
        //Serial.println(F("Finished setting time"));
    }


#ifdef GPS_EMBEDDED
    //read GPS if not setting time && not recently pressed the changedisplayType button
    if( !g_settingTime.settingMode && millis() - g_changeDisplayTypePushTime > 2000)
    {
        // Need to wait for the buffer to fill. Neopixel and Serial read both use the 16bit timer 
        // and serial buffer corrupts if the Neopixel writes while serial receives.
        //delay 950 should do it!
        delay(950);
        
        while (gpsSerial.available())
        {
            ch = gpsSerial.read();
            Serial.print(ch); // uncomment this line if you want to see the GPS data flowing
        
            if (gpsNMEA.encode(ch)) // Did a new valid sentence come in?
            {
                digitalWrite(LED_PIN,HIGH);
                unsigned long age;
                int Year;
                byte Month, Day, Hour, Minute, Second;
        
                gpsNMEA.crack_datetime(&Year, &Month, &Day, &Hour, &Minute, &Second, NULL, &age);
                if (age < 1000) 
                {
                    // set the Time to the latest GPS reading
                    setTime(Hour, Minute, Second, Day, Month, Year);
                    g_clockSet = true;
                }

                //gpsNMEA.f_get_position(&g_latitude, &g_longitude, &age);
                g_speed = gpsNMEA.f_speed_knots();
                g_course = gpsNMEA.f_course();
            }
        }
    }

    if( millis() - lastSendPressureTime > PRESURE_UPDATE_PERIOD )
    {
        digitalWrite(LED_PIN,HIGH);
        lastSendPressureTime = millis();

        bme.read(g_pressure, g_temperature, g_humidity);

        SetPressureHistory(g_pressure);

        Serial.print(F("P,T,H="));
        Serial.print(g_pressure, 1);
        Serial.print(F(","));
        Serial.print(g_temperature, 1);
        Serial.print(F(","));
        Serial.print(g_humidity, 1);
        Serial.println();
    }
#else
	if (g_rf69.available())
	{
        Blink(LED_PIN, 1, 1);
        delay(5); //allow time for the LED blink to fade!
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
            g_speed = g_payloadGPS.speed;
            g_course = g_payloadGPS.course;
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
            g_clockSet = true;

			if (g_currentDay == -1)
			{
				//first time received from base
				g_currentDay = day();
			}
			EmonSerial::PrintBasePayload(&g_payloadBase);
		}
		if ( node_id == BATTERY_NODE && len == sizeof(PayloadBattery))						// jeenode base Receives the time
		{
			g_payloadBattery = *((PayloadBattery*)buf);
			EmonSerial::PrintBatteryPayload(&g_payloadBattery);
		}
        if ( node_id == PRESSURE_NODE && len == sizeof(PayloadPressure))
        {
            g_payloadPressure =  *((PayloadPressure*)buf);
            g_pressure = g_payloadPressure.pressure/100.0;
            SetPressureHistory(g_pressure);

            EmonSerial::PrintPressurePayload(&g_payloadPressure);
        }
    }

    static unsigned long temperatureUpdateTime = millis();
    if( millis()-temperatureUpdateTime > 60000 && g_payloadTemperature.numSensors !=0 )
	{
        //Blink(LED_PIN, 100, 2);

        temperatureUpdateTime = millis();
		//get the temperature of this unit (inside temperature)
		temperatureSensor.requestTemperatures();
        for(int i=0; i< g_payloadTemperature.numSensors; i++ )
        {
            g_temperature = temperatureSensor.getTempCByIndex(0);       //only use the last temperature. There should only be one!
		    g_payloadTemperature.temperature[i] =  g_temperature * 100; // stored as 100ths of degrees
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
	}
#endif

    if(g_configChanged)
    {
        //the button was pressed. Need to store to EEPROM
        WriteEEPROMSettings( g_config );
        g_configChanged = false;
    }

    if( g_config.displayType == eDisplayType::eAutoRotate)
    {
        if( millis() - displayRotateTime >1000 )
        {
            if( displayToggle+1 >= eDisplayType::eEndDisplayType)
                displayToggle = eDisplayType::eAutoRotate+1;
            else
                displayToggle +=1;

            displayRotateTime = millis();
        }
    }
    else
    {
        displayToggle = g_config.displayType;
    }

    // Serial.print(F("freeMemory,displayMode,displayType,displayToggle="));
    // Serial.print(freeMemory());
    // Serial.print(F(","));
    // Serial.print(g_config.displayMode);
    // Serial.print(F(","));
    // Serial.print(g_config.displayType);
    // Serial.print(F(","));
    // Serial.println(displayToggle);

    //display text of the selected mode for 2 seconds after the button was pressed
    if( millis() - g_changeDisplayTypePushTime < 2000 )
    {
        //display the reading name
        strcpy_P(str,displayTypeName[g_config.displayType]);
        printString(str,displayTypeColor[g_config.displayType], GetCharIntensity() );
    }
    else
    {
        switch( displayToggle )
        {
        case eDisplayType::ePressure:        
            ch = ' ';
            if(g_pressureHistory[(g_pressureHistoryIndex+1)%PRESSURE_HISORY_SIZE] != __FLT_MAX__ )
            {
                float pressureChange = g_pressure - g_pressureHistory[(g_pressureHistoryIndex+1)%PRESSURE_HISORY_SIZE];
                if(      pressureChange >4)
                    ch = (char) 1;  //^A
                else if( pressureChange >2)
                    ch = (char) 2; //'^B';
                else if( pressureChange >1)
                    ch = (char) 3; //'^C';
                else if( pressureChange <-4)
                    ch = (char) 7; //'^G';
                else if( pressureChange <-2)
                    ch = (char) 6; //'^F';
                else if( pressureChange <-1)
                    ch = (char) 5; //'^E';
            }
            my_dtostrf( g_pressure, -BUF_SIZE, 1, chVal );
            if( ch != ' ' && second()%2==0)
            {
                //replace the last digit with a fall/rising arrow showing the rate of change every other second
                memset(str,0,BUF_SIZE);
                strncpy(str,chVal,5);
                memset(chVal,0,BUF_SIZE);
                strncpy(chVal,str,5);
                snprintf_P(str,BUF_SIZE,PSTR("%s%c"),chVal,ch);
            }
            else
            {
                snprintf_P(str,BUF_SIZE,PSTR("%s"),chVal);
            }
            break;
        case eDisplayType::eTemp:
            my_dtostrf( g_temperature, -BUF_SIZE, 1, str );
            break;
        case eDisplayType::eSpeed:
            if( g_speed < 0.2)
            {
                my_dtostrf( 0.0, -BUF_SIZE, 2, str );
            }
            else
            {
                my_dtostrf( g_speed, -BUF_SIZE, 2, str );
            }
            break;
        case eDisplayType::eHeading:
            if( g_speed < 0.2 || g_course >=360.0)
            {
                snprintf_P(str, BUF_SIZE,PSTR("-.-"));
            }
            else
            {
                my_dtostrf( g_course, -BUF_SIZE, 1, str );
            }
            break;
        case eDisplayType::eTime:
            if(g_clockSet)
            {
                int h = (hour()+g_config.gmtOffsetHours)%12;
                if(h == 0)
                    h=12;
                if( g_settingTime.settingMode)
                {
                    if( second()%2 == 1)
                        snprintf_P(str,BUF_SIZE,PSTR("--:%02i"),minute());
                    else
                        snprintf_P(str,BUF_SIZE,PSTR("%02i:%02i"),h,minute());
                }
                else
                {      
                    snprintf_P(str,BUF_SIZE,PSTR("%2i%c%02i"),h, (second()%2?':':' '),minute());
                }
            }
            else
            {
                snprintf_P(str,BUF_SIZE,PSTR("--%s--"),(second()%2?':':' '));
            }
            break;
        }
        //print to the display
        printString(str,displayTypeColor[displayToggle], GetCharIntensity());
    }
}
