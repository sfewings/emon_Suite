#define HARVEY_FARM

#define LORA_RF95

#ifdef LORA_RF95
	//Note: Use board config Moteino 8MHz for the Lora 8MHz boards
	#include <RH_RF95.h>
	RH_RF95 g_rfRadio(4,2);
	#define RADIO_BUF_LEN   RH_RF95_MAX_PAYLOAD_LEN
	#define NODE_INITIALISED_STRING F("RF95 initialise node: ")
#else
	#include <RH_RF69.h>
	RH_RF69 g_rfRadio;
	#define RADIO_BUF_LEN   RH_RF69_MAX_MESSAGE_LEN
	#define GREEN_LED 		9
	#define RFM69_RST     	4
	#define NODE_INITIALISED_STRING F("RF69 initialise node: ")
#endif

//#include <SoftwareSerial.h>
#include <EmonShared.h>

String QPI = "\x51\x50\x49\xBE\xAC\x0D";                    //Query Device Protocol ID Inquiry
String QPIRI = "\x51\x50\x49\x52\x49\xF8\x54\x0D";          //Query Device Rating Information inquiry
String QPIGS = "\x51\x50\x49\x47\x53\xB7\xA9\x0D";          //Query Device general status parameters inquiry
String QPIGS2 = "\x51\x50\x49\x47\x53\x32\x68\x2D\x0D";     //Query Device general status parameters for MPPT PV 2 and 3

PayloadInverter g_payloadInverter;

//SoftwareSerial g_serialInverter2(14, 13);	//18,17); //A1=rx, A0=tx

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


int ReadFromInverter(Stream& stream, String & cmdString)
{
  const uint16_t BUF_SIZE = 255;
  char buffer[BUF_SIZE];
  size_t pos = 0;

  memset(buffer,0,BUF_SIZE);

  while (stream.available() > 0 )   //Empty the input buffer
  {
    stream.read();
  }

  Serial.print( cmdString );
  stream.print( cmdString );

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
    Serial.println(buffer);
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
  char delimiter = ' ';
  char first ='(';
  char* pch = strtok(buffer-1, &first);
  if(pch == NULL) return 0;
  if( 0 == strcmp(cmdString.c_str(), "QPISG"))
  {
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // BBB.B      Grid voltage              B: 0~9, unit: 0.1V
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // CC.C       Grid frequency            C: 0~9, unit: 0.1Hz
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // DDD.D      AC output voltage         D: 0~9, unit: 0.1V
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // EE.E       AC output frequency       E: 0~9, unit: 0.1Hz
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // FFFF       AC output apparent power  F: 0~9, unit: VA
    g_payloadInverter.apparentPower = atoi(pch);
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // GGGG      AC output active power     G: 0~9, unit: W
    g_payloadInverter.activePower = atoi(pch);
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // HHH       Output load percent       H: 0~9, unit: %
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // III       Bus voltage               I: 0~9, unit: 0.1V
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // JJJ       Battery voltage from SCC  J: 0~9, unit: V
    g_payloadInverter.batteryVoltage = (unsigned short) (atof(pch)*10.0);   //convert V to 0.1V
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // KKK       Battery charging current  K: 0~9, unit: A
    g_payloadInverter.batteryCharging = atoi(pch);
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // OOO       Battery capacity          O: 0~9, unit: %
    g_payloadInverter.batteryCapacity = atoi(pch);
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // TTTT      Inverter heat sink temperature  T: 0~9, unit: oC
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // EEEE      PV Input current for battery    E: 0~9, unit: A
    int inputCurrent = atoi(pch);
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // UUU.U     PV1 Input voltage         U: 0~9, unit: 0.1V
    int inputVoltage = atoi(pch);
    g_payloadInverter.pvInputPower = inputCurrent * inputVoltage;  
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // WW.WW     Battery voltage from SCC W: 0~9, unit: 0.1V
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // PPPPP     Battery discharge current K: 0~9, unit: A
    g_payloadInverter.batteryDischarge = atoi(pch);
    Serial.println(pch);

                                                              /*  b7b6b5b4b3b2b1b0  Device status
                                                                            
                                                                            b7: add SBU priority version, 1:yes,0:no
                                                                            b6: configuration status: 1: Change 0:
                                                                            unchanged
                                                                            b5: SCC firmware version 1: Updated 0:
                                                                            unchanged
                                                                            b4: Load status: 0: Load off 1:Load on
                                                                            b3: battery voltage to steady while charging
                                                                            b2: Charging status( Charging on/off)
                                                                            b1: Charging status( SCC charging on/off)
                                                                            b0: Charging status(AC charging on/off)
                                                                            b2b1b0:
                                                                            000: Do nothing
                                                                            110: Charging on with SCC charge on
                                                                            101: Charging on with AC charge on
                                                                            111: Charging on with SCC and AC charge on*/
  }
  else if( 0 == strcmp(cmdString.c_str(), "QPISG2"))
  {
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N1N2N3N4        PV Input current 2              unit: A
    int inputCurrent = atoi(pch);
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N6N7N8.N10      PV Input voltage 2              unit: V
    double inputVoltage = atof(pch);
    g_payloadInverter.pvInputPower = (unsigned short) (inputCurrent * inputVoltage);  
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N12N13.N15N16   Battery voltage from SCC 2      unit: V
    g_payloadInverter.batteryVoltage = (unsigned short) (atof(pch)*10.0);   //convert V to 0.1V
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N18N19N20N21N22 PV Charging power 2             unit: Watt
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // b24b25b26b27b28b29b30b31  Device status         b24: Charging status( SCC2 charging on/off)
                                                               //                                                 b25: Charging status( SCC3 charging on/off)
                                                               //                                                 b26~ b31: Reserved
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N33N34N35N36    AC charging current             unit A
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N38N39N40N41    AC charging power               unit: W
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N42N43N44N45    PV Input current 3              unit: A
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N47N48N49.N51   PV Input voltage 3              unit: V
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N53N54.N56N57   Battery voltage from SCC 3      unit: V
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N58N59N60N61    PV Charging power 3             unit: Watt
    if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // N63N64N65N66N67 PV total charging power         unit: Watt
    Serial.println(pch);
  }
  else
  {
    return false;
  }
  return true;
}

