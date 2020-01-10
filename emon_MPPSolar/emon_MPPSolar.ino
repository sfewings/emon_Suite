//#include <SoftwareSerial.h>
#include <AltSoftSerial.h>

unsigned long lastMillis=0;
unsigned long lastMillis1=0;
long previousMillis = 0;


//SoftwareSerial serialMPP(A1, A0);  //A1=rx, A0=tx
AltSoftSerial serialMPP; //pin 9 = Tx, Pin 8 = Rx

String QPIGS = "\x51\x50\x49\x47\x53\xB7\xA9\x0D";
String QPIWS = "\x51\x50\x49\x57\x53\xB4\xDA\x0D";  
String QDI = "\x51\x44\x49\x71\x1B\x0D";
String QMOD = "\x51\x4D\x4F\x44\x49\xC1\x0D"; 
String BAD_CRC = "\x51\x4D\x4F\x44\x49\xba\x0D"; 
String QVFW =  "\x51\x56\x46\x57\x62\x99\x0D"; 
String QVFW2 = "\x51\x56\x46\x57\x32\xC3\xF5\x0D"; 
String POP02 = "\x50\x4F\x50\x30\x32\xE2\x0B\x0D";  //SBU priority
String POP01 = "\x50\x4F\x50\x30\x32\xE2\xD2\x69";  //solar first
String POP00 = "\x50\x4F\x50\x30\x30\xC2\x48\x0D";  //utility first
String QID = "\x51\x49\x44\xD6\xEA\x0D";
String QPI = "\x51\x50\x49\xBE\xAC\x0D";
String QPI_NOCRC = "\x51\x50\x49\x0D";
String P005GS = "\x5E\x50\x30\x30\x35\x47\x53\x58\x14\x0D"; //Query General status
String P005PI = "\x5E\x50\x30\x30\x35\x50\x49\x71\x8B\x0D"; //Query Protocol version
String P004T = "\x5E\x50\x30\x30\x34\x54\xDF\x69\x0D";     //Query Current time



float imp_volt;
float imp_freq;
float out_volt;
float out_freq;
int out_load_va;
int out_load_w;
int out_load_perc;
float bat_volt;
int chg_amp;
int  batt_level_perc;
float  pv_amp;
float pv_volt;
int disc_amp;
int inv_temp;
float  W_ftv;
String stato;

int readvalue;


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



void read_QPIGS()
{
  serialMPP.print(QPIGS);
  
  lastMillis = millis();
  while(serialMPP.available() == 0 &&  millis()< lastMillis+1000) ///wait for answer or timeout
  {
  }
  while (serialMPP.available())
  {
    char c = serialMPP.read();
   // if( ( (byte) c ) < 32 )
    {
      Serial.print((byte)c);
      Serial.print(",");
    }
//    else
//    {
//      Serial.print(c);
//    }
    
  }
 // if (serialMPP.find("(")) 
  //{
 //   Serial.println("provo a stampa dalla seriale 1");
 //   imp_volt = serialMPP.parseFloat();        //QPIGS.1 Grid voltage      
 //   imp_freq = serialMPP.parseFloat();        //QPIGS.2 Grid frequency

  //  float out_volt;
  //  float out_freq;
  //  int out_load_va;
  //  int out_load_w;
  //  int out_load_perc;
  //  float bat_volt;
  //  int chg_amp;
  //  int  batt_level_perc;
  //  float  pv_amp;
  //  float pv_volt;
  //  int disc_amp;
  //  int inv_temp;

  //  int dummy;

  //  out_volt = serialMPP.parseFloat();       //QPIGS.3 Out voltage  
 //   out_freq = serialMPP.parseFloat();       //QPIGS.4 Out frequency
 //   out_load_va = serialMPP.parseInt();     //QPIGS.5 AC output apparent power
 //   out_load_w = serialMPP.parseInt();      //QPIGS.6 AC output active power
 //   out_load_perc = serialMPP.parseInt();   //QPIGS.7 Output load percent 
  //  dummy =serialMPP.parseInt();                             //  INP_nonso  skip
 //   bat_volt = serialMPP.parseFloat();    //QPIGS.9 Battery voltage 
 //   chg_amp = serialMPP.parseInt();     //QPIGS.10 Battery charging current
 //   batt_level_perc = serialMPP.parseInt(); //QPIGS.11 Battery capacity 
 //   inv_temp =serialMPP.parseInt();                             //skip
 //   root["INP_PV_amp"] =serialMPP.parseFloat();                             //skip
 //   root["INP_PV_amp2"] =serialMPP.parseFloat();     //QPIGS.14 PV Input voltage 
 //   root["INP_PV_VOLT121"] = serialMPP.parseFloat();                             //skip
 //   root["OUT_DISC_AMP"] = serialMPP.parseInt();    //QPIGS.16 Battery discharge current
  //}
};

