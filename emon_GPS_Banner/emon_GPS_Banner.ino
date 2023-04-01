#include <Time.h>

/*--------------------------- Libraries ----------------------------------*/

#include <AltSoftSerial.h>
//#include <SoftwareSerial.h>           // Allows PMS to avoid the USB serial port
#include <TinyNMEA.h>

#include <NeoPixelBus.h>
#include <PinChangeInt.h>

#include <EEPROM.h>
#include <util/crc16.h>
#include <util/parity.h>

#include <SPI.h>
//#include <avr/wdt.h>
#include <TimeLib.h>
#include <BME280I2C.h>
#include <Wire.h>

/////////////////////////////////////////
#define     GPS_RX_PIN              8               // Rx from PMS (== PMS Tx)
#define     GPS_TX_PIN              9               // Tx to PMS (== PMS Rx)
#define     GPS_BAUD_RATE         9600               // PMS5003 uses 9600bps
#define     LED                     13               // Built-in LED pin

#define GSV_DISABLE F("$PUBX,40,GSV,0,0,0,0,0,0*59")
#define GLL_DISABLE F("$PUBX,40,GLL,0,0,0,0,0,0*5C")
#define RMC_DISABLE F("$PUBX,40,RMC,0,0,0,0,0,0*47")

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
                    eHalfLight, 
                    eFullLight,
                    eEndDisplayMode
                };

typedef struct {
  unsigned long pinDownTime;
  bool pinDown;
  bool settingTime;
  unsigned long settingTimeTimeout;
} SettingTime;

//Setting stored to EEPROM
//EEPROM settings stored for an individual node.
const uint8_t EEPROM_SETTINGS_BASE = 100; //260 is already used by EmonEEPROM
const uint8_t EEPROM_VERSION = 1;     
typedef struct {
    uint8_t version;
    uint8_t gmtOffsetHours;
    uint8_t displayType;
    uint8_t displayMode;
	word crc;						//crc checksum.
} EEPROMConfig;

typedef struct {
    byte bits[5];       //bitmap of the char
    byte width;         //font width, maximum of 5
    char refChar;       //Char it references, and char to use to write
} LEDChar;


//const int TIME_ZONE_OFFSET = 8;  // AWST Perth

const uint8_t NUM_CHARS = 17;
const LEDChar LEDChars[NUM_CHARS] PROGMEM = 
{
    { {0x3E,0x45,0x49,0x51,0x3E}, 5, '0' },
    { {0x00,0x21,0x7F,0x01,0x00}, 5, '1' },
    { {0x21,0x43,0x45,0x49,0x31}, 5, '2' },
    { {0x42,0x41,0x51,0x69,0x46}, 5, '3' },
    { {0x0C,0x14,0x24,0x7F,0x04}, 5, '4' },
    { {0x72,0x51,0x51,0x51,0x4E}, 5, '5' },
    { {0x1E,0x29,0x49,0x49,0x06}, 5, '6' },
    { {0x40,0x47,0x48,0x50,0x60}, 5, '7' },
    { {0x36,0x49,0x49,0x49,0x36}, 5, '8' },
    { {0x30,0x49,0x49,0x4A,0x3C}, 5, '9' },
    { {0x00,0x00,0x00,0x00,0x00}, 1, ' ' },     //space char
    { {0x01,0x00,0x00,0x00,0x00}, 1, '.' },     //decimal point char
    { {0x14,0x00,0x00,0x00,0x00}, 1, ':' },     //colon char
    { {0x00,0x08,0x08,0x08,0x00}, 5, '-' },     //minus char
    { {0x20,0x50,0x20,0x00,0x00}, 3, 'o' },     //degree Heading char
    { {0x20,0x50,0x50,0x00,0x00}, 3, 'c' },     //degree C char
    { {0x00,0x00,0x7C,0x08,0x14}, 5, 'k' },     //knots speed
};

const uint8_t LDR_PIN = A0;
const uint8_t PIXEL_PIN = 3;
const uint8_t LED_PIN = A3;  //Pin 17
const uint8_t NUM_BUTTONS = 2;
const uint8_t  g_buttons[NUM_BUTTONS] = { A1, A2 };	//pin number for each input A1, A2.  Pins 15 & 16
const uint16_t NUM_PIXELS = 256;

