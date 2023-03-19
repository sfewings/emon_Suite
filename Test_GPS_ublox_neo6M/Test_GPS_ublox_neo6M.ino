#include <Time.h>

/*--------------------------- Libraries ----------------------------------*/

#include <SoftwareSerial.h>           // Allows PMS to avoid the USB serial port
#include <TinyNMEA.h>

#include <EmonShared.h>
#include <EmonEEPROM.h>
//Radiohead RF_69 support
#include <SPI.h>
#include <RH_RF69.h>
//#include <avr/wdt.h>
#include <TimeLib.h>
#include <Wire.h>

/////////////////////////////////////////
//  Moteino GPS BME280 CY271 board : rx=5, tx= 6
//  Breadboard Enchantee V1        : rx=6, tx=5
#define     GPS_RX_PIN              5               // Rx from PMS (== PMS Tx)
#define     GPS_TX_PIN              6               // Tx to PMS (== PMS Rx)
#define     GPS_BAUD_RATE         9600               // PMS5003 uses 9600bps
#define     LED                     13               // Built-in LED pin
#define     RF_FREQUENCY          915.0
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
PayloadGPS g_payloadGPS;

RH_RF69 g_rf69;

EEPROMSettings  eepromSettings;

// Software serial port
SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);

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

void Select_GSA_RMC_Sentences()
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
  //gpsSerial.println(F("$PUBX,40,RMC,0,1,0,0*46"));
  gpsSerial.println(RMC_DISABLE);
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

void digitalClockDisplay() 
{
 // digital clock display of the time
 Serial.print(hour());
 printDigits(minute());
 printDigits(second());
 Serial.print(" ");
 Serial.print(day());
 Serial.print(" ");
 Serial.print(month());
 Serial.print(" ");
 Serial.print(year());
 Serial.println();
}

void printDigits(int digits) {
 // utility function for digital clock display: prints preceding colon and leading 0
 Serial.print(":");
 if (digits < 10)
 Serial.print('0');
 Serial.print(digits);
}


void setup()
{
    pinMode(LED, OUTPUT);    

    Blink(LED, 50, 3);

    Serial.begin(9600); 
    Serial.println(F("GPS sketch"));

    //set the subnode from the eeprom settings
    EmonEEPROM::ReadEEPROMSettings(eepromSettings);
    EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
    //g_payloadPressure.subnode = eepromSettings.subnode;

    //have to set SoftwareSerial.h _SS_MAX_RX_BUFF 64 to 128 to receive more than one NMEA string
    // Open a connection to the PMS and put it into passive mode
    gpsSerial.begin(GPS_BAUD_RATE);

    delay(1000);
    //SelectSentences();
    //SelectRMConly();
    Select_GSA_RMC_Sentences();
    //AllSentences();
    //  gpsSerial.println(GSV_DISABLE);
    //  delay(100);
    //  gpsSerial.println(RMC_DISABLE);
    //  delay(100);
    //  gpsSerial.println(GLL_DISABLE);
    //  delay(100);
    
    //gpsBufPos = 0;
    

    if (!g_rf69.init())
        Serial.println(F("g_rf69 init failed"));
    // Defaults after init are 434.0MHz, modulation GFSK_Rb250Fd250, +13dbM (for low power module)
    // No encryption
    if (g_rf69.setFrequency(RF_FREQUENCY))
    {
      Serial.print(F("RF69 frequency set to "));
      Serial.println(RF_FREQUENCY,1);
    }
    else
    {
      Serial.println(F("setFrequency failed"));
    }
    g_rf69.setHeaderId(GPS_NODE);

    // The encryption key has to be the same as the one in the client
    uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    g_rf69.setEncryptionKey(key);

	  EmonSerial::PrintGPSPayload(NULL);
    memset(&g_payloadGPS, 0, sizeof(PayloadGPS));
    g_payloadGPS.subnode = eepromSettings.subnode;
 
    setTime(9,0,0,1,1,2023);

//    Serial.println(F("Watchdog timer set for 8 seconds"));
//    wdt_enable(WDTO_8S);  
}


void loop()
{
    //reset the watchdog timer
    //wdt_reset();
   
    bool newData = false;
    

    while (gpsSerial.available())
    {
        char ch = gpsSerial.read();
        //Serial.print(ch); // uncomment this line if you want to see the GPS data flowing
        
        Serial.print(ch);
        // if( ch == '$' || gpsBufPos-2 >= SERIAL_BUF_LEN )
        // {
        //   gpsBuf[gpsBufPos++] = '\n';
        //   gpsBuf[gpsBufPos++] = '\0';
        //   Serial.print('-');
        //   Serial.print(gpsBuf);
        //   gpsBufPos = 0;
        // }
        // gpsBuf[gpsBufPos++] = ch;


        if (gpsNMEA.encode(ch)) // Did a new valid sentence come in?
        {
            digitalWrite(LED,HIGH);
            newData = true;

            // gpsBuf[gpsBufPos++] = '\n';
            // gpsBuf[gpsBufPos++] = '\0';
            // Serial.print('+');
            // Serial.print(gpsBuf);


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

            gpsNMEA.f_get_position(&g_payloadGPS.latitude, &g_payloadGPS.longitude, &age);
            g_payloadGPS.speed = gpsNMEA.f_speed_knots();
            g_payloadGPS.course = gpsNMEA.f_course();
            g_payloadGPS.numSatellites = gpsNMEA.satellites();
            g_payloadGPS.hdop = gpsNMEA.hdop()/100.0;  

            g_rf69.setHeaderId(GPS_NODE);
            g_rf69.send((const uint8_t*) &g_payloadGPS, sizeof(g_payloadGPS));
            if( g_rf69.waitPacketSent() )
            {
              EmonSerial::PrintGPSPayload(&g_payloadGPS);
              Serial.print("Free mem(");Serial.print(freeMemory());Serial.println(")");
            }
            else
            {
                Serial.println(F("No packet sent"));
            }

            //SendSignalKDataGPS(g_payloadGPS.latitude, g_payloadGPS.longitude, g_payloadGPS.speed, g_payloadGPS.course );


            // Serial.println("==>Received GPS");
            // // Serial.print(" LAT=");
            // // Serial.print(g_flat == TinyNMEA::GPS_INVALID_F_ANGLE ? 0.0 : g_flat, 6);
            // // Serial.print(" LON=");
            // // Serial.print(g_flon == TinyNMEA::GPS_INVALID_F_ANGLE ? 0.0 : g_flon, 6);
            // Serial.print(" SAT=");
            // Serial.print(gpsNMEA.satellites() == TinyNMEA::GPS_INVALID_SATELLITES ? 0 : gpsNMEA.satellites());
            // Serial.print(" PREC=");
            // Serial.print(gpsNMEA.hdop() == TinyNMEA::GPS_INVALID_HDOP ? 0 : gpsNMEA.hdop());
            // // Serial.print(" SPEED=");
            // // Serial.print(g_fspeed == TinyNMEA::GPS_INVALID_SPEED ? 0 : g_fspeed/100.0,1);
            // // Serial.print(" HEADING=");
            // // Serial.println(g_fcourse == TinyNMEA::GPS_INVALID_ANGLE ? 0 : g_fcourse/100.0,1);
        }
    }


    digitalWrite(LED,LOW);

}