/*
void read_QPIWS()
{
  String inData;
  lastMillis = millis();
  
  //ledblink(MKR_LED, 500, 3);
  serialMPP.print(QPIWS);
//  while (serialMPP.available() == 0&&  millis()< lastMillis+1000)   ///wait for answer or timeout
//  {
//  }

  inData= serialMPP.readStringUntil('\r');
  Serial.println(inData);
  
  //while (serialMPP.available() > 0)
  // {   
  //    char recieved = serialMPP.read();
  //
  //      inData += recieved; 
  //
  //  }
//  root["I_SETTING"] = inData.substring(1,30);
};
*/
void read_QMOD()
{
 // while (serialMPP.available() > 0)
 // {
 //   serialMPP.flush();
 //   byte a=serialMPP.read();
 //   Serial.print(".");
 //   Serial.print(a);
 // }
 
  serialMPP.print(QMOD);
  
  //Serial.print(QMOD);
  
  lastMillis = millis();
  while(serialMPP.available() == 0 &&  millis()< lastMillis+1000) ///wait for answer or timeout
  {
    //Serial.print(serialMPP.available());  
  }
  
  while (serialMPP.available() )   ///wait for answer or timeout
  {
    char c = serialMPP.read();
    if( ( (byte) c ) < 32 )
    {
      Serial.print((byte)c);
      Serial.print(",");
    }
    else
      Serial.print(c);
  }
  
//  String inData;
//  inData= serialMPP.readStringUntil('\r');
//  Serial.println(inData);
  
  //while (serialMPP.available() > 0)
  // {   
  //    char recieved = serialMPP.read();
  //
  //      inData += recieved; 
  //
  //  }
  //root["MODE_MAINS"] = inData.substring(1,2);
  //stato= inData.substring(1,2);
}


void read_from_Inverter(String & s)
{
  Serial.println( s );
  serialMPP.print( s );

  delay(500);
  
  lastMillis = millis();
  while(serialMPP.available() == 0 &&  millis()< lastMillis+1000) ///wait for answer or timeout
  {
    //Serial.print(serialMPP.available());  
  }
  
  while (serialMPP.available() )   ///wait for answer or timeout
  {
    char c = serialMPP.read();
    if( ( (byte) c ) < 32 )
    {
      Serial.print("0x");
      Serial.print((byte)c, HEX);
      Serial.print(",");
    }
    else
    {
      Serial.print(c);
    }
    delay(1);
  }
  Serial.println();
}

void CalculateCmdString(char* c )
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


void setup()
{  
  Serial.begin(9600);
	serialMPP.begin(2400);

  char qmod[] = {"QMOD"};
  CalculateCmdString(qmod); 
  char cmd[] = {"^P004T"};
  CalculateCmdString(cmd); 
  
}

void loop()
{
	unsigned long currentMillis = millis();
	if(	currentMillis - previousMillis > 5000) 
	{

    //char qmod[] = {"QMOD"};
    //uint16_t crc = cal_crc_half( qmod, 4);
    //Serial.print(crc,HEX);
    
		previousMillis = currentMillis;  
 //   Serial.println("loop");
 
//    Serial.println("read_QMOD()");
//    read_QMOD();
//    Serial.println();
//    delay(300);

    read_from_Inverter( P004T );

    
//    Serial.println("read_QPIGS()");
//    read_QPIGS();
//    Serial.println();
	}
}
  /*  
    String x;
     
		root.printTo(x);
    
		Serial.println(x.c_str());  
     
    
		imp_volt=root["INP_VOLT"];
		imp_freq=root["INP_FREQ"] ;
		out_volt=root["OUT_VOLT"];
		out_freq=root["OUT_FREQ"];
		out_load_va=root["OUT_LOAD_VA"];
		out_load_w=root["OUT_LOAD_W"];
		out_load_perc= root["OUT_LOAD_PERC"];
		bat_volt=root["INP_BAT_VOLT"];
		chg_amp=root["INP_CHG_AMP"];
		batt_level_perc=root["BATT_LEVEL_PERC"];
		pv_amp=root["INP_PV_amp"];
		pv_volt=root["INP_PV_amp2"];
		disc_amp=root["OUT_DISC_AMP"];
		inv_temp=root["inv_temp"];
		W_ftv=( pv_volt*pv_amp);
		JsonObject& root = jsonBuffer.createObject();     
     //} 
}
Serial.print("stato=");

Serial.println(stato);
}
*/
