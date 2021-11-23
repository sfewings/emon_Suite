// See https://github.com/pierremolinaro/acan2515
//——————————————————————————————————————————————————————————————————————————————
//  ACAN2515 Demo in loopback mode
//——————————————————————————————————————————————————————————————————————————————

#include <ACAN2515.h>

//——————————————————————————————————————————————————————————————————————————————
//  MCP2515 connections:
//    - standard SPI pins for SCK, MOSI and MISO
//    - a digital output for CS
//    - interrupt input pin for INT
//——————————————————————————————————————————————————————————————————————————————
// If you use CAN-BUS shield (http://wiki.seeedstudio.com/CAN-BUS_Shield_V2.0/) with Arduino Uno,
// use B connections for MISO, MOSI, SCK, #9 or #10 for CS (as you want),
// #2 or #3 for INT (as you want).
//——————————————————————————————————————————————————————————————————————————————
// Error codes and possible causes:
//    In case you see "Configuration error 0x1", the Arduino doesn't communicate
//       with the 2515. You will get this error if there is no CAN shield or if
//       the CS pin is incorrect. 
//    In case you see succes up to "Sent: 17" and from then on "Send failure":
//       There is a problem with the interrupt. Check if correct pin is configured
//——————————————————————————————————————————————————————————————————————————————

static const byte MCP2515_CS  =  9 ; // CS input of MCP2515 (adapt to your design) 
static const byte MCP2515_INT =  2 ; // INT output of MCP2515 (adapt to your design)
static const byte MCP2515_CS_2=  8 ; // CS input of MCP2515 (adapt to your design) 
static const byte MCP2515_INT_2 =  1 ; // INT output of MCP2515 (adapt to your design)

//——————————————————————————————————————————————————————————————————————————————
//  MCP2515 Driver object
//——————————————————————————————————————————————————————————————————————————————

ACAN2515 can (MCP2515_CS, SPI, MCP2515_INT) ;
ACAN2515 can2 (MCP2515_CS_2, SPI, MCP2515_INT) ;

//——————————————————————————————————————————————————————————————————————————————
//  MCP2515 Quartz: adapt to your design
//——————————————————————————————————————————————————————————————————————————————

static const uint32_t QUARTZ_FREQUENCY = 8UL * 1000UL * 1000UL ; // 8 MHz

//——————————————————————————————————————————————————————————————————————————————
//   SETUP
//——————————————————————————————————————————————————————————————————————————————

