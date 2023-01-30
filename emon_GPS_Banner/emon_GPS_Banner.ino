#include <Time.h>

/*--------------------------- Libraries ----------------------------------*/

#include <AltSoftSerial.h>
//#include <SoftwareSerial.h>           // Allows PMS to avoid the USB serial port
#include <TinyNMEA.h>

#include <NeoPixelBus.h>
#include <PinChangeInt.h>

#include <SPI.h>
//#include <avr/wdt.h>
#include <TimeLib.h>
#include <BME280I2C.h>
#include <Wire.h>

/////////////////////////////////////////
//#define     GPS_RX_PIN              5               // Rx from PMS (== PMS Tx)
//#define     GPS_TX_PIN              6               // Tx to PMS (== PMS Rx)
#define     GPS_BAUD_RATE         9600               // PMS5003 uses 9600bps
#define     LED                     13               // Built-in LED pin

#define GSV_DISABLE F("$PUBX,40,GSV,0,0,0,0,0,0*59")
#define GLL_DISABLE F("$PUBX,40,GLL,0,0,0,0,0,0*5C")
#define RMC_DISABLE F("$PUBX,40,RMC,0,0,0,0,0,0*47")

const int TIME_ZONE_OFFSET = 8;  // AWST Perth



// #define SERIAL_BUF_LEN 200
// int gpsBufPos = 0;
// char gpsBuf[SERIAL_BUF_LEN];


// #define SERIAL_BUF_LEN 200
// int gpsBufPos;
// char gpsBuf[SERIAL_BUF_LEN];
TinyNMEA gpsNMEA;
//PayloadGPS g_payloadGPS;
//PayloadPressure g_payloadPressure;

//RH_RF69 g_rf69;

//EEPROMSettings  eepromSettings;

// Software serial port
//SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);
AltSoftSerial gpsSerial;  //pin 8 and 9

BME280I2C bme;    // Default : forced mode, standby time = 1000 ms
                  // Oversampling = pressure ×1, temperature ×1, humidity ×1, filter off,


float g_latitude = 0;
float g_longitude = 0;
float g_course = 0;
float g_speed = 0;
float g_pressure = 0;
float g_temperature = 0;
float g_humidity = 0;


const byte digits[12][5]={  //5*8
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
                            {0x00,0x00,0x24,0x00,0x00}, //:
                                
    };
const uint8_t LDR_PIN = A0;
const uint8_t PIXEL_PIN = 3;
const uint8_t LED_PIN = A3;  //Pin 17
const uint8_t NUM_BUTTONS = 2;
const uint8_t  g_buttons[NUM_BUTTONS] = { A1, A2 };	//pin number for each input A1, A2.  Pins 15 & 16
const uint16_t NUM_PIXELS = 256;

volatile unsigned long	g_lastButtonPush[NUM_BUTTONS]	= { 0,0 };

volatile uint8_t g_displayMode = 1; //0 is off, 1 is dimmed text, 2 is white light

NeoPixelBus<NeoGrbFeature, Neo800KbpsMethod> strip(NUM_PIXELS,PIXEL_PIN);


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
            return;		// we only support 3 buttons though we could get an interrupt for more!
    }
    unsigned long msSinceLastButton = millis()- g_lastButtonPush[button];
    g_lastButtonPush[button] = millis();

    if(msSinceLastButton <20)
        return;     //button debounce

    if( button == 0)
    {
       
    }

    if( button == 1)
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
                    pixelColour = digits[digit][i] & 1<<b ? onColour : offColour;
                else
                    pixelColour = digits[digit][i] & 1<<(7-b) ? onColour : offColour;
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

        // Serial.print(F("value:   ")); Serial.println(value);
        // Serial.print(F("whole:   ")); Serial.println(whole);
        // Serial.print(F("fraction:")); Serial.println(fraction);
        // Serial.print(F("places:  ")); Serial.println(places);
        // Serial.print(F("decimals:")); Serial.println(decimals);
        // Serial.print(F("negative:")); Serial.println(negative);
        
        //use -1 as indication to align to centre
        if(offset == -1)
            offset = NUM_PIXELS/8/2 - (places + negative + 1)*(5+1)/2;

        if(decimals > 0)
        {
            for (int i = 0; i < decimals; i++)
            {
                int digit = fraction % 10;
                bannerDigit(digit, offset, colour);
                fraction = fraction/10;
                offset += 5+1;
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
            offset += 5+1;
        }

        if(negative)
        {
            bannerDigit(10, offset, colour);
            offset += 5+1;
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
            offset = NUM_PIXELS/8/2 - (places+1)*(5+1)/2;

        for (int i = 0; i <= places; i++)
        {
            int digit = value % 10;
            bannerDigit(digit, offset, colour);
            value = value/10;
            offset += 5+1;
        }
    }
    strip.Show();
}

