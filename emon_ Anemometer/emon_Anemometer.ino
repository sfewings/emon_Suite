////////////////////////////////////////////
#include <SoftwareSerial.h>
#include <TinyNMEA.h>

#include <EmonShared.h>
#include <EmonEEPROM.h>
#include <RH_RF69.h>

//#define HOME_NETWORK
#define BOAT_NETWORK
#ifdef BOAT_NETWORK
	#define NETWORK_FREQUENCY 914.0
#elif defined( HOME_NETWORK )
	#define NETWORK_FREQUENCY 915.0
#endif

#define MOTEINO_LED 9			// LED on Moteino

#define SERIAL_BUF_LEN 200
int anemometerBufPos;
char anemometerBuf[SERIAL_BUF_LEN];

PayloadAnemometer g_payloadAnemometer;

TinyNMEA anemometer;
SoftwareSerial ss(3,4); // rx, tx

RH_RF69 g_rf69;

////////////////////////////////////////////////

void setup()
{
    pinMode(MOTEINO_LED, OUTPUT);     
    digitalWrite(MOTEINO_LED, HIGH );

    anemometerBufPos = 0;

    Serial.begin(9600);
    
    Serial.println(F("Emon anemometer start"));
    Serial.print("Using TinyNMEA library version "); 
    Serial.println(TinyNMEA::library_version());


    if (!g_rf69.init())
        Serial.println("rf69 init failed");
    if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
        Serial.println("rf69 setFrequency failed");
    // The encryption key has to be the same as the one in the client
    uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    g_rf69.setEncryptionKey(key);
    g_rf69.setHeaderId(DALY_BMS_NODE);
    g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
    //when using the RH_RF69 driver with the RFM69HW module, you must setTxPowercan with isHigherPowerModule set to true
    //Otherwise, the library will not set the PA_BOOST pin high and the module will not transmit
    g_rf69.setTxPower(13,true);

    Serial.print(F("RF69 initialise node: "));
    Serial.print(DALY_BMS_NODE);
    Serial.print(F(" Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println(F("MHz"));

    //initialise the EEPROMSettings for relay and node number
    EEPROMSettings eepromSettings;
    EmonEEPROM::ReadEEPROMSettings(eepromSettings);
    EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
    memset(&g_payloadAnemometer, 0, sizeof(g_payloadAnemometer));
    g_payloadAnemometer.subnode = eepromSettings.subnode;
    
    //set some defaults
    g_payloadAnemometer.temperature = 20;
    g_payloadAnemometer.windDirection = 180;
    g_payloadAnemometer.windSpeed = 10;

    ss.begin( 2400 );

    Serial.println("initilaised");
    delay(1000);

    digitalWrite(MOTEINO_LED, LOW );
}

void loop()
{
    delay(1000);
    digitalWrite(MOTEINO_LED, HIGH );

    //simulation mode
    g_payloadAnemometer.windSpeed = (float) ((int)g_payloadAnemometer.windSpeed +(int)random(0,3)-1);;
    if( g_payloadAnemometer.windSpeed < 0 ) g_payloadAnemometer.windSpeed = 0;
    if( g_payloadAnemometer.windSpeed > 100 ) g_payloadAnemometer.windSpeed = 100;

    g_payloadAnemometer.windDirection = (float) ((int)g_payloadAnemometer.windDirection +(int)random(0,3)-1);
    if( g_payloadAnemometer.windDirection < 0 ) g_payloadAnemometer.windDirection = 359;
    if( g_payloadAnemometer.windDirection >= 360 ) g_payloadAnemometer.windDirection = 0;

    g_payloadAnemometer.temperature = (float) ((int)g_payloadAnemometer.temperature +(int)random(0,3)-1);
    if( g_payloadAnemometer.temperature < -10 ) g_payloadAnemometer.temperature = -10;
    if( g_payloadAnemometer.temperature > 40 ) g_payloadAnemometer.temperature = 40;
    
    g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
    g_rf69.send((const uint8_t*) &g_payloadAnemometer, sizeof(PayloadAnemometer) );
    if( g_rf69.waitPacketSent() )
    {
        EmonSerial::PrintAnemometerPayload(&g_payloadAnemometer);
    }
    else
    {
        Serial.println(F("No packet sent"));
    }
    g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);


    digitalWrite(MOTEINO_LED, LOW );

  
    // while (ss.available())
    // {
    //     char c = Serial.read();

    //     if( c == '$' || anemometerBufPos-2 >= SERIAL_BUF_LEN )
    //       anemometerBufPos = 0;
    //     anemometerBuf[anemometerBufPos++] = c;

    //     Serial.write(c);    //write the stream stright back out
    //     if( anemometer.encode(c))
    //     {
    //         digitalWrite(MOTEINO_LED, HIGH );
    //         anemometerBuf[anemometerBufPos++] = '\n';
    //         anemometerBuf[anemometerBufPos++] = '\0';
    //         Serial.print(anemometerBuf);
    //         anemometerBufPos = 0;

    //         g_payloadAnemometer.windSpeed = (float) anemometer.windSpeed();
    //         g_payloadAnemometer.windDirection = (float) ((anemometer.windDirection()+130)%360);
    //         g_payloadAnemometer.temperature = (float) anemometer.temperature();

    //         g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
    //         g_rf69.send((const uint8_t*) &g_payloadAnemometer, sizeof(PayloadAnemometer) );
    //         if( g_rf69.waitPacketSent() )
    //         {
    //             EmonSerial::PrintAnemometerPayload(&g_payloadAnemometer);
    //         }
    //         else
    //         {
    //             Serial.println(F("No packet sent"));
    //         }
    //         g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

    //         // Serial.print("WIND SPEED=");
    //         // Serial.print(anemometer.windSpeed());
    //         // Serial.print(" WIND DIRECTION=");
    //         // Serial.print((anemometer.windDirection()+130)%360);
    //         // Serial.print(" TEMPERATURE=");
    //         // Serial.println(anemometer.temperature());

    //         digitalWrite(MOTEINO_LED, LOW );
    //     }
    // }
}