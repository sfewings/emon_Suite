#include <SPI.h>
#include <utility/w5100.h>
#include <Ethernet.h>


//  The address of the server you want to connect to (pachube.com):

// IP address of the www.pachube.com server to contact (IP of the first portion of the URL):
static byte pachubeip[4] = {173,203,98,29 };   //209,40,205,190};

// The name of the virtual host which you want to contact at pachubeip (hostname of the first portion of the URL):
#define PACHUBE_VHOST "api.pachube.com"
#define PACHUBEAPIURL "/v2/feeds/13743.csv"
#define PACHUBEAPIKEY "X-PachubeApiKey: f04d8709cfe8d8b88d5c843492a738f634f0fab11402e6c2abc2b4c7f6dfff31"


uint8_t PachubeSendData(String dataString)
{
  // initialize the library instance:
  EthernetClient tcpClient;
  
  long lastConnectionTime = 0;        // last time you connected to the server, in milliseconds

  // if you're not connected, and ten seconds have passed since
  // your last connection, then connect again and send data:
  Serial.print("Client status start = ");
  Serial.println(tcpClient.status(), HEX);
  
  if(!tcpClient.connected() )
  {
    // if there's a successful connection:
    if (tcpClient.connect(pachubeip,80)) 
    {
      Serial.println("Pachube connecting...");
      // send the HTTP PUT request. 
      // fill in your feed address here:
      tcpClient.print("PUT /v2/feeds/13743.csv HTTP/1.0\n");
      tcpClient.print("Host: api.pachube.com\n");
      tcpClient.print("X-PachubeApiKey: f04d8709cfe8d8b88d5c843492a738f634f0fab11402e6c2abc2b4c7f6dfff31\n");
      tcpClient.print("Content-Length: ");
      tcpClient.println(dataString.length(), DEC);
      tcpClient.print("Content-Type: text/csv\n");
      tcpClient.println("Connection: close\n");
  
      // here's the actual content of the PUT request:
      tcpClient.println(dataString);
  
      Serial.print("PUT /v2/feeds/13743.csv HTTP/1.0\n");
      Serial.print("Host: api.pachube.com\n");
      Serial.print("X-PachubeApiKey: f04d8709cfe8d8b88d5c843492a738f634f0fab11402e6c2abc2b4c7f6dfff31\n");
      Serial.print("Content-Length: ");
      Serial.println(dataString.length(), DEC);
      Serial.print("Content-Type: text/csv\n");
      Serial.println("Connection: close\n");
      Serial.println(dataString);
  
  
      // note the time that the connection was made:
      lastConnectionTime = millis();
    } 
    else
    {
      // if you couldn't make a connection:
      Serial.print("Pachube connection failed. Client status = ");
      Serial.println(tcpClient.status(), HEX);

      //Serial.println(tcpClient.status(3), HEX);
    }
  }
  else
  {
      Serial.print("Pachube already connected. Client status = ");
      Serial.println(tcpClient.status(), HEX);
  }
  
  while( tcpClient.status() != SnSR::CLOSED )
  { 
    //Serial.print("Client status 1 = ");
    //Serial.println(tcpClient.status(), HEX);
  
    while(tcpClient.available()) 
    {
      char c = tcpClient.read();
      Serial.print(c);
    }
    
    if (!tcpClient.available() && tcpClient.status() == SnSR::CLOSE_WAIT ) 
    {
      Serial.println();
      Serial.println("Pachube disconnecting.");
      tcpClient.stop();
    }
    else if( millis() - lastConnectionTime >40000 && tcpClient.status() != SnSR::CLOSED )
    {
      Serial.println();
      Serial.println("Pachube forcefully disconnecting!");
      tcpClient.stop();
    }
  }
  
  Serial.print("Client status end = ");
  Serial.println(tcpClient.status(), HEX);

  return tcpClient.status();
}