// void printTime(uint8_t hours, uint8_t mins, uint8_t secs, RgbColor inColour, uint8_t intensity = 255)
// {
//     RgbColor colour = RgbColor(inColour.R*intensity/255,inColour.G*intensity/255,inColour.B*intensity/255);

//     for(uint16_t pixel=0; pixel <NUM_PIXELS; pixel++)
//     {
//         strip.SetPixelColor(pixel, (g_displayMode==2?RgbColor(255, 255, 255):RgbColor(0, 0, 0)));
//     }

//     int places = 5;
//     if( hours > 9)
//       places += 1;

//     int offset = NUM_PIXELS/8/2 - (places+1)*(5+1)/2;
// }

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

extern char *__brkval;

int freeMemory()
{
  char top;
  return &top - __brkval;
}

void digitalClockDisplay() {
 // digital clock display of the time
 Serial.print(hour());
 printDigits(minute());
 printDigits(second());
 Serial.print(F(" "));
 Serial.print(day());
 Serial.print(F(" "));
 Serial.print(month());
 Serial.print(F(" "));
 Serial.print(year());
 Serial.println();
}

void printDigits(int digits) {
 // utility function for digital clock display: prints preceding colon and leading 0
 Serial.print(F(":"));
 if (digits < 10)
    Serial.print('0');
 Serial.print(digits);
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


    //have to set SoftwareSerial.h _SS_MAX_RX_BUFF 64 to 128 to receive more than one NMEA string
    // Open a connection to the PMS and put it into passive mode
    gpsSerial.begin(GPS_BAUD_RATE);

    delay(1000);
    //SelectSentences();
    SelectRMConly();
    //AllSentences();
    //  gpsSerial.println(GSV_DISABLE);
    //  delay(100);
    //  gpsSerial.println(RMC_DISABLE);
    //  delay(100);
    //  gpsSerial.println(GLL_DISABLE);
    //  delay(100);
    
    //gpsBufPos = 0;
    

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

    setTime(9,0,0,1,1,2023);

    strip.Begin();
    for(uint16_t ui=0; ui<NUM_PIXELS; ui++)
        strip.SetPixelColor(ui, RgbColor(0,0,0));

    strip.Show();

    for(uint8_t button = 0; button < NUM_BUTTONS; button++)
    {
        attachPinChangeInterrupt(g_buttons[button], interruptHandlerIR, RISING);
    }

//    Serial.println(F("Watchdog timer set for 8 seconds"));
//    wdt_enable(WDTO_8S);  
}


