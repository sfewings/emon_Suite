#include <AltSoftSerial.h>
#include <EmonShared.h>


//SoftwareSerial Serial1(A1, A0);  //A1=rx, A0=tx
//AltSoftSerial Serial1; //UNO pin 9 = Tx, Pin 8 = Rx Mega 1284 pin 14=Rx, pin 13 = Tx
String P005GS = "\x5E\x50\x30\x30\x35\x47\x53\x58\x14\x0D"; //Query General status
String P005PI = "\x5E\x50\x30\x30\x35\x50\x49\x71\x8B\x0D"; //Query Protocol version
String P004T = "\x5E\x50\x30\x30\x34\x54\xDF\x69\x0D";      //Query Current time

PayloadInverter payloadInverter;
/*
^P005GS<CRC><cr>: Query general status
Response: ^D106AAAA,BBB,CCCC,DDD,EEEE,FFFF,GGG,HHH,III,JJJ,KKK,LLL,MMM,NNN,OOO,PPP,QQQQ,RRRR,SSSS,TTTT,U,V,W,X,Y,Z,a,b<CRC><cr>
Data      Description               Remark
    // AAAA      Grid voltage              A: 0~9, unit: 0.1V
    // BBB       Grid frequency            B: 0~9, unit: 0.1Hz
    // CCCC      AC output voltage         C: 0~9, unit: 0.1V
    // DDD       AC output frequency       D: 0~9, unit: 0.1Hz
    // EEEE      AC output apparent power  E: 0~9, unit: VA
    // FFFF      AC output active power    F: 0~9, unit: W
    // GGG       Output load percent       G: 0~9, unit: %
    // HHH       Battery voltage           H: 0~9, unit: 0.1V
    // III       Battery voltage from SCC  I: 0~9, unit: 0.1V
    // JJJ       Battery voltage from SCC2 J: 0~9, unit: 0.1V
    // KKK       Battery discharge current K: 0~9, unit: A
    // LLL       Battery charging current  L: 0~9, unit: A
    // MMM       Battery capacity          M: 0~9, unit: %
    // NNN       Inverter heat sink temperature  N: 0~9, unit: oC
    // OOO       MPPT1 charger temperature O: 0~9, unit: oC
    // PPP       MPPT2 charger temperature P: 0~9, unit: oC
    // QQQQ      PV1 Input power           Q: 0~9, unit: W
    // RRRR      PV2 Input power           R: 0~9, unit: W
    // SSSS      PV1 Input voltage         S: 0~9, unit: 0.1V
    // TTTT      PV2 Input voltage         S: 0~9, unit: 0.1V
    // U         Setting value configuration state 0: Nothing changed, 1: Something changed
    // V         MPPT1 charger status      0: abnormal, 1: normal but not charged, 2: charging
    // W         MPPT2 charger status      0: abnormal, 1: normal but not charged, 2: charging
    // X         Load connection           0: disconnect, 1: connect
    // Y         Battery power direction   0: donothing, 1: charge, 2: discharge
    // Z         DC/AC power direction     0: donothing, 1: AC-DC, 2: DC-AC
    // a         Line power direction      0: donothing, 1: input, 2: output
    // b         Local parallel ID         a: 0~(parallel number - 1)
*/



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


int ReadFromInverter(String & s)
{
  const uint16_t BUF_SIZE = 255;
  char buffer[BUF_SIZE];
  size_t pos = 0;

  memset(buffer,0,BUF_SIZE);

  while (Serial1.available() > 0 )   //Empty the input buffer
  {
    Serial1.read();
  }

  Serial.println( s );
  Serial1.print( s );

  //delay(100);
  int wait = 0;
  unsigned long start = millis();
  while(millis() < start+1000 ) ///wait for answer or timeout
  {
    while (Serial1.available() > 0 )   ///wait for answer or timeout
    {
      char c = Serial1.read();
      buffer[pos++] = c;
      if( pos == BUF_SIZE )
      {
        Serial.println(F("overflow"));
        return false;  //overflow
      }
      if( c == 0x0d )
      {
        pos--;
        Serial.println("EOL");
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
  
  uint16_t crc = cal_crc_half(buffer, pos-3);
  if( (char)(crc << 8) != buffer[pos-1] && (char)(crc) != buffer[pos-2] )
  {
    Serial.print((char)(crc<<8),HEX);Serial.print(",");
    Serial.print((char)crc,HEX);Serial.println();
    Serial.print(buffer[pos-1],HEX);Serial.print(",");
    Serial.print(buffer[pos-2],HEX);Serial.println();
    Serial.print("Len=");Serial.println(pos);
    Serial.println("CRC error");
//    return false; //CRC error
  }
  char delimiter = ',';
  char first ='6';
  char* pch = strtok(buffer, &first);
  if( pch == NULL )
    Serial.println("buffer == NULL");

  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // AAAA      Grid voltage              A: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // BBB       Grid frequency            B: 0~9, unit: 0.1Hz
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // CCCC      AC output voltage         C: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // DDD       AC output frequency       D: 0~9, unit: 0.1Hz
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;  // EEEE      AC output apparent power  E: 0~9, unit: VA
  payloadInverter.apparentPower = atoi(pch);
  //Serial.print("  payloadInverter.apparentPower =");Serial.println(  payloadInverter.apparentPower );
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;      // FFFF      AC output active power    F: 0~9, unit: W
  payloadInverter.activePower = atoi(pch);
  //Serial.print("  payloadInverter.activePower =");Serial.println(  payloadInverter.activePower );
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

  EmonSerial::PrintInverterPayload(&payloadInverter);
  
  return true;
}

void setup()
{  
  Serial.begin(9600);
	Serial1.begin(2400);
  Serial.println("Reset");
  delay(2000);
//  char qmod[] = {"QMOD"};
//  CreateCmdString(qmod); 
//  char cmd[] = {"^P004T"};
//  CreateCmdString(cmd); 
}

void loop()
{
  int retVal = ReadFromInverter( P005GS );

  Serial.println( retVal );
  //if( ReadFromInverter( P005GS ) )
  {
    EmonSerial::PrintInverterPayload(&payloadInverter);
  }

  delay(2000);
}
