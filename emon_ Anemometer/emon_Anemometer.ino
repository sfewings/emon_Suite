////////////////////////////////////////////
#include <SoftwareSerial.h>
#include <TinyGPS++.h>
#include <TinyGPSPlus.h>

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
#define UART_PCB_LED 7          //LED on the UART to RS232 breakout board
#define SEND_INTERVAL_MS 2000   //send at least every 2 seconds. Data is currently received at ~5Hz
#define SERIAL_BUF_LEN 200

PayloadAnemometer g_payloadAnemometer;

// The TinyGPSPlus object
TinyGPSPlus anemometer;
TinyGPSCustom windDirection(anemometer, "WIMWV", 1);   // $WIMWV sentence, 1st element
TinyGPSCustom windSpeed(anemometer, "WIMWV", 3);       // $WIMWV sentence, 3rd element
TinyGPSCustom temperature(anemometer, "YXXDR", 2);     // $YXXDR sentence, 2nd element

SoftwareSerial ss(3,4); // rx, tx

RH_RF69 g_rf69;

////////////////////////////////////////////////

void setup()
{
    pinMode(MOTEINO_LED, OUTPUT);     
    digitalWrite(MOTEINO_LED, HIGH );
    pinMode(UART_PCB_LED, OUTPUT);
    digitalWrite(UART_PCB_LED, HIGH);

    Serial.begin(9600);
    
    Serial.println(F("Emon anemometer start"));
    Serial.print(F("Using TinyGPSPlus library version ")); 
    Serial.println(TinyGPSPlus::libraryVersion());


    if (!g_rf69.init())
        Serial.println(F("rf69 init failed"));
    if (!g_rf69.setFrequency(NETWORK_FREQUENCY))
        Serial.println(F("rf69 setFrequency failed"));
    // The encryption key has to be the same as the one in the client
    uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    g_rf69.setEncryptionKey(key);
    g_rf69.setHeaderId(ANEMOMETER_NODE);
    g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
    //when using the RH_RF69 driver with the RFM69HW module, you must setTxPowercan with isHigherPowerModule set to true
    //Otherwise, the library will not set the PA_BOOST pin high and the module will not transmit
    g_rf69.setTxPower(13,true);

    Serial.print(F("RF69 initialise node: "));
    Serial.print(ANEMOMETER_NODE);
    Serial.print(F(" Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println(F("MHz"));

    //initialise the EEPROMSettings for relay and node number
    EEPROMSettings eepromSettings;
    EmonEEPROM::ReadEEPROMSettings(eepromSettings);
    EmonEEPROM::PrintEEPROMSettings(Serial, eepromSettings);
    memset(&g_payloadAnemometer, 0, sizeof(g_payloadAnemometer));
    g_payloadAnemometer.subnode = eepromSettings.subnode;
    
    ss.begin( 4800 );

    delay(1000);
    
    digitalWrite(MOTEINO_LED, LOW );
    digitalWrite(UART_PCB_LED, LOW );
}

void loop()
{
    static unsigned long lastSendTime = millis();
    static bool receivedData = false;  //true if we are getting any data from the anemometer
    bool dataToSend = false;           //true if the data received has changed and we should send it immeditely

    while (ss.available() > 0)
    {
        char c = ss.read();
        anemometer.encode(c);
        //Serial.write(c);    //write the stream stright back out
    }

    if ( windSpeed.isUpdated()  || windDirection.isUpdated() || temperature.isUpdated() )
    {
        digitalWrite(UART_PCB_LED, HIGH);
        receivedData = true;
        if( atof(windSpeed.value())     != g_payloadAnemometer.windSpeed || 
            atof(windDirection.value()) != g_payloadAnemometer.windDirection  || 
            atof(temperature.value())   != g_payloadAnemometer.temperature )
        {
            g_payloadAnemometer.windSpeed = atof(windSpeed.value());
            g_payloadAnemometer.windDirection = atof(windDirection.value());
            g_payloadAnemometer.temperature = atof(temperature.value());
            dataToSend = true;
         }
    }

    //we only send data if we are still receiving something from the anemometer and either the data has changed or the send interval has elapsed
    // this prevents us sending packets if the anemoeter is not working and flooding the network with unchanged data
    if( receivedData && 
        (dataToSend || (millis() - lastSendTime) >= SEND_INTERVAL_MS ) )
    {
        digitalWrite(MOTEINO_LED, HIGH );
        lastSendTime = millis();

        dataToSend = false;

        ss.stopListening();
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
        ss.listen();
        digitalWrite(MOTEINO_LED, LOW );
    }

    digitalWrite(UART_PCB_LED, LOW);
}