volatile unsigned long	g_lastButtonPush[NUM_BUTTONS]	= { 0,0 };
volatile bool g_configChanged = false;
volatile SettingTime g_settingTime = { 0, false, false, 0 };

EEPROMConfig g_config = {0,0,0,0};

// Software serial port
//SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);
AltSoftSerial gpsSerial;  //pin 8 and 9

BME280I2C bme;    // Default : forced mode, standby time = 1000 ms
                  // Oversampling = pressure ×1, temperature ×1, humidity ×1, filter off,
TinyNMEA gpsNMEA;

float g_latitude = 0;
float g_longitude = 0;
float g_course = 0;
float g_speed = 0;
float g_pressure = 0;
float g_temperature = 0;
float g_humidity = 0;

bool g_clockSet = false;

NeoPixelBus<NeoGrbFeature, Neo800KbpsMethod> strip(NUM_PIXELS,PIXEL_PIN);


extern char *__brkval;

int freeMemory()
{
  char top;
  return &top - __brkval;
}


LEDChar* LEDChar_F(uint8_t index, LEDChar* pLedChar)
{
    if( index < 0 || index > NUM_CHARS )
    {
        Serial.print(F("LEDChar index out-of-range-"));
        Serial.println(index);
        index = 12; //substitute the '-' char if an out-of-range index is used
    }
    memcpy_P(pLedChar,&LEDChars[index], sizeof(LEDChar));
    return pLedChar;
}