void setup () {
//--- Switch on builtin led
  pinMode (LED_BUILTIN, OUTPUT) ;
  digitalWrite (LED_BUILTIN, HIGH) ;
//--- Start serial
  Serial.begin (9600);
//--- Wait for serial (blink led at 10 Hz during waiting)
  while (!Serial) {
    delay (50) ;
    digitalWrite (LED_BUILTIN, !digitalRead (LED_BUILTIN)) ;
  }
//--- Begin SPI
  SPI.begin () ;
//--- Configure ACAN2515
  Serial.println ("Configure ACAN2515") ;
  ACAN2515Settings settings (QUARTZ_FREQUENCY, 500UL * 1000UL) ; // CAN bit rate 500 kb/s
  settings.mRequestedMode = ACAN2515Settings::LoopBackMode ; // Select loopback mode
  uint16_t errorCode = can2.begin (settings, [] { can2.isr () ; }) ;
  if (errorCode == 0) {
    Serial.print ("Bit Rate prescaler: ") ;
    Serial.println (settings.mBitRatePrescaler) ;
    Serial.print ("Propagation Segment: ") ;
    Serial.println (settings.mPropagationSegment) ;
    Serial.print ("Phase segment 1: ") ;
    Serial.println (settings.mPhaseSegment1) ;
    Serial.print ("Phase segment 2: ") ;
    Serial.println (settings.mPhaseSegment2) ;
    Serial.print ("SJW: ") ;
    Serial.println (settings.mSJW) ;
    Serial.print ("Triple Sampling: ") ;
    Serial.println (settings.mTripleSampling ? "yes" : "no") ;
    Serial.print ("Actual bit rate: ") ;
    Serial.print (settings.actualBitRate ()) ;
    Serial.println (" bit/s") ;
    Serial.print ("Exact bit rate ? ") ;
    Serial.println (settings.exactBitRate () ? "yes" : "no") ;
    Serial.print ("Sample point: ") ;
    Serial.print (settings.samplePointFromBitStart ()) ;
    Serial.println ("%") ;
  }else{
    Serial.print ("Configuration error 0x") ;
    Serial.println (errorCode, HEX) ;
  }

  Serial.println ("Configure ACAN2515 2") ;
  errorCode = can.begin (settings, [] { can.isr () ; }) ;
  if (errorCode == 0) {
    Serial.print ("Bit Rate prescaler: ") ;
    Serial.println (settings.mBitRatePrescaler) ;
    Serial.print ("Propagation Segment: ") ;
    Serial.println (settings.mPropagationSegment) ;
    Serial.print ("Phase segment 1: ") ;
    Serial.println (settings.mPhaseSegment1) ;
    Serial.print ("Phase segment 2: ") ;
    Serial.println (settings.mPhaseSegment2) ;
    Serial.print ("SJW: ") ;
    Serial.println (settings.mSJW) ;
    Serial.print ("Triple Sampling: ") ;
    Serial.println (settings.mTripleSampling ? "yes" : "no") ;
    Serial.print ("Actual bit rate: ") ;
    Serial.print (settings.actualBitRate ()) ;
    Serial.println (" bit/s") ;
    Serial.print ("Exact bit rate ? ") ;
    Serial.println (settings.exactBitRate () ? "yes" : "no") ;
    Serial.print ("Sample point: ") ;
    Serial.print (settings.samplePointFromBitStart ()) ;
    Serial.println ("%") ;
  }else{
    Serial.print ("Configuration error 0x") ;
    Serial.println (errorCode, HEX) ;
  }
}

//----------------------------------------------------------------------------------------------------------------------

static uint32_t gBlinkLedDate = 0 ;
static uint32_t gReceivedFrameCount = 0 ;
static uint32_t gSentFrameCount = 0 ;

//——————————————————————————————————————————————————————————————————————————————

void loop () {
  CANMessage frame ;
  // if (gBlinkLedDate < millis ()) {
  //   gBlinkLedDate += 2000 ;
  //   digitalWrite (LED_BUILTIN, !digitalRead (LED_BUILTIN)) ;
  //   const bool ok = can.tryToSend (frame) ;
  //   if (ok) {
  //     gSentFrameCount += 1 ;
  //     Serial.print ("Sent: ") ;
  //     Serial.println (gSentFrameCount) ;
  //   }else{
  //     Serial.println ("Send failure") ;
  //   }
  // }
  if (can.available ()) {
    can.receive (frame) ;
    gReceivedFrameCount ++ ;
    Serial.print ("Received 1: ") ;
    Serial.println (gReceivedFrameCount) ;
  }

  if (can2.available ()) {
    can2.receive (frame) ;
    gReceivedFrameCount ++ ;
    Serial.print ("Received 2: ") ;
    Serial.println (gReceivedFrameCount) ;
  }
}

//——————————————————————————————————————————————————————————————————————————————



// #include <CanBusMCP2515_asukiaaa.h>
// #ifndef PIN_CS
// #define PIN_CS 9
// #endif
// #ifndef PIN_INT
// #define PIN_INT 2
// #endif
//
// See https://github.com/asukiaaa/CanBusMCP2515-arduino
//
// static const auto QUARTZ_FREQUENCY =
//     CanBusMCP2515_asukiaaa::QuartzFrequency::MHz8;
// static const auto BITRATE = CanBusMCP2515_asukiaaa::BitRate::Kbps500;
// #ifndef CAN_ID
// #define CAN_ID 3000
// #endif

