#include <avr/io.h>
#include <avr/interrupt.h>
//#include <wiring.h>



// interrupt driven pulse counts 
#define POWER_PULSE_PIN     3   
#define INTERRUPT_IR        1    // ATmega 168 and 328 - interrupt 0 = pin 2, 1 = pin 3

volatile unsigned short   g_wHrCount = 0;
volatile unsigned long    g_lastTick = 0;
volatile unsigned long    g_period   = 0;

unsigned short MeterPulseLog()
{
    unsigned short wattSensorCountIR; //number of watts during this logging interval 
    //uint8_t oldSREG = SREG;          // save interrupt register
    //cli();                           // prevent interrupts while accessing the count   
    wattSensorCountIR = g_wHrCount;  //get the count from the interrupt handler 
    g_wHrCount = 0;                    //reset the watts count
    //SREG = oldSREG;                  // restore interrupts

    return wattSensorCountIR;
}

unsigned short MeterCurrentWatts()
{  
  unsigned long lastPeriod; 
  unsigned long thisPeriod; 
  unsigned long lastTick;
  unsigned long tick = millis();
  double watts;
  
  uint8_t oldSREG = SREG;          // save interrupt register
  cli();                           // prevent interrupts while accessing the count   
  
  lastPeriod = g_period;
  lastTick = g_lastTick;
  
  SREG = oldSREG;                  // restore interrupts

  if( tick < lastTick )
    thisPeriod = tick + (lastTick-0xFFFFFFFF);  //rollover occured
  else
    thisPeriod = tick - lastTick;

  if( thisPeriod < lastPeriod )
    watts = ((double)1000)*3600/lastPeriod;       //report the watts for the last tick period
  else if( thisPeriod >120000 )                   
    watts = 0;                                    // 2 minutes. That is less than 30 watts/hour. report 0 instead of tappering off slowly towards 0 over time.
  else
    watts = ((double)1000)*3600/thisPeriod;       //report the wattage as if the tick occured now 
  
  return (unsigned short) watts;
}

void SetupPulseCount()
{
  g_lastTick = millis();

  //set up the interrupt handler that will count the IR LED watt pulse counts
  pinMode(POWER_PULSE_PIN, INPUT);     
  digitalWrite(POWER_PULSE_PIN, HIGH);   
  attachInterrupt(INTERRUPT_IR, interruptHandlerIR, FALLING);   
}


void interruptHandlerIR() // routine called when external interrupt is triggered
{
  //digitalWrite(LEDpin, HIGH);     //flash LED - very quickly each time a pluse occus  
  
  g_wHrCount = g_wHrCount + 1;  //Update number of pulses, 1 pulse = 1 watt
  unsigned long tick = millis();
  if( tick < g_lastTick )
    g_period = tick + (g_lastTick-0xFFFFFFFF);  //rollover occured
  else
    g_period = tick - g_lastTick;
  g_lastTick = tick;

  //digitalWrite(LEDpin, LOW);     //flash LED - very quickly each time a pluse occus  
}
