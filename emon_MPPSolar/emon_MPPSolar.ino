#include <SoftwareSerial.h>


unsigned long lastMillis=0;
unsigned long lastMillis1=0;
long previousMillis = 0;
long interval = 1000;

SoftwareSerial serialMPP(A1, A0);	//A1=rx, A0=tx

String QPIGS = "\x51\x50\x49\x47\x53\xB7\xA9\x0D";
String QPIWS = "\x51\x50\x49\x57\x53\xB4\xDA\x0D";  
String QDI = "\x51\x44\x49\x71\x1B\x0D";
String QMOD = "\x51\x4D\x4F\x44\x49\xC1\x0D"; 
String QVFW =  "\x51\x56\x46\x57\x62\x99\x0D"; 
String QVFW2 = "\x51\x56\x46\x57\x32\xC3\xF5\x0D"; 
String POP02 = "\x50\x4F\x50\x30\x32\xE2\x0B\x0D";  //SBU priority
String POP01 = "\x50\x4F\x50\x30\x32\xE2\xD2\x69";  //solar first
String POP00 = "\x50\x4F\x50\x30\x30\xC2\x48\x0D";  //utility first


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

void setup()
{  
  Serial.begin(9600);
	serialMPP.begin(2400);
   
  Serial.println("finito setup2");
}

void loop()
{
	unsigned long currentMillis = millis();
	if(	currentMillis - previousMillis > interval) 
	{
		previousMillis = currentMillis;  
    Serial.println("loop");
     
    read_QMOD();
    read_QPIGS();
    
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



void read_QPIGS()
{
  serialMPP.print(QPIGS);
  
	while (serialMPP.available() == 0 )   ///wait for answer or timeout
  {
  }
	while (serialMPP.available())
	{
		String inData = serialMPP.read();
		char c = serialMPP.read();
		Serial.print(c);
 // if (serialMPP.find("(")) 
	//{
 //   Serial.println("provo a stampa dalla seriale 1");
 //   imp_volt = serialMPP.parseFloat();        //QPIGS.1 Grid voltage      
 //   imp_freq = serialMPP.parseFloat();        //QPIGS.2 Grid frequency

	//	float out_volt;
	//	float out_freq;
	//	int out_load_va;
	//	int out_load_w;
	//	int out_load_perc;
	//	float bat_volt;
	//	int chg_amp;
	//	int  batt_level_perc;
	//	float  pv_amp;
	//	float pv_volt;
	//	int disc_amp;
	//	int inv_temp;

	//	int dummy;

	//	out_volt = serialMPP.parseFloat();       //QPIGS.3 Out voltage  
 //   out_freq = serialMPP.parseFloat();       //QPIGS.4 Out frequency
 //   out_load_va = serialMPP.parseInt();     //QPIGS.5 AC output apparent power
 //   out_load_w = serialMPP.parseInt();      //QPIGS.6 AC output active power
 //   out_load_perc = serialMPP.parseInt();   //QPIGS.7 Output load percent 
	//	dummy =serialMPP.parseInt();                             //  INP_nonso  skip
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


void read_QPIWS()
{
	String inData;
  
	//ledblink(MKR_LED, 500, 3);
	serialMPP.print(QPIWS);
	while (serialMPP.available() == 0&&  millis()< lastMillis+1000)   ///wait for answer or timeout
	{
	}

	inData= serialMPP.readStringUntil('\r');
	//while (serialMPP.available() > 0)
	// {   
	//    char recieved = serialMPP.read();
	//
	//      inData += recieved; 
	//
	//  }
//	root["I_SETTING"] = inData.substring(1,30);
};

void read_QMOD()
{
  while (serialMPP.available() > 0)
  {
		serialMPP.flush();
		byte a=serialMPP.read();
	}

	String inData;
 
  
	//ledblink(MKR_LED, 500, 3);
	serialMPP.print(QMOD);
	while (serialMPP.available() == 0 )   ///wait for answer or timeout
	{
	}
	inData= serialMPP.readStringUntil('\r');
	//while (serialMPP.available() > 0)
	// {   
	//    char recieved = serialMPP.read();
	//
	//      inData += recieved; 
	//
	//  }
	root["MODE_MAINS"] = inData.substring(1,2);
	stato= inData.substring(1,2);
}
