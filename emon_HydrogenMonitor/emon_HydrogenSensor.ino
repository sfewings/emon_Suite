#define     LED                     13               // Built-in LED pin

/*--------------------------- Global Variables ---------------------------*/


void Blink(byte PIN, byte DELAY_MS, byte loops) 
{
  for (byte i=0; i<loops; i++)  
  {
    digitalWrite(PIN,HIGH);
    delay(DELAY_MS);
    digitalWrite(PIN,LOW);
    delay(DELAY_MS);
  }
}


/**
  Setup
*/
void setup()
{
  Serial.begin(9600);
  pinMode(LED, OUTPUT);    

  Blink(LED, 50, 3);
  
  pinMode(2, INPUT);
  
}

/**
  Main loop
*/
void loop()
{

  uint32_t time_now = millis();

  int val = analogRead(A0);
  int dec = digitalRead(2);
  Serial.print("Analog in=");
  Serial.print(val);
  Serial.print(", Digital in=");
  Serial.println(dec);

  delay(1000);
}