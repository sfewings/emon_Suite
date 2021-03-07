/**
  Particulate matter sensor firmware for D1 Mini (ESP8266) and PMS5003

  Read from a Plantower PMS5003 particulate matter sensor using a Wemos D1
  Mini (or other ESP8266-based board) and report the values to an MQTT
  broker and to the serial console. Also optionally show them on a 128x32
  I2C OLED display, with a mode button to change between display modes.

  External dependencies. Install using the Arduino library manager:
     "Adafruit GFX Library" by Adafruit
     "Adafruit SSD1306" by Adafruit
     "PubSubClient" by Nick O'Leary

  Bundled dependencies. No need to install separately:
     "PMS Library" by Mariusz Kacki, forked by SwapBap

  Written by Jonathan Oxer for www.superhouse.tv
    https://github.com/superhouse/AirQualitySensorD1Mini

  Inspired by https://github.com/SwapBap/WemosDustSensor/

  Copyright 2020 SuperHouse Automation Pty Ltd www.superhouse.tv
*/
#define VERSION "2.6"
/*--------------------------- Configuration ------------------------------*/
/* Particulate Matter Sensor */
uint32_t    g_pms_warmup_period   =  30;             // Seconds to warm up PMS before reading
uint32_t    g_pms_report_period   = 120;             // Seconds between reports

/* ----------------- Hardware-specific config ---------------------- */
#define     PMS_RX_PIN              A5               // Rx from PMS (== PMS Tx)
#define     PMS_TX_PIN              A6               // Tx to PMS (== PMS Rx)
#define     PMS_BAUD_RATE         9600               // PMS5003 uses 9600bps
#define     LED                     13               // Built-in LED pin
#define     PMS_SET_PIN             A7               //The set pin for PMS unit. High is on, Low is off

/*--------------------------- Libraries ----------------------------------*/
#include <SoftwareSerial.h>           // Allows PMS to avoid the USB serial port
#include "PMS.h"                      // Particulate Matter Sensor driver (embedded)
#include <EmonShared.h>
//Radiohead RF_69 support
#include <SPI.h>
#include <RH_RF69.h>
/*--------------------------- Global Variables ---------------------------*/
// Particulate matter sensor
#define   PMS_STATE_ASLEEP        0   // Low power mode, laser and fan off
#define   PMS_STATE_WAKING_UP     1   // Laser and fan on, not ready yet
#define   PMS_STATE_READY         2   // Warmed up, ready to give data
uint8_t   g_pms_state           = PMS_STATE_WAKING_UP;
uint32_t  g_pms_state_start     = 0;  // Timestamp when PMS state last changed
uint8_t   g_pms_ae_readings_taken  = false;  // true/false: whether any readings have been taken
uint8_t   g_pms_ppd_readings_taken = false;  // true/false: whether PPD readings have been taken

uint16_t  g_pm1p0_sp_value      = 0;  // Standard Particle calibration pm1.0 reading
uint16_t  g_pm2p5_sp_value      = 0;  // Standard Particle calibration pm2.5 reading
uint16_t  g_pm10p0_sp_value     = 0;  // Standard Particle calibration pm10.0 reading

uint16_t  g_pm1p0_ae_value      = 0;  // Atmospheric Environment pm1.0 reading
uint16_t  g_pm2p5_ae_value      = 0;  // Atmospheric Environment pm2.5 reading
uint16_t  g_pm10p0_ae_value     = 0;  // Atmospheric Environment pm10.0 reading

uint32_t  g_pm0p3_ppd_value     = 0;  // Particles Per Deciliter pm0.3 reading
uint32_t  g_pm0p5_ppd_value     = 0;  // Particles Per Deciliter pm0.5 reading
uint32_t  g_pm1p0_ppd_value     = 0;  // Particles Per Deciliter pm1.0 reading
uint32_t  g_pm2p5_ppd_value     = 0;  // Particles Per Deciliter pm2.5 reading
uint32_t  g_pm5p0_ppd_value     = 0;  // Particles Per Deciliter pm5.0 reading
uint32_t  g_pm10p0_ppd_value    = 0;  // Particles Per Deciliter pm10.0 reading

uint8_t   g_uk_aqi_value        = 0;  // Air Quality Index value using UK reporting system
uint16_t  g_us_aqi_value        = 0;  // Air Quality Index value using US reporting system

