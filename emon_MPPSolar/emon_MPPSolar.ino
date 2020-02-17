#define RF69_COMPAT 1

//#define __MOTEINO_AVR_ATmega1284__
#include <JeeLib.h>			// ports and RFM12 - used for RFM12B wireless
#include <SoftwareSerial.h>
#include <EmonShared.h>
#include <RF69_avr.h>  // for SPI_SCK, SPI_SS, SPI_MOSI & SPI_MISO

/*
Note. To make the Jeelib RFM69 work witht he Moteino Mega 1284p two changes need to be made to the jeelib libraries
1. The SPI pin assignement for __
in RF69_avr.h add the following definition for SPI pins
  #elif defined(__AVR_ATmega1284P__) //Moteino mega

  #define SS_DDR      DDRB
  #define SS_PORT     PORTB
  #define SS_BIT      4     // PB4    D4

  #define SPI_SS      4     // PB4    D4
  #define SPI_MOSI    5     // PB5    D5
  #define SPI_MISO    6     // PB6    D6
  #define SPI_SCK     7     // PB7    D7

  static void spiConfigPins () {
      SS_PORT |= _BV(SS_BIT);
      SS_DDR |= _BV(SS_BIT);
      PORTB |= _BV(SPI_SS);
      DDRB |= _BV(SPI_SS) | _BV(SPI_MOSI) | _BV(SPI_SCK);
  }

2. In RF69.cpp rf69_initialize change the interrupt from 0 to 2
#if defined(__AVR_ATmega1284P__) //Moteino mega
        attachInterrupt(2, RF69::interrupt_compat, RISING);
#else
        attachInterrupt(0, RF69::interrupt_compat, RISING);
#endif
*/
RF12Init g_rf12Init = { INVERTER_NODE, RF12_915MHZ, FEWINGS_MONITOR_GROUP, RF69_COMPAT };

String P005GS = "\x5E\x50\x30\x30\x35\x47\x53\x58\x14\x0D"; //Query General status
String P005PI = "\x5E\x50\x30\x30\x35\x50\x49\x71\x8B\x0D"; //Query Protocol version
String P004T = "\x5E\x50\x30\x30\x34\x54\xDF\x69\x0D";      //Query Current time


PayloadInverter payloadInverter;

SoftwareSerial g_serialInverter2(14, 13);	//18,17); //A1=rx, A0=tx

#define LED_PIN 15

uint16_t cal_crc_half(uint8_t *pin, uint8_t len)
{
     uint16_t crc;

     uint8_t da;
     uint8_t *ptr;
     uint8_t bCRCHign;
     uint8_t bCRCLow;

     uint16_t crc_ta[16]=
     {
          0x0000,0x1021,0x2042,0x3063,0x4084,0x50a5,0x60c6,0x70e7,

          0x8108,0x9129,0xa14a,0xb16b,0xc18c,0xd1ad,0xe1ce,0xf1ef
     };
     ptr=pin;
     crc=0;
     
     while(len--!=0)
     {
          da=((uint8_t)(crc>>8))>>4;

          crc<<=4;

          crc^=crc_ta[da^(*ptr>>4)];

          da=((uint8_t)(crc>>8))>>4;

          crc<<=4;

          crc^=crc_ta[da^(*ptr&0x0f)];

          ptr++;
     }
     bCRCLow = crc;

    bCRCHign= (uint8_t)(crc>>8);

     if(bCRCLow==0x28||bCRCLow==0x0d||bCRCLow==0x0a)

    {
         bCRCLow++;
    }
    if(bCRCHign==0x28||bCRCHign==0x0d||bCRCHign==0x0a)

    {
          bCRCHign++;
    }
    crc = ((uint16_t)bCRCHign)<<8;
    crc += bCRCLow;
     return(crc);
}

void CreateCmdString(char* c )
{
  Serial.print(strlen(c ) );
  Serial.print(", String ");
  Serial.print( c );
  Serial.print(" = \"");
  
  uint16_t crc = cal_crc_half( c, strlen(c));
  for(int i = 0; i < strlen(c); i++ )
  {
    Serial.print("\\x");
    Serial.print(c[i], HEX);
  }
  Serial.print("\\x");
  Serial.print(((crc>>8)&0xFF),HEX);
  Serial.print("\\x");
  Serial.print((crc&0xFF),HEX);
  Serial.print("\\x0D\";");
  Serial.println();
}