void setup()
{  
  Serial.begin(9600);
	
  // delay(1000);
  // char cmd[] = {"QPIGS2"};
  // CreateCmdString(cmd); 

  return;

  Serial1.begin(2400);

  pinMode(LED_PIN, OUTPUT);
  
	Serial.println(F("PIP-5048MS (Giant) inverter sensor node start"));


	if (!g_rfRadio.init())
		Serial.println(F("rfRadio init failed"));
	if (!g_rfRadio.setFrequency(915.0))
		Serial.println(F("rfRadio setFrequency failed"));
	g_rfRadio.setHeaderId(INVERTER_NODE);

#ifndef LORA_RF95
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rfRadio.setEncryptionKey(key);
#endif

	Serial.print(NODE_INITIALISED_STRING);
	Serial.print(INVERTER_NODE);
	Serial.println(" Freq: 915MHz");

  EmonSerial::PrintInverterPayload(NULL);
}

void SendPacket()
{
  g_rfRadio.send((const uint8_t*) &g_payloadInverter, sizeof(g_payloadInverter));
  g_rfRadio.waitPacketSent();

  EmonSerial::PrintInverterPayload(&g_payloadInverter);
}

void loop()
{
  digitalWrite(LED_PIN, HIGH);

  if( ReadFromInverter( Serial1, QPIGS ) )
  {
    g_payloadInverter.subnode = 0;
    SendPacket();
  }
  if( ReadFromInverter( Serial1, QPIGS2 ) )
  {
    g_payloadInverter.subnode = 1;
    SendPacket();
  }

  digitalWrite(LED_PIN, LOW);
  
  delay(10000);
}