RH_RF69 g_rf69;

/* -------------------------- Resources ----------------------------------*/
#include "aqi.h"                         // Air Quality Index calculations

/*--------------------------- Instantiate Global Objects -----------------*/
// Software serial port
SoftwareSerial pmsSerial(PMS_RX_PIN, PMS_TX_PIN); // Rx pin = GPIO2 (D4 on Wemos D1 Mini)

// Particulate matter sensor
PMS pms(pmsSerial);                      // Use the software serial port for the PMS
PMS::DATA g_data;
PayloadAirQuality  g_payloadAirQuality;
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


/**
  Setup
*/
void setup()
{
  pinMode(LED, OUTPUT);    

  Blink(LED, 50, 3);

  Serial.begin(9600); 
  Serial.println();
  Serial.print("Air Quality Sensor starting up, v");
  Serial.println(VERSION);
	EmonSerial::PrintAirQualityPayload(NULL);


  // Open a connection to the PMS and put it into passive mode
  pinMode(PMS_SET_PIN, OUTPUT);
  digitalWrite(PMS_SET_PIN,HIGH);
  pmsSerial.begin(PMS_BAUD_RATE);   // Connection for PMS5003
  pms.passiveMode();                // Tell PMS to stop sending data automatically
  delay(100);
  pms.wakeUp();                     // Tell PMS to wake up (turn on fan and laser)


  if (!g_rf69.init())
    Serial.println("g_rf69 init failed");
  // Defaults after init are 434.0MHz, modulation GFSK_Rb250Fd250, +13dbM (for low power module)
  // No encryption
  if (!g_rf69.setFrequency(915.0))
    Serial.println("setFrequency failed");
  g_rf69.setHeaderId(AIRQUALITY_NODE);

  // If you are using a high power g_rf69 eg RFM69HW, you *must* set a Tx power with the
  // ishighpowermodule flag set like this:
  //g_rf69.setTxPower(14, true);

  // The encryption key has to be the same as the one in the client
  uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
  g_rf69.setEncryptionKey(key);
  
}