void loop()
{    
    //reset the watchdog timer
    //wdt_reset();
    static uint32_t lastSendPressureTime = millis();
    static int displayToggle = 0;
    static unsigned long displayToggleTime = millis();

    bool newData = false;
    
    while (gpsSerial.available())
    {
        char ch = gpsSerial.read();
        Serial.print(ch); // uncomment this line if you want to see the GPS data flowing
        
        if (gpsNMEA.encode(ch)) // Did a new valid sentence come in?
        {
            digitalWrite(LED_PIN,HIGH);
            newData = true;
            unsigned long age;
            int Year;
            byte Month, Day, Hour, Minute, Second;
    
            gpsNMEA.crack_datetime(&Year, &Month, &Day, &Hour, &Minute, &Second, NULL, &age);
            if (age < 1000) 
            {
              // set the Time to the latest GPS reading
              setTime(Hour, Minute, Second, Day, Month, Year);
              adjustTime(TIME_ZONE_OFFSET * SECS_PER_HOUR);
              digitalClockDisplay();
            }

            gpsNMEA.f_get_position(&g_latitude, &g_longitude, &age);
            g_speed = gpsNMEA.f_speed_knots();
            g_course = gpsNMEA.f_course();


            Serial.println(F("==>Received GPS"));
            Serial.print(F(" LAT="));
            Serial.print(g_latitude == TinyNMEA::GPS_INVALID_F_ANGLE ? 0.0 : g_latitude, 6);
            Serial.print(F(" LON="));
            Serial.print(g_longitude == TinyNMEA::GPS_INVALID_F_ANGLE ? 0.0 : g_longitude, 6);
            Serial.print(F(" SAT="));
            Serial.print(gpsNMEA.satellites() == TinyNMEA::GPS_INVALID_SATELLITES ? 0 : gpsNMEA.satellites());
            Serial.print(F(" PREC="));
            Serial.print(gpsNMEA.hdop() == TinyNMEA::GPS_INVALID_HDOP ? 0 : gpsNMEA.hdop());
            Serial.print(F(" SPEED="));
            Serial.print(g_speed == TinyNMEA::GPS_INVALID_SPEED ? 0 : g_speed/100.0,1);
            Serial.print(F(" HEADING="));
            Serial.println(g_course == TinyNMEA::GPS_INVALID_ANGLE ? 0 : g_course/100.0,1);
        }
    }

    //Serial.print("Free mem(");Serial.print(freeMemory());Serial.println(")");

    if( millis() - lastSendPressureTime > 15000 )
    {
       digitalWrite(LED_PIN,HIGH);
      lastSendPressureTime = millis();

      BME280::TempUnit tempUnit(BME280::TempUnit_Celsius);
      BME280::PresUnit presUnit(BME280::PresUnit_Pa);
      bme.read(g_pressure, g_temperature, g_humidity, tempUnit, presUnit);
      g_pressure = g_pressure/100;

      // Serial.println(F("==>Read BME280"));
      // Serial.print(F(" Pressure="));
      // Serial.print(g_pressure, 1);
      // Serial.print(F(" Temperature="));
      // Serial.print(g_temperature, 1);
      // Serial.print(F(" Humidity="));
      // Serial.print(g_humidity, 1);
      // Serial.println();
    }

    switch( displayToggle)
    {
      case 0:
        //Produced is green
        printValue( g_pressure,1, RgbColor(0,255,0), -1, readLDR());
        //Serial.println(g_pressure,1);
        break;
      case 1:
        //Consumed is pink
        printValue(g_temperature,1, RgbColor(255,0,0), -1, readLDR());
        //Serial.println(g_temperature,1);
        break;
      case 2:
        printValue(g_speed,1, RgbColor(0,0,255), -1, readLDR());
        //Serial.println(g_speed,1);
        break;
      case 3:
        printValue(g_course,1, RgbColor(255,255,0), -1, readLDR());
        //Serial.println(g_course,1);
        break;
      case 4:
        printValue(hour(), RgbColor(255,0,255), (hour()<=9?6:1), readLDR());
        if( minute() <=9 )
        {
            printValue(0, RgbColor(255,0,255), 14, readLDR());
            printValue(0, RgbColor(255,0,255), 20, readLDR());
        }
        else
          printValue(minute(), RgbColor(255,0,255), 14, readLDR());

        //Serial.println(millis());
        break;
    }
    digitalWrite(LED_PIN,LOW);

    if( millis() - displayToggleTime >1000 )
    {
      displayToggle = (displayToggle+1) % 5;
      displayToggleTime = millis();
    }
}
