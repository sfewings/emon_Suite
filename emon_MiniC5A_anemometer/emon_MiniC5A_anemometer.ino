// Mini-C5A Modbus RTU reader - reads 5 registers starting at 0x0000 from slave addr 0x01
// Parses registers (0..4) into windSpeed, windDirection, temperature, humidity, pressure.
// Adjust scaling constants to match your sensor's register scaling.
#include <SoftwareSerial.h>

#include <EmonShared.h>
#include <RH_RF69.h>

//#define HOME_NETWORK
#define BOAT_NETWORK
#ifdef BOAT_NETWORK
	#define NETWORK_FREQUENCY 914.0
#elif defined( HOME_NETWORK )
	#define NETWORK_FREQUENCY 915.0
#endif


const uint8_t MOTEINO_LED = 9;	// LED on Moteino
SoftwareSerial rs232Serial(3,4); // rx, tx

const unsigned long BAUD_RS232 = 9600;  // Mini-C5A RS232 baud

const uint8_t MODBUS_ADDR = 0x01;
const uint8_t MODBUS_FN_READ = 0x03;
const uint16_t MODBUS_REG_START = 0x0000;
const uint16_t MODBUS_REG_COUNT = 5;

const unsigned long SEND_WIND_INTERVAL_MS = 1000; // ms
const unsigned long RESPONSE_TIMEOUT = 500;  // ms
const unsigned long SEND_PRESSURE_INTERVAL_MS = 5000; // send pressure data at least every 5 seconds

unsigned long lastSendWindTime;
unsigned long lastSendPressureTime;

// scaling as in the Mini C5A datasheet
const float SCALE_WIND_SPEED = 0.01f; // register value * 0.01 -> m/s
const float SCALE_WIND_DIR   = 1.0f; // degrees
const float SCALE_TEMPERATURE= 0.1f; // degC
const float SCALE_HUMIDITY   = 0.1f; // %RH
const float SCALE_PRESSURE   = 0.1f; // hPa or other unit

// storage
float windSpeed = NAN, windDirection = NAN, temperature = NAN, humidity = NAN, pressure = NAN;

PayloadPressure g_payloadPressure;
PayloadAnemometer g_payloadAnemometer;

RH_RF69 g_rf69;


void flashErrorToLED(int error, bool haltExecution = false)
{
  do
  { 
    for( int i = 0; i < error; i++)
    {
      digitalWrite(MOTEINO_LED, HIGH);
      delay(100);
      digitalWrite(MOTEINO_LED, LOW);
      delay(100);
    }
	delay(1000);
  }
  while( haltExecution );
}


uint16_t modbus_crc16(const uint8_t *buf, uint16_t len)
{
    uint16_t crc = 0xFFFF;
    for (uint16_t pos = 0; pos < len; pos++) 
    {
        crc ^= (uint16_t)buf[pos];
        for (int i = 0; i < 8; i++) 
        {
            if (crc & 0x0001) crc = (crc >> 1) ^ 0xA001;
            else crc >>= 1;
        }
    }
    return crc;
}

// build and send Modbus RTU read request for registers START..START+COUNT-1
void sendReadRequest()
{
    uint8_t req[8];
    req[0] = MODBUS_ADDR;
    req[1] = MODBUS_FN_READ;
    req[2] = (MODBUS_REG_START >> 8) & 0xFF;
    req[3] = MODBUS_REG_START & 0xFF;
    req[4] = (MODBUS_REG_COUNT >> 8) & 0xFF;
    req[5] = MODBUS_REG_COUNT & 0xFF;
    uint16_t crc = modbus_crc16(req, 6);
    req[6] = crc & 0xFF;       // CRC low
    req[7] = (crc >> 8) & 0xFF; // CRC high

    rs232Serial.write(req, 8);
}

// Attempt to read a Modbus RTU response for the last request.
// Blocks up to RESPONSE_TIMEOUT ms while collecting bytes.
// Returns true if a valid frame was parsed.
bool readResponseAndParse()
{
    const uint8_t expectedByteCount = MODBUS_REG_COUNT * 2; // 10
    const uint8_t expectedLen = 1 + 1 + 1 + expectedByteCount + 2; // addr+func+bytecount+data+crc

    uint8_t buf[64];
    uint8_t pos = 0;
    unsigned long start = millis();

    while (millis() - start < RESPONSE_TIMEOUT) 
    {
        while (rs232Serial.available() && pos < sizeof(buf)) 
        {
            buf[pos++] = (uint8_t)rs232Serial.read();
        }
        if (pos >= expectedLen) 
            break;
    }

    if (pos < expectedLen) 
        return false;

    // Try to find a valid frame inside buf (sliding window)
    for (uint8_t offset = 0; offset + expectedLen <= pos; ++offset) 
    {
        uint8_t *p = buf + offset;
        if (p[0] != MODBUS_ADDR) 
            continue;
        if (p[1] != MODBUS_FN_READ) 
            continue;
        if (p[2] != expectedByteCount) 
            continue;
        uint16_t crc_calc = modbus_crc16(p, 3 + expectedByteCount);
        uint16_t crc_recv = (uint16_t)p[3 + expectedByteCount] | ((uint16_t)p[3 + expectedByteCount + 1] << 8);
        if (crc_calc != crc_recv) 
            continue;

        // parse registers
        for (uint8_t i = 0; i < MODBUS_REG_COUNT; ++i) 
        {
            uint8_t hi = p[3 + i*2];
            uint8_t lo = p[3 + i*2 + 1];
            uint16_t reg = ((uint16_t)hi << 8) | lo;
            switch (i) 
            {
                case 0: windSpeed = reg * SCALE_WIND_SPEED; break;
                case 1: windDirection   = reg * SCALE_WIND_DIR;   break;
                case 2: temperature = (int16_t)reg * SCALE_TEMPERATURE; break; // cast if signed
                case 3: humidity = reg * SCALE_HUMIDITY; break;
                case 4: pressure = reg * SCALE_PRESSURE; break;
            }
        }
        return true;
    }

    return false;
}