/**
  Main loop
*/
void loop()
{
/**
  Update particulate matter sensor values
*/
  uint32_t time_now = millis();

  // Check if we've been in the sleep state for long enough
  if (PMS_STATE_ASLEEP == g_pms_state)
  {
    if (time_now - g_pms_state_start
        >= ((g_pms_report_period * 1000) - (g_pms_warmup_period * 1000)))
    {
      // It's time to wake up the sensor
      Serial.println("Waking up sensor");
      digitalWrite(PMS_SET_PIN,HIGH);
      delay(5);

      pms.wakeUp();
      g_pms_state_start = time_now;
      g_pms_state = PMS_STATE_WAKING_UP;
    }
  }

  // Check if we've been in the waking up state for long enough
  if (PMS_STATE_WAKING_UP == g_pms_state)
  {
    if (time_now - g_pms_state_start
        >= (g_pms_warmup_period * 1000))
    {
      g_pms_state_start = time_now;
      g_pms_state = PMS_STATE_READY;
    }
  }

  // Put the most recent values into globals for reference elsewhere
  if (PMS_STATE_READY == g_pms_state)
  {
    //pms.requestRead();
    Serial.println("Reading sensor");
    if (pms.readUntil(g_data))  // Use a blocking road to make sure we get values
    {
      g_pm1p0_sp_value   = g_data.PM_SP_UG_1_0;
      g_pm2p5_sp_value   = g_data.PM_SP_UG_2_5;
      g_pm10p0_sp_value  = g_data.PM_SP_UG_10_0;

      g_pm1p0_ae_value   = g_data.PM_AE_UG_1_0;
      g_pm2p5_ae_value   = g_data.PM_AE_UG_2_5;
      g_pm10p0_ae_value  = g_data.PM_AE_UG_10_0;

      g_pms_ae_readings_taken = true;

      // This condition below should NOT be required, but currently I get all
      // 0 values for the PPD results every second time. This check only updates
      // the global values if there is a non-zero result for any of the values:
      if (g_data.PM_TOTALPARTICLES_0_3 + g_data.PM_TOTALPARTICLES_0_5
          + g_data.PM_TOTALPARTICLES_1_0 + g_data.PM_TOTALPARTICLES_2_5
          + g_data.PM_TOTALPARTICLES_5_0 + g_data.PM_TOTALPARTICLES_10_0
          != 0)
      {
        g_pm0p3_ppd_value  = g_data.PM_TOTALPARTICLES_0_3;
        g_pm0p5_ppd_value  = g_data.PM_TOTALPARTICLES_0_5;
        g_pm1p0_ppd_value  = g_data.PM_TOTALPARTICLES_1_0;
        g_pm2p5_ppd_value  = g_data.PM_TOTALPARTICLES_2_5;
        g_pm5p0_ppd_value  = g_data.PM_TOTALPARTICLES_5_0;
        g_pm10p0_ppd_value = g_data.PM_TOTALPARTICLES_10_0;

        g_payloadAirQuality.pm0p3  = g_data.PM_TOTALPARTICLES_0_3;
        g_payloadAirQuality.pm0p5  = g_data.PM_TOTALPARTICLES_0_5;
        g_payloadAirQuality.pm1p0  = g_data.PM_TOTALPARTICLES_1_0;
        g_payloadAirQuality.pm2p5  = g_data.PM_TOTALPARTICLES_2_5;
        g_payloadAirQuality.pm5p0  = g_data.PM_TOTALPARTICLES_5_0;
        g_payloadAirQuality.pm10p0 = g_data.PM_TOTALPARTICLES_10_0;

        g_pms_ppd_readings_taken = true;
      }
      Serial.println("Sleeping sensor");
      pms.sleep();
      digitalWrite(PMS_SET_PIN,LOW);

      // Calculate AQI values for the various reporting standards
      //calculateUkAqi();

      // Report the new values
      //reportToMqtt();
      reportToSerial();
      if( g_pms_ppd_readings_taken )
      {
        g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
        g_rf69.send((const uint8_t*) &g_payloadAirQuality, sizeof(g_payloadAirQuality));
        if( g_rf69.waitPacketSent() )
        {
          EmonSerial::PrintAirQualityPayload(&g_payloadAirQuality);
        }
        else
        {
          Serial.println(F("No packet sent"));
        }
        g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
      }

      g_pms_state_start = time_now;
      g_pms_state = PMS_STATE_ASLEEP;
    }
  }
}

/**
  Report the latest values to the serial console
*/
void reportToSerial()
{
  if (true == g_pms_ae_readings_taken)
  {
    /* Report PMSPC1.0 AE value */
    Serial.print("PMSPC1:");
    Serial.println(String(g_pm1p0_sp_value));

    /* Report PM2.5 AE value */
    Serial.print("PMSPC2.5:");
    Serial.println(String(g_pm2p5_sp_value));

    /* Report PM10.0 AE value */
    Serial.print("PMSPC10:");
    Serial.println(String(g_pm10p0_sp_value));



    /* Report PM1.0 AE value */
    Serial.print("PM1:");
    Serial.println(String(g_pm1p0_ae_value));

    /* Report PM2.5 AE value */
    Serial.print("PM2.5:");
    Serial.println(String(g_pm2p5_ae_value));

    /* Report PM10.0 AE value */
    Serial.print("PM10:");
    Serial.println(String(g_pm10p0_ae_value));
  }

  if (true == g_pms_ppd_readings_taken)
  {
    /* Report PM0.3 PPD value */
    Serial.print("PPD0.3:");
    Serial.println(String(g_pm0p3_ppd_value));

    /* Report PM0.5 PPD value */
    Serial.print("PPD0.5:");
    Serial.println(String(g_pm0p5_ppd_value));

    /* Report PM1.0 PPD value */
    Serial.print("PPD1:");
    Serial.println(String(g_pm1p0_ppd_value));

    /* Report PM2.5 PPD value */
    Serial.print("PPD2.5:");
    Serial.println(String(g_pm2p5_ppd_value));

    /* Report PM5.0 PPD value */
    Serial.print("PPD5:");
    Serial.println(String(g_pm5p0_ppd_value));

    /* Report PM10.0 PPD value */
    Serial.print("PPD10:");
    Serial.println(String(g_pm10p0_ppd_value));

    /* Report UK AQI value */
    Serial.print("UKAQI:");
    Serial.println(String(g_uk_aqi_value));
  }
  else
  {
    Serial.println("No valid reading taken");
  }
}