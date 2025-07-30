//Emon_MPPSolar for MPP hybrid inverter

#include <SPI.h>
#include <RH_RF69.h>

#include <EEPROM.h>
#include <SoftwareSerial.h>
#include <EmonShared.h>

//#define MEGA_INSTALL  //install of MPP on Moteino mega for two inverters. Moetino is for a single inverter
#ifdef MEGA_INSTALL
//Note: Set board to Moteino-Mega to access Serial1
  #define NUM_INVERTERS 2
  #define INVERTER_SUBNODE_1 0
  #define INVERTER_SUBNODE_2 1

  #define SW_SERIAL_RX_PIN 14
  #define SW_SERIAL_TX_PIN 13
  #define LED_PIN 15
  
  RH_RF69 g_rf69(4,2);
#else
  #define NUM_INVERTERS 1
  #define INVERTER_SUBNODE_2 2

  #define SW_SERIAL_RX_PIN 3
  #define SW_SERIAL_TX_PIN 4
  #define LED_PIN 9
  
  RH_RF69 g_rf69;
#endif

#define EEPROM_BASE 0x10	//where the wH readings are stored in EEPROM

double g_mWH_produced[NUM_INVERTERS];
unsigned long g_lastMillis[NUM_INVERTERS];


String P005GS = "\x5E\x50\x30\x30\x35\x47\x53\x58\x14\x0D"; //Query General status
String P005PI = "\x5E\x50\x30\x30\x35\x50\x49\x71\x8B\x0D"; //Query Protocol version
String P004T = "\x5E\x50\x30\x30\x34\x54\xDF\x69\x0D";      //Query Current time


PayloadInverter g_payloadInverter;

SoftwareSerial g_serialInverter(SW_SERIAL_RX_PIN, SW_SERIAL_TX_PIN);

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

double readEEPROM(int offset)
{
	double value = 0;
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(double); l++)
	{
		*(pc + l) = EEPROM.read(EEPROM_BASE + offset * sizeof(double) + l);
	}

	return value;
}

void writeEEPROM(int offset, double value)
{
	char* pc = (char*)& value;

	for (long l = 0; l < sizeof(double); l++)
	{
		EEPROM.write(EEPROM_BASE + offset * sizeof(double) + l, *(pc + l));
	}
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
  g_payloadInverter.apparentPower = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;      // FFFF      AC output active power    F: 0~9, unit: W
  g_payloadInverter.activePower = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // GGG       Output load percent       G: 0~9, unit: %
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // HHH       Battery voltage           H: 0~9, unit: 0.1V
  g_payloadInverter.batteryVoltage = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // III       Battery voltage from SCC  I: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // JJJ       Battery voltage from SCC2 J: 0~9, unit: 0.1V
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // KKK       Battery discharge current K: 0~9, unit: A
  g_payloadInverter.batteryDischarge = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // LLL       Battery charging current  L: 0~9, unit: A
  g_payloadInverter.batteryCharging = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // MMM       Battery capacity          M: 0~9, unit: %
	g_payloadInverter.batteryCapacity = atoi(pch);
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // NNN       Inverter heat sink temperature  N: 0~9, unit: oC
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // OOO       MPPT1 charger temperature O: 0~9, unit: oC
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // PPP       MPPT2 charger temperature P: 0~9, unit: oC
  if (NULL == (pch = strtok(NULL, &delimiter))) return 0;    // QQQQ      PV1 Input power           Q: 0~9, unit: W
  g_payloadInverter.pvInputPower = atoi(pch);
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

//calculate the number of watt hours and then store to EEPROM, if changed!
void calculateWattHoursAndStore(int inverter)
{
  double mWH_produced = g_mWH_produced[inverter];
  unsigned long now = millis();
  unsigned long period = now - g_lastMillis[inverter];

  g_lastMillis[inverter] = now;
  g_mWH_produced[inverter] += g_payloadInverter.pvInputPower * period / (60 * 60 * 1000.0); //convert to wH

  //this will do the rounding to units of pulses
  g_payloadInverter.pulse = g_mWH_produced[inverter];

  //write g_mWH_produced to eeprom, if changed
  if( mWH_produced != g_mWH_produced[inverter])
  {
		writeEEPROM(inverter, g_mWH_produced[inverter]);
	}
}

void FlashLEDError()
{
		for(int i=0;i<3;i++)
		{
			digitalWrite(LED_PIN, HIGH);
			delay(100);
			digitalWrite(LED_PIN, LOW);
			delay(100);
		}
}

void setup()
{  
  Serial.begin(9600);
#ifdef MEGA_INSTALL
	Serial1.begin(2400);
#endif
  g_serialInverter.begin(2400);

  pinMode(LED_PIN, OUTPUT);
  
	Serial.println(F("MPP inverter sensor node start"));


	if (!g_rf69.init())
		Serial.println("rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("rf69 setFrequency failed");
	Serial.println("RF69 initialise node: 10 Freq: 915MHz");
	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
	g_rf69.setHeaderId(INVERTER_NODE);
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);


	//reset the counters
	// for (int i = 0; i < NUM_INVERTERS; i++)
	// {
	//   g_mWH_produced[i] = 0.0; 
	//  	writeEEPROM(i, 0.0);
	// }

	//Get double g_mWH_In and g_mWH_Out from eeprom
	for (int i = 0; i < NUM_INVERTERS; i++)
	{
		g_mWH_produced[i] = readEEPROM(i);
    g_lastMillis[i] = millis();
    Serial.print(F("Inverter ")); Serial.print(i);Serial.print(F(" total pulse (wh) " ));
    Serial.println(g_mWH_produced[i],1);
	}

  memset(&g_payloadInverter, 0, sizeof(g_payloadInverter));

  EmonSerial::PrintInverterPayload(NULL);

  delay(1000);
//  char qmod[] = {"QMOD"};
//  CreateCmdString(qmod); 
//  char cmd[] = {"^P004T"};
//  CreateCmdString(cmd); 
}

void SendPacket()
{
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
  g_rf69.send((const uint8_t*) &g_payloadInverter, sizeof(g_payloadInverter));
  g_rf69.waitPacketSent();
	g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);
  EmonSerial::PrintInverterPayload(&g_payloadInverter);
}

void loop()
{
  digitalWrite(LED_PIN, HIGH);

#ifdef MEGA_INSTALL
  if( ReadFromInverter( Serial1, P005GS ) )
  {
    calculateWattHoursAndStore(1);
    g_payloadInverter.subnode = INVERTER_SUBNODE_1;
    SendPacket();
  }
  else
  {
    FlashLEDError();
  }
#endif
  if( ReadFromInverter( g_serialInverter, P005GS ) )
  {
    calculateWattHoursAndStore(0);
    g_payloadInverter.subnode = INVERTER_SUBNODE_2;
    SendPacket();
  }
  else
  {
    FlashLEDError();
  }
  digitalWrite(LED_PIN, LOW);

  delay(13000);
}
