/*--------------------------- Libraries ----------------------------------*/
#include <SoftwareSerial.h>           // Allows PMS to avoid the USB serial port
#include <TinyNMEA.h>

#include <EmonShared.h>
#include <EmonEEPROM.h>
//Radiohead RF_69 support
#include <SPI.h>
#include <RH_RF69.h>
//watchdog timer
#include <avr/wdt.h>

/////////////////////////////////////////
#define     GPS_RX_PIN              A5               // Rx from PMS (== PMS Tx)
#define     GPS_TX_PIN              A6               // Tx to PMS (== PMS Rx)
#define     GPS_BAUD_RATE         9600               // PMS5003 uses 9600bps
#define     LED                     13               // Built-in LED pin

#define GSV_DISABLE F("$PUBX,40,GSV,0,0,0,0,0,0*59")
#define GLL_DISABLE F("$PUBX,40,GLL,0,0,0,0,0,0*5C")
#define RMC_DISABLE F("$PUBX,40,RMC,0,0,0,0,0,0*47")

#define SERIAL_BUF_LEN 200
int gpsBufPos;
char gpsBuf[SERIAL_BUF_LEN];
TinyNMEA gpsNMEA;
PayloadGPS g_payloadGPS;

RH_RF69 g_rf69;

EEPROMSettings  eepromSettings;


/*--------------------------- Instantiate Global Objects -----------------*/
// Software serial port
SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);

/*--------------------------- Program ------------------------------------*/

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

// void ReadSerial()
// {
//     while (gpsSerial.available())
//     {
//         Serial.print((char)gpsSerial.read());
//     }
//     Serial.println("======================");
// }

// void SelectGGAonly()
// {
//   // NMEA_GLL output interval - Geographic Position - Latitude longitude
//   // NMEA_RMC output interval - Recommended Minimum Specific GNSS Sentence
//   // NMEA_VTG output interval - Course Over Ground and Ground Speed
//   // NMEA_GGA output interval - GPS Fix Data
//   // NMEA_GSA output interval - GNSS DOPS and Active Satellites
//   // NMEA_GSV output interval - GNSS Satellites in View

//   // Enable $PUBX,40,GGA,0,1,0,0*5B
//   gpsSerial.println("$PUBX,40,GGA,0,1,0,0*5B");
//   delay(100);
//   ReadSerial();

//   // disable $PUBX,40,RMC,0,0,0,0*47
//   gpsSerial.println("$PUBX,40,RMC,0,0,0,0*47");
//   delay(100);
//   ReadSerial();

//   // disable $PUBX,40,GLL,0,0,0,0*5C
//   gpsSerial.println("$PUBX,40,GLL,0,0,0,0*5C");
//   delay(100);
//   ReadSerial();

//   // disable $PUBX,40,VTG,0,0,0,0*5E
//   gpsSerial.println("$PUBX,40,VTG,0,0,0,0*5E");
//   delay(100);
//   ReadSerial();
  
//   // disable $PUBX,40,GSA,0,0,0,0*4E
//   gpsSerial.println("$PUBX,40,GSA,0,0,0,0*4E");
//   delay(100);  
//   ReadSerial();

//   // disable $PUBX,40,GSV,0,0,0,0*59
//   gpsSerial.println("$PUBX,40,GSV,0,0,0,0*59");
//   delay(100);
//   ReadSerial();
  
