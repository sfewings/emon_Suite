// Example: simulate 100-tooth flywheel at variable RPM
const int tachPin = 8;  // output pin
int teeth = 120;
int rpm = 500;
int highPeriod = 500; //microseconds signal high time

void setup() 
{
  pinMode(tachPin, OUTPUT);

  Serial.begin(9600);
  Serial.println("Tachometer Signal Generator");
  Serial.print("Teeth: "); Serial.println(teeth);
  Serial.print("RPM: "); Serial.println(rpm);

}

long deltaTime(long rpm)
{
  double dTime = 42000.0*pow(rpm,-0.7); //-0.668);
  return dTime;
}

void loop() 
{
  // for(int i =100; i <2500; i+=100)
  // {
  //   long dt = deltaTime(i);
  //   Serial.print("RPM: "); Serial.print(i);
  //   Serial.print(" Delay: "); Serial.println(dt);
  //   unsigned long start = millis();
  //   while(millis() < 300 + start)
  //   {
  //     digitalWrite(tachPin, HIGH);
  //     delayMicroseconds(dt);
  //     digitalWrite(tachPin, LOW);
  //   }
  //   delay(5);
  // }
  // for(int i =2500; i >=100; i-=100)
  // {
  //   long dt = deltaTime(i);
  //   Serial.print("RPM: "); Serial.print(i);
  //   Serial.print(" Delay: "); Serial.println(dt);
  //   unsigned long start = millis();
  //   while(millis() < 300 + start)
  //   {
  //     digitalWrite(tachPin, HIGH);
  //     delayMicroseconds(dt);
  //     digitalWrite(tachPin, LOW);
  //   }
  // }
  // calculate frequency in Hz
  //float freq = (rpm * teeth) / 60.0;
  // calculate delay for 50% duty
  //float period = (1.0 / freq) * 1e6; // microseconds
  //for(int i = 3000; i > 160; i--)
const int VALS_COUNT = 8;
  int rpm_vals[VALS_COUNT] = {100, 500,1000,1100,1200,1500,2000,2500};
//  int vals[6] = {430,393,360,285,221,180}; 
//  int vals[6] = {428,391,358,283,220,179}; 
//  int vals[6] = {435,397,365,287,222,181}; 
//  int vals[6] = {440,400,367,289,224,182}; 
///  int vals[6] = {444,402,368,291,225,182}; 
//  int vals[VALS_COUNT] = {2000, 860,447,404,370,295,226,184}; 
//  int vals[VALS_COUNT] = {2000, 880,447,405,370,297,225,183}; 
//  int vals[VALS_COUNT] = {2100, 900,448,406,370,298,225,183};
  int vals[VALS_COUNT] = {2130, 940,447,406,370,298,225,183}; 

//  for(int i = 430; i > 160; i--)
  for(int j=0; j<VALS_COUNT; j++)
  {
    int i = vals[j];
    double frequency = 1.0 / (i/1000000.0); // microseconds
    Serial.print(rpm_vals[j]);Serial.print(", "); Serial.print(i); Serial.print(", ");Serial.println(frequency,2);
    unsigned long start = millis();
    while(millis() < 5000 + start)
    {
      digitalWrite(tachPin, HIGH);
      delayMicroseconds(i);
      digitalWrite(tachPin, LOW);
//      delayMicroseconds(1);
    }
  }
//  delayMicroseconds(period-highPeriod);
}