void printValues()
{
    Serial.print(millis()); Serial.print(", ");
    Serial.print("WSPD=");
    if (isnan(windSpeed)) 
        Serial.print("NaN"); 
    else 
        Serial.print(windSpeed, 2);
    
    Serial.print(", WDIR=");
    if (isnan(windDirection)) 
        Serial.print("NaN"); 
    else 
        Serial.print(windDirection, 1);

    Serial.print(", TEMP=");
    if (isnan(temperature)) 
        Serial.print("NaN"); 
    else 
        Serial.print(temperature, 2);

    Serial.print(", HUM=");
    if (isnan(humidity)) 
        Serial.print("NaN"); 
    else 
        Serial.print(humidity, 2);
    
    Serial.print(", PRES=");
    if (isnan(pressure)) 
        Serial.print("NaN"); 
    else 
        Serial.print(pressure, 2);
    Serial.println();
}

void setup()
{
    pinMode(MOTEINO_LED, OUTPUT);     
    digitalWrite(MOTEINO_LED, HIGH );
    Serial.begin(9600);

    rs232Serial.begin(BAUD_RS232);
    Serial.println(F("Mini-C5A Modbus RTU reader starting"));

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
    //g_rf69.setTxPower(13,true);
    Serial.print(F("RF69 initialise node: "));
    Serial.print(ANEMOMETER_NODE);
    Serial.print(F(" Freq: "));Serial.print(NETWORK_FREQUENCY,1); Serial.println(F("MHz"));

    memset(&g_payloadAnemometer, 0, sizeof(g_payloadAnemometer));
    g_payloadAnemometer.subnode = 1;
    memset(&g_payloadPressure, 0, sizeof(g_payloadPressure));
    g_payloadPressure.subnode = 1;
    EmonSerial::PrintPressurePayload(NULL);
    EmonSerial::PrintAnemometerPayload(NULL);

    lastSendWindTime = 0;
    lastSendWindTime = millis();
    lastSendPressureTime = millis();
    
    digitalWrite(MOTEINO_LED, LOW );
}

void loop()
{
  unsigned long now = millis();
  if (now - lastSendWindTime >= SEND_WIND_INTERVAL_MS) 
  {
    lastSendWindTime = now;
    // send request
    sendReadRequest();
    // read and parse response
    if (readResponseAndParse()) 
    {
        //printValues();

        lastSendWindTime = now;

        digitalWrite(MOTEINO_LED, HIGH );
        rs232Serial.stopListening();
        g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);

        g_payloadAnemometer.windSpeed = windSpeed;      // m/s
        g_payloadAnemometer.windDirection = windDirection;          // degrees
        g_payloadAnemometer.temperature = temperature;  // degree celcius

        g_rf69.send((const uint8_t*) &g_payloadAnemometer, sizeof(PayloadAnemometer) );
        if( g_rf69.waitPacketSent() )
        {
            EmonSerial::PrintAnemometerPayload(&g_payloadAnemometer);
        }
        else
        {
            Serial.println(F("No packet sent"));
        }

        //send the pressure readings less regularly
        if( (now - lastSendPressureTime) >= SEND_PRESSURE_INTERVAL_MS )
        {
            lastSendPressureTime = now;
            // send pressure packet
            g_payloadPressure.pressure = pressure;
            g_payloadPressure.humidity = humidity;
            g_payloadPressure.temperature = temperature;


            g_rf69.send((const uint8_t*) &g_payloadPressure, sizeof(PayloadPressure) );
            if( g_rf69.waitPacketSent() )
            {
                EmonSerial::PrintPressurePayload(&g_payloadPressure);
            }
            else
            {
                Serial.println(F("No packet sent"));
            }
        }
        
        g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
        rs232Serial.listen();
        digitalWrite(MOTEINO_LED, LOW );
    } 
    else 
    {
        Serial.println(F("No valid Modbus response"));
        flashErrorToLED(3);
    }
  }

  // small idle delay
  delay(10);
}