// CanBusMCP2515_asukiaaa::Driver canCar(9);
// CanBusMCP2515_asukiaaa::Driver canEV(8);

// bool initCAN(CanBusMCP2515_asukiaaa::Driver& can)
// {
//   CanBusMCP2515_asukiaaa::Settings settings(QUARTZ_FREQUENCY, BITRATE);
//   Serial.print("settings for :");Serial.println(can.CS());
//   Serial.println(settings.toString());

//   while (true) {
//     uint16_t errorCode = can.begin(settings);
//     if (errorCode == 0) {
//       Serial.println("can.begin() success");
//       break;
//     } else {
//       Serial.print("can.begin() failed: ");
//       Serial.println(errorCode);
//       delay(1000);
//     }

//     if (errorCode == 0) break;
//     Serial.print("Configuration error: ");
//     Serial.println(CanBusMCP2515_asukiaaa::Error::toString(errorCode));
//     delay(1000);
//   }
//   Serial.println("Succeeced in beginning");
// }

// void setup() {
//   Serial.begin(9600);

//   initCAN( canEV );
//   //initCAN( canCar );
//  }

// void loop() 
// {
//   static uint8_t i = 0;

//   // static unsigned long trySendAt = 0;
//   // static const unsigned long intervalMs = 1000UL;
//   // // if (trySendAt == 0 || millis() - trySendAt > intervalMs) {
//   //   trySendAt = millis();
//   //   CanBusData_asukiaaa::Frame frame;
//   //   frame.id = CAN_ID;
//   //   frame.ext = frame.id > 2048;
//   //   frame.data64 = millis();
//   //   // frame.idx = frame.data64 % 3;
//   //   const bool ok = can.tryToSend(frame);
//   //   Serial.println("Sent");
//   //   Serial.println(frame.toString());
//   //   Serial.print(ok ? "Succeeded" : "Failed");
//   //   Serial.print(" at ");
//   //   Serial.println(trySendAt);
//   // }
//   // if (canCar.available()) {
//   //   CanBusData_asukiaaa::Frame frame;
//   //   canCar.receive(&frame);
//   //   Serial.print("canCar: ");
//   //   Serial.print(frame.id,HEX);
//   //   Serial.print(":");
//   //   Serial.println(frame.toString());
//   //   i=0;
//   // }
//   // else
//   // {
//   //   i++;
//   // }

//   if (canEV.available()) {
//     CanBusData_asukiaaa::Frame frame;
//     canEV.receive(&frame);
//     Serial.print("canEV: ");
//     Serial.print(frame.id,HEX);
//     Serial.print(":");
//     Serial.println(frame.toString());
//     i=0;
//   }
//   else
//   {
//     i++;
//   }

//   if(i >=100)
//   {
//     i = 0;
//     Serial.println(".");
//   }
//   delay(10);
// }


// // see https://ev-olution.yolasite.com/CANa.php for more info

// #include <mcp_can.h>
// #include <SPI.h>
// //#include <LiquidCrystal.h>

// //const int rs = 8, en = 7, d4 = 6, d5 = 5, d6 = 4, d7 = 3;
// //LiquidCrystal lcd(rs, en, d4, d5, d6, d7);

// long unsigned int rxId;
// unsigned char len = 0;
// unsigned char rxBuf[8];