int ReadFromInverter(Stream& stream, String & s)
{
  const uint16_t BUF_SIZE = 255;
  char buffer[BUF_SIZE];
  size_t pos = 0;

  memset(buffer,0,BUF_SIZE);

  while (stream.available() > 0 )   //Empty the input buffer
  {
    stream.read();
  }

  Serial.print( s );
  stream.print( s );

  //delay(100);
  int wait = 0;
  unsigned long start = millis();
  while(millis() < start+1000 ) ///wait for answer or timeout
  {
    while (stream.available() > 0 )   ///wait for answer or timeout
    {
      char c = stream.read();
      buffer[pos++] = c;
      if( pos == BUF_SIZE )
      {
        Serial.println(F("overflow"));
        return false;  //overflow
      }
      if( c == 0x0d )
      {
        pos--;
        break;  //end of line
      }
    }    
  }

  if( pos == 0 )
  {
    Serial.println("timeout");
    return false; //timeout
  }
  else
  {
    Serial.print(buffer);
  }
  
  uint16_t crc = cal_crc_half(buffer, pos-2);
  uint16_t check = (((uint16_t)buffer[pos-2]&0xFF)<<8) + (uint16_t)(buffer[pos-1]&0xFF); 
  if(crc != check)
  {
    Serial.print("CRC error: crc=");
    Serial.print(crc,HEX); 
    Serial.print(" check=");
    Serial.println(check,HEX);
    return false; //CRC error
  }
  char delimiter = ',';
  char first ='6';
  char* pch = strtok(buffer, &first);
  if(pch == NULL) return 0;
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // AAAA      Grid voltage              A: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // BBB       Grid frequency            B: 0~9, unit: 0.1Hz
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // CCCC      AC output voltage         C: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // DDD       AC output frequency       D: 0~9, unit: 0.1Hz
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;  // EEEE      AC output apparent power  E: 0~9, unit: VA
  payloadInverter.apparentPower = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;      // FFFF      AC output active power    F: 0~9, unit: W
  payloadInverter.activePower = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // GGG       Output load percent       G: 0~9, unit: %
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // HHH       Battery voltage           H: 0~9, unit: 0.1V
  payloadInverter.batteryVoltage = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // III       Battery voltage from SCC  I: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // JJJ       Battery voltage from SCC2 J: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // KKK       Battery discharge current K: 0~9, unit: A
  payloadInverter.batteryDischarge = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // LLL       Battery charging current  L: 0~9, unit: A
  payloadInverter.batteryCharging = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // MMM       Battery capacity          M: 0~9, unit: %
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // NNN       Inverter heat sink temperature  N: 0~9, unit: oC
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // OOO       MPPT1 charger temperature O: 0~9, unit: oC
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // PPP       MPPT2 charger temperature P: 0~9, unit: oC
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // QQQQ      PV1 Input power           Q: 0~9, unit: W
  payloadInverter.pvInputPower = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // RRRR      PV2 Input power           R: 0~9, unit: W
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // SSSS      PV1 Input voltage         S: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // TTTT      PV2 Input voltage         S: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // U         Setting value configuration state 0: Nothing changed
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // V         MPPT1 charger status      0: abnormal, 1: normal but
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // W         MPPT2 charger status      0: abnormal, 1: normal but
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // X         Load connection           0: disconnect, 1: connect
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // Y         Battery power direction   0: donothing, 1: charge, 2
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // Z         DC/AC power direction     0: donothing, 1: AC-DC, 2:
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // a         Line power direction      0: donothing, 1: input, 2:
 // if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // b         Local parallel ID         a: 0~(parallel number - 1)

  return true;
}

void setup()
{  
  Serial.begin(9600);
	Serial1.begin(2400);
  g_serialInverter2.begin(2400);

  pinMode(LED_PIN, OUTPUT);
  
	Serial.println(F("MPP inverter sensor node start"));

  //check to make sure the correct SPI pins are assigned for use witht he Moteino Mega 1284P
  if( SPI_SS !=  4 || SPI_MOSI != 5 || SPI_MISO != 6 || SPI_SCK != 7 )
    Serial.println("Warning. The JLib code will not work with the Moteino Mega.");

	// Serial.print("SPI_SS   ");   Serial.println(SPI_SS   );
	// Serial.print("SPI_MOSI ");   Serial.println(SPI_MOSI );
	// Serial.print("SPI_MISO ");   Serial.println(SPI_MISO );
	// Serial.print("SPI_SCK  ");   Serial.println(SPI_SCK  );

	Serial.println("rf12_initialize");

	rf12_initialize(g_rf12Init.node, g_rf12Init.freq, g_rf12Init.group);
	EmonSerial::PrintRF12Init(g_rf12Init);

  EmonSerial::PrintInverterPayload(NULL);

  delay(1000);
//  char qmod[] = {"QMOD"};
//  CreateCmdString(qmod); 
//  char cmd[] = {"^P004T"};
//  CreateCmdString(cmd); 
}

void SendPacket()
{
  rf12_sleep(RF12_WAKEUP);
  int wait = 1000;
  while (!rf12_canSend() && wait--)
  {
    rf12_recvDone();
  }
  if (wait)
  {
    rf12_sendStart(0, &payloadInverter, sizeof(payloadInverter));
    rf12_sendWait(0);
  }
  else
  {
    Serial.println(F("RF12 waiting. No packet sent"));
  }
  rf12_sleep(RF12_SLEEP);
  EmonSerial::PrintInverterPayload(&payloadInverter);
}

void loop()
{
  digitalWrite(LED_PIN, HIGH);

  if( ReadFromInverter( Serial1, P005GS ) )
  {
    payloadInverter.subnode = 0;
    SendPacket();
  }

  if( ReadFromInverter( g_serialInverter2, P005GS ) )
  {
    payloadInverter.subnode = 1;
    SendPacket();
  }
  digitalWrite(LED_PIN, LOW);
  
  delay(13000);
}
