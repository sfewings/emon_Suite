#include <SPI.h>
#include <utility/w5100.h>
#include <Ethernet.h>


//  The address of the server you want to connect to (pachube.com):

// IP address of the www.pachube.com server to contact (IP of the first portion of the URL):
static byte ourPowerIP[4] = {180,92,192,242 };   //209,40,205,190};

// The name of the virtual host which you want to contact at pachubeip (hostname of the first portion of the URL):
//#define VHOST "ourpower.fewings.org.au"
//#define APIURL "/upload/upload.php"
//#define APIKEY "?code=fjsdklajflsd&u=sfewings"


void OurPowerSendData(String dataString)
{
  EthernetClient tcpClient(2);
  long lastConnectionTime = 0;        // last time you connected to the server, in milliseconds
  
  // if you're not connected, and ten seconds have passed since
  // your last connection, then connect again and send data:
  if(!tcpClient.connected() )
  {
    // if there's a successful connection:
    if (tcpClient.connect(ourPowerIP,80)) 
    {
      Serial.println("Ourpower connecting...");

      String sendStr = "GET /upload/upload.php?code=fjsdklajflsd&u=sfewings";
      sendStr += dataString;
      sendStr += " HTTP/1.1\n";
      tcpClient.print(sendStr);
      Serial.print(sendStr);

      sendStr = "Host: ourpower.fewings.org.au\n";
      sendStr += "Accept: */";
      sendStr += "*\n";
      tcpClient.print( sendStr );
      Serial.print(sendStr);

      sendStr = "Connection: Close\n";
      sendStr += "User-Agent: Audurino (Steves)\n";
      tcpClient.println( sendStr );
      Serial.print(sendStr);

      // note the time that the connection was made:
      lastConnectionTime = millis();
    } 
    else
    {
      // if you couldn't make a connection:
      Serial.println("OurPower connection failed");
      Serial.println(tcpClient.status(), HEX);
      //Serial.println(tcpClient.status(), HEX);
    }
  }
  else
  {
      Serial.println("OurPower already connected");
      Serial.println(tcpClient.status(), HEX);
  }
  
  while( tcpClient.status() != SnSR::CLOSED )
  { 
    Serial.print("Client status 1 = ");
    Serial.println(tcpClient.status(), HEX);
  
    while(tcpClient.available()) 
    {
      char c = tcpClient.read();
      Serial.print(c);
    }
    
    if (!tcpClient.available() && tcpClient.status() == SnSR::CLOSE_WAIT ) 
    {
      Serial.println();
      Serial.println("Disconnecting.");
      tcpClient.stop();
    }
    else if( millis() - lastConnectionTime >40000 && tcpClient.status() != SnSR::CLOSED )
    {
      Serial.println();
      Serial.println("Forcefully disconnecting!");
      tcpClient.stop();
    }
  }
  
  Serial.print("Client status end = ");
  Serial.println(tcpClient.status(), HEX);
}