// }
/**
  Setup
*/
void setup()
{
    pinMode(LED, OUTPUT);    

    Blink(LED, 50, 3);

    Serial.begin(9600); 
    Serial.println();
    Serial.print("GPS sketch");

    //set the subnode from teh eeprom settings
    EmonEEPROM::ReadEEPROMSettings(eepromSettings);
    EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
    g_payloadGPS.subnode = eepromSettings.subnode;

    //have to set SoftwareSerial.h _SS_MAX_RX_BUFF 64 to 128 to receive more than one NMEA string
    // Open a connection to the PMS and put it into passive mode
    gpsSerial.begin(GPS_BAUD_RATE);   // Connection for PMS5003

    delay(1000);
    //SelectGGAonly();

    // gpsSerial.println(GSV_DISABLE);
    // delay(100);
    // gpsSerial.println(RMC_DISABLE);
    // delay(100);
    // gpsSerial.println(GLL_DISABLE);
    // delay(100);
    
    gpsBufPos = 0;
    

    if (!g_rf69.init())
        Serial.println("g_rf69 init failed");
    // Defaults after init are 434.0MHz, modulation GFSK_Rb250Fd250, +13dbM (for low power module)
    // No encryption
    if (!g_rf69.setFrequency(914.0))
        Serial.println("setFrequency failed");
    g_rf69.setHeaderId(GPS_NODE);

    // The encryption key has to be the same as the one in the client
    uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    g_rf69.setEncryptionKey(key);

	EmonSerial::PrintGPSPayload(NULL);
    memset(&g_payloadGPS, 0, sizeof(PayloadGPS));

//    Serial.println(F("Watchdog timer set for 8 seconds"));
//    wdt_enable(WDTO_8S);  
}

/**
  Main loop
*/
void loop()
{
    //reset the watchdog timer
    //wdt_reset();
    uint32_t time_now = millis();
    bool newData = false;
    unsigned long age;

    while (gpsSerial.available())
    {
        char ch = gpsSerial.read();
        //Serial.print(ch);
        if( ch == '$' || gpsBufPos-2 >= SERIAL_BUF_LEN )
          gpsBufPos = 0;
        gpsBuf[gpsBufPos++] = ch;

        Serial.write(ch); // uncomment this line if you want to see the GPS data flowing
        if (gpsNMEA.encode(ch)) // Did a new valid sentence come in?
        {
            gpsSerial.println(GSV_DISABLE);
            delay(100);


            newData = true;

            gpsBuf[gpsBufPos++] = '\n';
            gpsBuf[gpsBufPos++] = '\0';
            Serial.print(gpsBuf);

            gpsNMEA.f_get_position(&g_payloadGPS.latitude, &g_payloadGPS.longitude, &age);
            g_payloadGPS.speed = gpsNMEA.f_speed_knots();
            g_payloadGPS.course = gpsNMEA.f_course();

            g_rf69.send((const uint8_t*) &g_payloadGPS, sizeof(g_payloadGPS));

            if( g_rf69.waitPacketSent() )
            {
                EmonSerial::PrintGPSPayload(&g_payloadGPS);
            }
            else
            {
                Serial.println(F("No packet sent"));
            }

            Serial.println("==>Received GPS");
            // Serial.print(" LAT=");
            // Serial.print(g_flat == TinyNMEA::GPS_INVALID_F_ANGLE ? 0.0 : g_flat, 6);
            // Serial.print(" LON=");
            // Serial.print(g_flon == TinyNMEA::GPS_INVALID_F_ANGLE ? 0.0 : g_flon, 6);
            Serial.print(" SAT=");
            Serial.print(gpsNMEA.satellites() == TinyNMEA::GPS_INVALID_SATELLITES ? 0 : gpsNMEA.satellites());
            Serial.print(" PREC=");
            Serial.print(gpsNMEA.hdop() == TinyNMEA::GPS_INVALID_HDOP ? 0 : gpsNMEA.hdop());
            // Serial.print(" SPEED=");
            // Serial.print(g_fspeed == TinyNMEA::GPS_INVALID_SPEED ? 0 : g_fspeed/100.0,1);
            // Serial.print(" HEADING=");
            // Serial.println(g_fcourse == TinyNMEA::GPS_INVALID_ANGLE ? 0 : g_fcourse/100.0,1);
        }
    }

}

///////////////////////////////////////////////////////////////////////////////////////////////////////

