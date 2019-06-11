#include <EthernetUdp.h>        //for SNTP time

///////////// SNTP support /////////////////
// IP address of the NTP server to contact

#define MAX_SNTP_REQUESTS   10
#define NUM_NTPSERVERS      7
#define NTP_PACKET_SIZE     48     // NTP time stamp is in the first 48 bytes of the message

static byte NTP_server_IP[NUM_NTPSERVERS][4] ={
                                     { 150, 203, 1, 10 },   // ntp1.anu.edu.au
                                     { 64, 90, 182, 55},    // nist1-ny.ustiming.org
                                     { 130,149, 17, 21},    // ntps1-0.cs.tu-berlin.de
                                     { 192, 53,103,108},    // ptbtime1.ptb.de
                                     { 192, 43,244, 18},    // time.nist.gov
                                     { 130,149, 17, 21},    // ntps1-0.cs.tu-berlin.de
                                     { 192, 53,103,108}};   // ptbtime1.ptb.de

typedef enum 
{
  eReadyForUpdate, 
  eWaitingForServer, 
  eServerTimeReceived
}  NTPStatus;
  
int           ntpServer         = 0;                // the current NTP server we are trying to reach
int           requestTimeOuts   = 0;                // the number of times a request has timed out. 
NTPStatus     ntpStatus         = eReadyForUpdate;
time_t        receivedNTPTime;                      // time received from response packet
unsigned long timeNTPRequested;
char          packetBuffer[ NTP_PACKET_SIZE];       // buffer to hold incoming and outgoing packets 

EthernetUDP   udp;


// send an NTP request to the time server at the given address 
void SendNTPpacket(byte *address)
{
  // set all bytes in the buffer to 0
  memset(packetBuffer, 0, NTP_PACKET_SIZE); 
  // Initialize values needed to form NTP request
  // (see URL above for details on the packets)
  packetBuffer[0] = 0b11100011;   // LI, Version, Mode
  packetBuffer[1] = 0;     // Stratum, or type of clock
  packetBuffer[2] = 6;     // Polling Interval
  packetBuffer[3] = 0xEC;  // Peer Clock Precision
  // 8 bytes of zero for Root Delay & Root Dispersion
  packetBuffer[12]  = 49; 
  packetBuffer[13]  = 0x4E;
  packetBuffer[14]  = 49;
  packetBuffer[15]  = 52;

  // all NTP fields have been given values, now
  // you can send a packet requesting a timestamp: 	

  udp.beginPacket(IPAddress(address), 123);            //NTP requests are to port 123
  udp.write(packetBuffer,NTP_PACKET_SIZE);
	int value = udp.endPacket();
  Serial.print(F("NTP Packet sent. Return value = "));
  Serial.println(value);
}



//callback from Time.now() to get the latest time
unsigned long GetNtpTime()
{
  switch( ntpStatus )
  {
    case eReadyForUpdate:
      SendNTPpacket(NTP_server_IP[ntpServer]); // send an NTP packet to a time server
        
      ntpStatus = eWaitingForServer;
      receivedNTPTime = 0;
      Serial.println(F("SNTP request"));
      timeNTPRequested = millis();
     break;    //can't return a time as waiting back from server
    case eWaitingForServer:
      if( millis() - timeNTPRequested > 6000 )
      {
        Serial.println(F("SNTP request timed out"));
        if( ++requestTimeOuts >= MAX_SNTP_REQUESTS )
        {
          if( ntpServer == NUM_NTPSERVERS )
            ntpServer = 0;
          else
            ntpServer++;
          Serial.print(F("Trying NTP server "));
          for(int i=0; i<4;i++)
          {
            Serial.print(NTP_server_IP[ntpServer][i],DEC);
            Serial.print(".");
          }
          Serial.println();
          requestTimeOuts = 0;
        }
        ntpStatus = eReadyForUpdate;
      }
      break;    //still waiting back from server
    case eServerTimeReceived:
			setSyncInterval(86400 * 7);         // update the time every week  (24*60*60) *7
			ntpStatus = eReadyForUpdate;
      Serial.println(F("SNTP time updated"));
      return receivedNTPTime;
  }
  return 0;
}


void NTPClientSetup()
{
  //must have called Ethernet.begin() prior
  udp.begin(8888);                  // local port to listen for UDP packets  
	setSyncInterval(0);         // Need to set this to 0 to force every call to now() to callback GetNTPTime()
	setSyncProvider(GetNtpTime);      // initiate the callback to GetNtpTime   
}

bool  NTPClientLoop()
{
  if( ntpStatus == eWaitingForServer )
  {
    time_t time; 
    if( millis() %500 == 0 )
    {
       time = now();    //updates time and performs a NTP sync if required 
    }

    
    if ( udp.parsePacket() ) 
    {  
      udp.read(packetBuffer,NTP_PACKET_SIZE);  // read the packet into the buffer
  
      //the timestamp starts at byte 40 of the received packet and is four bytes,
      // or two words, long. First, esxtract the two words:
  
      unsigned long highWord = word(packetBuffer[40], packetBuffer[41]);
      unsigned long lowWord = word(packetBuffer[42], packetBuffer[43]);  
      // combine the four bytes (two words) into a long integer
      // this is NTP time (seconds since Jan 1 1900):
      receivedNTPTime = highWord << 16 | lowWord;  
      receivedNTPTime -= 2208988800;       //adjust the seconds difference between NTP time (1-Jan-1900) and unix time (1-Jan-1970)   
      receivedNTPTime += 8*60*60;          //adjust for GMT + 8. Perth time 

      //this will be picked up in the next call to GetNTPTime
      ntpStatus = eServerTimeReceived;
			time = now(); // forces a sync request that will callback GetNTPTime and update internal time
			return true;
    }
  }
  return false;
}