LEDChar* GetLEDChar(char ch, LEDChar* pLedChar)
{
    for(short i=0; i< NUM_CHARS; i++)
    {
        LEDChar_F(i, pLedChar);
        if( pLedChar->refChar == ch)
        {
            return pLedChar;
        }
    }
    return pLedChar;
}


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
                if( g_settingTime.settingTime )
                {
                    //increment the hour on a button down while setting time
                    g_config.gmtOffsetHours = (g_config.gmtOffsetHours+1)%12;   //we only do a 12 hour clock!
                    g_settingTime.settingTimeTimeout = millis();    //reset on each button press
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
            if(g_config.displayType == eDisplayType::eTime && !g_settingTime.settingTime &&  millis() - g_settingTime.pinDownTime <1000)
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


RgbColor GetBackgroundColour()
{
    switch( g_config.displayMode)
    {
        case eDisplayMode::eHalfLight:
            //return RgbColor(64, 64, 64);
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


//refChar is the char to write
//offset is lines of 8 leds from 0 along the Banner bar
//colour is the colour of the text
short bannerChar(char ch, int offset, RgbColor colour)
{
    LEDChar ledChar;
    GetLEDChar(ch, &ledChar);

    for(int i=0; i < ledChar.width;i++)
    {
        if(offset+i >= 0 )
        {
            int ledIndex = (offset+i)*8;
            for(int b=0; b<8;b++)
            {
                RgbColor onColour = colour;
                RgbColor offColour = GetBackgroundColour();
                RgbColor pixelColour;
                if( (offset+i) %2 == 1) // the LEDS go alternat direction each line of the bar!
                    pixelColour = ledChar.bits[i] & 1<<b ? onColour : offColour;
                else
                    pixelColour = ledChar.bits[i] & 1<<(7-b) ? onColour : offColour;
                if( ledIndex+b < 0 || ledIndex+b >= NUM_PIXELS)
                {
                    Serial.print(F("Bad Pixel("));Serial.print(ledIndex+b);Serial.println(F(")"));
                }
                else
                {
                    strip.SetPixelColor(ledIndex+b, pixelColour);
                }
            }
        }
    }
    return ledChar.width;
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
        LEDChar ledChar;

        if(offset == -1)        //center text on banner
        {
            short width = 0;
            for(int i=0; i< strlen(str); i++)
            {
                GetLEDChar(str[i], &ledChar);
                width += ledChar.width+1;
            }
            offset = 16 - width/2;
            Serial.print(F("str,l,w,o="));
            Serial.print(str);
            Serial.print(F(","));
            Serial.print(strlen(str));
            Serial.print(F(","));
            Serial.print(width);
            Serial.print(F(","));
            Serial.println(offset);
        }
        //Serial.print(F("Str "));
        for(short i=0;i<strlen(str); i++)
        {
        //Serial.print(str[i]);Serial.print(F(":"));Serial.print(offset);Serial.print(F(","));
            offset += bannerChar(str[i], offset, colour);
            offset += 1;
        }
        //Serial.println();
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

void SelectRMConly()
{
  // NMEA_GLL output interval - Geographic Position - Latitude longitude
  // NMEA_RMC output interval - Recommended Minimum Specific GNSS Sentence
  // NMEA_VTG output interval - Course Over Ground and Ground Speed
  // NMEA_GGA output interval - GPS Fix Data
  // NMEA_GSA output interval - GNSS DOPS and Active Satellites
  // NMEA_GSV output interval - GNSS Satellites in View

  gpsSerial.println(F("$PUBX,40,GGA,0,0,0,0*5A"));
  delay(100);

  gpsSerial.println(F("$PUBX,40,RMC,0,1,0,0*46"));
  delay(100);

  // disable $PUBX,40,GLL,0,0,0,0*5C
  gpsSerial.println(F("$PUBX,40,GLL,0,0,0,0*5C"));
  delay(100);

  // disable $PUBX,40,VTG,0,0,0,0*5E
  gpsSerial.println(F("$PUBX,40,VTG,0,0,0,0*5E"));
  delay(100);
  
  // disable $PUBX,40,GSA,0,0,0,0*4E
  gpsSerial.println(F("$PUBX,40,GSA,0,0,0,0*4E"));
  delay(100);  

  // disable $PUBX,40,GSV,0,0,0,0*59
  gpsSerial.println(F("$PUBX,40,GSV,0,0,0,0*59"));
  delay(100);
  
}

void SelectSentences()
{
  // See http://cdn.sparkfun.com/datasheets/Sensors/GPS/760.pdf
  // Also https://www.roboticboat.uk/Microcontrollers/Uno/GPS-PAM7Q/GPS-PAM7Q.html for enable/disable NMEA strings
  // NMEA_GLL output interval - Geographic Position - Latitude longitude
  // NMEA_RMC output interval - Recommended Minimum Specific GNSS Sentence
  // NMEA_VTG output interval - Course Over Ground and Ground Speed
  // NMEA_GGA output interval - GPS Fix Data
  // NMEA_GSA output interval - GNSS DOPS and Active Satellites
  // NMEA_GSV output interval - GNSS Satellites in View

  // Enable $PUBX,40,RMC,0,1,0,0*46
  gpsSerial.println(F("$PUBX,40,RMC,0,1,0,0*46"));
  delay(100);

  // Enable $PUBX,40,GGA,0,1,0,0*5B
  gpsSerial.println(F("$PUBX,40,GGA,0,1,0,0*5B"));
  delay(100);

  // disable $PUBX,40,GLL,0,0,0,0*5C
  gpsSerial.println(F("$PUBX,40,GLL,0,0,0,0*5C"));
  delay(100);
  
  // disable $PUBX,40,VTG,0,0,0,0*5E
  gpsSerial.println(F("$PUBX,40,VTG,0,0,0,0*5E"));
  delay(100);
  
  // disable $PUBX,40,GSA,0,0,0,0*4E
  gpsSerial.println(F("$PUBX,40,GSA,0,0,0,0*4E"));
  delay(100);  

  // disable $PUBX,40,GSV,0,0,0,0*59
  gpsSerial.println(F("$PUBX,40,GSV,0,0,0,0*59"));
  delay(100);
  
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
    Serial.print( g_config.displayType);
    Serial.print(F(",GMT offset="));
    Serial.print( g_config.gmtOffsetHours);
    Serial.println();

    //have to set SoftwareSerial.h _SS_MAX_RX_BUFF 64 to 128 to receive more than one NMEA string
    // Open a connection to the PMS and put it into passive mode
    gpsSerial.begin(GPS_BAUD_RATE);
    delay(1000);
    SelectRMConly();

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

    strip.Begin();
    for(uint16_t ui=0; ui<NUM_PIXELS; ui++)
        strip.SetPixelColor(ui, RgbColor(0,0,0));
    strip.Show();

    for(uint8_t button = 0; button < NUM_BUTTONS; button++)
    {
        attachPinChangeInterrupt(g_buttons[button], interruptHandlerIR, CHANGE);
    }

    Serial.println("Exit setup()");
//    Serial.println(F("Watchdog timer set for 8 seconds"));
//    wdt_enable(WDTO_8S);  
}

void loop()
{    
    //reset the watchdog timer
    //wdt_reset();
    static uint32_t lastSendPressureTime = millis();
    static int displayToggle = 2;
    static unsigned long displayRotateTime = millis();

    //deal with the time setting mode. 
    //  Hold button down for 3000 ms to enter into mode
    //  Move out of mode if no button pressed for 5 seconds
    if( g_settingTime.pinDown && millis() - g_settingTime.pinDownTime > 3000 && !g_settingTime.settingTime)
    {
        //move into the setTime mode
        g_settingTime.settingTime = true;
        g_settingTime.settingTimeTimeout = millis();
        Serial.println(F("Setting time"));
    }
    if(g_settingTime.settingTime && millis() - g_settingTime.settingTimeTimeout >15000)
    {
        //move out of setTime mode
        g_settingTime.settingTime = false;
        Serial.println(F("Finished setting time"));
    }

    if( !g_settingTime.settingTime)
    {
        //Need to reset the serial after each call to NeoPixel as neoPixel stops interrupts breaks AltSoftSerial
        //Delay 1100 to fill serial buffer (1 message/second)
        //gpsSerial.begin(GPS_BAUD_RATE);
        delay(1000);
        
        while (gpsSerial.available())
        {
            char ch = gpsSerial.read();
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

                gpsNMEA.f_get_position(&g_latitude, &g_longitude, &age);
                g_speed = gpsNMEA.f_speed_knots();
                g_course = gpsNMEA.f_course();
            }
        }
    }

    if( millis() - lastSendPressureTime > 15000 )
    {
      digitalWrite(LED_PIN,HIGH);
      lastSendPressureTime = millis();

      BME280::TempUnit tempUnit(BME280::TempUnit_Celsius);
      BME280::PresUnit presUnit(BME280::PresUnit_Pa);
      bme.read(g_pressure, g_temperature, g_humidity, tempUnit, presUnit);
      g_pressure = g_pressure/100;

      Serial.println(F("==>Read BME280"));
      Serial.print(F(" Pressure="));
      Serial.print(g_pressure, 1);
      Serial.print(F(" Temperature="));
      Serial.print(g_temperature, 1);
      Serial.print(F(" Humidity="));
      Serial.print(g_humidity, 1);
      Serial.println();
    }

    if(g_configChanged)
    {
        //the button was pressed. Need to store to EEPROM
        WriteEEPROMSettings( g_config );
        g_configChanged = false;
    }

    if( g_config.displayType == eDisplayType::eAutoRotate)
    {
        if( millis() - displayRotateTime >3000 )
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

    Serial.print(F("Free mem,mode,type,toggle="));
    Serial.print(freeMemory());
    Serial.print(F(","));
    Serial.print(g_config.displayMode);
    Serial.print(F(","));
    Serial.print(g_config.displayType);
    Serial.print(F(","));
    Serial.println(displayToggle);

    #define BUF_SIZE 10
    char chVal[BUF_SIZE];
    char str[BUF_SIZE];

    switch( displayToggle)
    {
      case eDisplayType::ePressure:        
        my_dtostrf( g_pressure, -BUF_SIZE, 1, chVal );
        snprintf_P(str,BUF_SIZE,PSTR("%s"),chVal);
        printString(str,RgbColor(0,255,0), readLDR()); //Green
        break;
      case eDisplayType::eTemp:
        my_dtostrf( g_temperature, -BUF_SIZE, 1, chVal );
        snprintf_P(str,BUF_SIZE,PSTR("%sc"),chVal);
        printString(str,RgbColor(255,0,0), readLDR()); //Red
        break;
      case eDisplayType::eSpeed:
        my_dtostrf( g_speed, -BUF_SIZE, 1, chVal );
        snprintf_P(str,BUF_SIZE,PSTR("%sk"),chVal);
        printString(str,RgbColor(0,0,255), readLDR()); //Blue
        break;
      case eDisplayType::eHeading:
        my_dtostrf( g_course, -BUF_SIZE, 1, chVal );
        snprintf_P(str, BUF_SIZE,PSTR("%so"),chVal);
        printString(str,RgbColor(255,255,0), readLDR());
        break;
      case eDisplayType::eTime:
        if(g_clockSet)
        {
            int h = (hour()+g_config.gmtOffsetHours)%12;
            if(h == 0)
                h=12;
            if( g_settingTime.settingTime)
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
        printString(str,RgbColor(255,0,255), readLDR());
        break;
    }
    digitalWrite(LED_PIN,LOW);
}