/*#include <Wire.h>

byte start_address = 0;
byte end_address = 127;

void setup()
{
  byte rc;
  Wire.begin();

  Serial.begin(9600);
  Serial.println("\nI2C Scanner");

  Serial.print("Scanning I2C bus from ");
  Serial.print(start_address,DEC);  Serial.print(" to ");  Serial.print(end_address,DEC);
  Serial.println("...");

  for( byte addr  = start_address;
            addr <= end_address;
            addr++ ) {
      Wire.beginTransmission(addr);
      rc = Wire.endTransmission();

      if (addr<16) Serial.print("0");
      Serial.print(addr,HEX);
      if (rc==0) {
        Serial.print(" found!");
      } else {
        Serial.print(" "); Serial.print(rc); Serial.print("     ");
      }
      Serial.print( (addr%8)==7 ? "\n":" ");
  }

  Serial.println("\n-------------------------------\nPossible devices:");

  for( byte addr  = start_address;
            addr <= end_address;
            addr++ ) {
      Wire.beginTransmission(addr);
      rc = Wire.endTransmission();
      if (rc == 0) {
        Serial.print(addr,HEX); Serial.print(" = ");
        switch (addr) {
          case 0x50: Serial.println("AT24C32/AT24C64 - EEPROM"); break;
          case 0x68: Serial.println("DS1307"); break;
          default: Serial.println("Unknown"); break;
        }
      }
  }

  Serial.println("\ndone");
}


void loop()
{}

*/

/*
#include <Wire.h>
#include <MechaQMC5883.h>

MechaQMC5883 qmc;

void setup() {
  Wire.begin(0x0D);
  Serial.begin(9600);
  qmc.init();
  //qmc.setMode(Mode_Continuous,ODR_200Hz,RNG_2G,OSR_256);
}

void loop() {
  int x,y,z;
  int ret = qmc.read(&x,&y,&z);

  Serial.print("ret: ");
  Serial.print(ret);
  Serial.print("x: ");
  Serial.print(x);
  Serial.print(" y: ");
  Serial.print(y);
  Serial.print(" z: ");
  Serial.print(z);
  Serial.println();
  delay(500);
}

*/
/*
#include <Wire.h> //I2C Arduino Library

#define addr 0x1E //I2C Address for The HMC5883

void setup() {

  Serial.begin(9600);
  Wire.begin();


  Wire.beginTransmission(addr); //start talking
  Wire.write(0x0B); // Tell the HMC5883 to Continuously Measure
  Wire.write(0x01); // Set the Register
  Wire.endTransmission();
  Wire.beginTransmission(addr); //start talking
  Wire.write(0x09); // Tell the HMC5883 to Continuously Measure
  Wire.write(0x1D); // Set the Register
  Wire.endTransmission();
}

void loop() {

  int x, y, z; //triple axis data

  //Tell the HMC what regist to begin writing data into


  Wire.beginTransmission(addr);
  Wire.write(0x00); //start with register 3.
  Wire.endTransmission();

  //Read the data.. 2 bytes for each axis.. 6 total bytes
  Wire.requestFrom(addr, 6);
  if (6 <= Wire.available()) {
    x = Wire.read(); //MSB  x
    x |= Wire.read() << 8; //LSB  x
    z = Wire.read(); //MSB  z
    z |= Wire.read() << 8; //LSB z
    y = Wire.read(); //MSB y
    y |= Wire.read() << 8; //LSB y
  }

  // Show Values
  Serial.print("X Value: ");
  Serial.println(x);
  Serial.print("Y Value: ");
  Serial.println(y);
  Serial.print("Z Value: ");
  Serial.println(z);
  Serial.println();

  delay(500);
}
*/


/*
  GY-271 Compass
  modified on 02 Sep 2020
  by Mohammad Reza Akbari @ Electropeak
  Home


// I2C Library
#include <Wire.h>
// QMC5883L Compass Library
#include <QMC5883LCompass.h>

QMC5883LCompass compass;

void setup() {
  // Initialize the serial port.
  Serial.begin(9600);
  // Initialize I2C.
  Wire.begin();
  // Initialize the Compass.
  compass.init();
}

void loop() {
  int x, y, z;

  // Read compass values
  compass.read();

  x = compass.getX();
  y = compass.getY();
  z = compass.getZ();

  Serial.print("X: ");
  Serial.print(x);
  Serial.print("   Y: ");
  Serial.print(y);
  Serial.print("   Z: ");
  Serial.println(z);

  delay(300);
}

*/