// long LCDInterval = 500;        // First and second screen update interval
// long LCD3Interval = 500;       // Third screen update interval
// long LCD4Interval = 2000;      // Forth screen update interval
// long CANInterval = 500;        // 0x79b message repeat interval in case of unsuccessful previous attempts
// long LCDMillis = 0;            // for LCD screen update
// long LCD3Millis = 0;           // for LCD third screen update
// long LCD4Millis = 0;           // for LCD forth screen update 
// long CANMillis = 0;            // for 0x79b message repeat
// float BattVolts;               // Main battery voltage
// uint16_t Soc;                  // Gids
// uint16_t ActSoc;               // Actual state of charge
// int16_t Amp;                   
// float SocPct;                  // Gids in percentage
// float ActSocPct;               // Acual state of charge in percentages 
// float Amps;                    // Main battery current
// float kWh;                     // Energy left in main batery
// float kW;                      // Power used from main battery
// int BattTemp1;                 // Battery temperature sensor 1 
// int BattTemp2;                 // Battery temperature sensor 2
// int BattTemp3;                 // Battery temperature sensor 3
// int BattTemp4;                 // Battery temperature sensor 4
// int ScSt = 0;                  // Screen page state
// int CANSt = 0;
// uint16_t CPVmin,CPVmax,CPVdiff;// cell pair min/max/diff voltage (mV)
// uint8_t RcvFrIdx;

// #define MAX_SOC 281.0F
// #define CAN0_INT 3             // Set INT to pin 3
// MCP_CAN CAN0(9);              // Set CS to pin 9
// #define KW_FACTOR 74.73F       // Some people prefer 80

// void setup() 
// {
//   //pinMode(9, INPUT_PULLUP);
  
//   // lcd.begin(16, 2);
//   // lcd.print(" EV-OLUTION.NET");
//   // lcd.setCursor(0, 1);
//   // lcd.print("CANa Ver: 1.3");
//   // delay (2000);

//  	Serial.begin(9600);
// 	delay(500);
  
//   // Initialize MCP2515 running at 8MHz with a baudrate of 500kb/s and the masks and filters disabled.
//   // Change MCP_8MHZ to MCP_16 MHZ if your MCP2515 board is equiped with 16MHZ crystal!!!

//   if (CAN0.begin(MCP_STDEXT, CAN_500KBPS, MCP_8MHZ) == CAN_OK)
//   {
//     Serial.println("MCP2515 Init success");
//     delay(1000);
//   }
//   else
//   {
//     Serial.println("MCP2515 Init fail");
//     delay(1000);
//   }
//   CAN0.init_Mask(0, 0, 0x07ff0000);
//   CAN0.init_Filt(0, 0, 0x07bb0000);
//   CAN0.init_Filt(1, 0, 0x07bb0000);

//   CAN0.init_Mask(1, 0, 0x07ff0000);
//   CAN0.init_Filt(2, 0, 0x01db0000);
//   CAN0.init_Filt(3, 0, 0x055b0000); 
//   CAN0.init_Filt(4, 0, 0x05bc0000); 
//   CAN0.init_Filt(5, 0, 0x05bc0000); 
//   CAN0.setMode(MCP_NORMAL);

//   pinMode(CAN0_INT, INPUT);
// }

// void loop() 
// {
//   if (digitalRead(CAN0_INT))
//   {
//     CAN0.readMsgBuf(&rxId, &len, rxBuf);
//     Serial.print("  CAN0 ID: ");Serial.print(rxId, HEX);
//     Serial.print(",LEN: ");Serial.print(len);
//     for(int i =0; i<len; i++)
//     {
//       Serial.print(", ");Serial.print(rxBuf[i], HEX);
//     }
//     Serial.println();  
//   }
//   //if(CAN0.checkReceive())
//   {
//     CAN0.readMsgBuf(&rxId, &len, rxBuf);
//     Serial.print("  CAN0 ID: ");Serial.print(rxId, HEX);
//     Serial.print(",LEN: ");Serial.print(len);
//     for(int i =0; i<len; i++)
//     {
//       Serial.print(", ");Serial.print(rxBuf[i], HEX);
//     }
//     Serial.println();
//   }
//   if(CAN0.checkError())
//   {
//     Serial.print("  CAN0 Error : ");
//     Serial.print(CAN0.getError());
//     Serial.print(", error count : ");
//     Serial.println(CAN0.errorCountRX());
//   }
//   if
// }
