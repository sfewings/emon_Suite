//Data structure to store in EEPROM the last days and months records
//Note EEPROM has a limited (100000) writes so don't overuse the store methods
#include <EEPROM.h>
#include <avr/io.h>
#include <avr/pgmspace.h>
#include "EEPROMHist.h"
#include <HardwareSerial.h>


#define EEPROM_DAY_CONSUMED_OFFSET    0
#define EEPROM_DAY_GENERATED_OFFSET   (EEPROM_DAY_CONSUMED_OFFSET + EEPROM_DAYS)
#define EEPROM_MONTH_CONSUMED_OFFSET  (EEPROM_DAY_GENERATED_OFFSET + EEPROM_DAYS)
#define EEPROM_MONTH_GENERATED_OFFSET (EEPROM_MONTH_CONSUMED_OFFSET + EEPROM_MONTHS)
#define EEPROM_DAY_RAINFALL_OFFSET    (EEPROM_MONTH_GENERATED_OFFSET + EEPROM_MONTHS)
#define EEPROM_MONTH_RAINFALL_OFFSET  (EEPROM_DAY_RAINFALL_OFFSET + EEPROM_DAYS)
#define EEPROM_END                    (EEPROM_MONTH_RAINFALL_OFFSET + EEPROM_MONTHS)

//Note values from original Mega copied in on 27-Aug-12

//If you want to overwrite day and month values place them here. Leave as 0xffff if you do not want to overwrite them 
const unsigned short dayConsumedDefaults[EEPROM_DAYS] ={ 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 
                                                          0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 
                                                          0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 
                                                          0xffff};
                                                             // { 5900, 6204, 9230, 10792, 20862, 7995, 9648, 11026, 4803, 25407, 
                                                             //   18630, 19347, 5653, 26466, 11011, 10037, 11938, 12172, 1658, 22442, 
                                                             //   11360, 1788, 22658, 8524, 7001, 10578, 8471, 17149, 11100, 4018, 
                                                             //   10438};

const unsigned short dayGeneratedDefaults[EEPROM_DAYS] = { 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 
                                                          0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 
                                                          0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 
                                                          0xffff};
                                                               //{3324, 1084, 5583, 4927, 4957, 5016, 5772, 6032, 7189, 7798, 
                                                               // 0xFFFF, 9213, 6784, 9872, 5928, 7694, 5174, 7726, 125, 8673, 
                                                               // 3637, 5531, 8787, 5150, 7639, 7885, 4249, 2386, 5019, 2804, 
                                                               // 1646};

const unsigned short monthConsumedDefaults[EEPROM_MONTHS] ={ 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff};
                                                              //{ 3240, 4033, 2784, 2870, 2863, 2931, 1273, 2738, 3010, 3420, 2931, 2654 };
  
const unsigned short monthGeneratedDefaults[EEPROM_MONTHS] ={ 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff};
                                                              //{ 1574, 2186, 1741, 1810, 1037, 649, 233, 1274, 1767, 1923, 2062, 1981 };

const unsigned short dayRainfallDefaults[EEPROM_DAYS] = 
																											//	{ 0, 0, 0, 0, 0, 0, 9 * 5, 12.4 * 5, 3.2 * 5, 12.4 * 5,
																											//		0.6 * 5, 14.8 * 5, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff,
																											//		0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff,
																											//		0xffff };

																												{ 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 
                                                          0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 
                                                          0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 
                                                          0xffff};

const unsigned short monthRainfallDefaults[EEPROM_MONTHS] = { 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff };
																													//{ 18.6*5, 23.4*5, 15.6*5, 52.4*5, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff};
EEPROMHistory::EEPROMHistory()
{
}

void EEPROMHistory::SerialPrint( const char* title, int EepromOffset, int range )
{
    unsigned short value;
    Serial.print(title);
    Serial.print(" = { ");
    
    for(int i=0; i< range;i++)
    {
      value = readEEPROM(EepromOffset + i);

      Serial.print(value);
      if( i == range-1 )
        Serial.println("};");
      else
        Serial.print(", "); 
      //if( (i+1)%10 == 0)
      //  Serial.println();
    }
}

void EEPROMHistory::init(const char* title, int offset, int range, const unsigned short *defaults)
{
    unsigned short value;

    for(int i=0; i< range;i++)
    {
      //initialise the EEPROM memory if it has never been used before i.e. = 0xFFFF
      value = readEEPROM(offset+i);
      if( value == 0xffff )
        writeEEPROM(offset+i, 0);

      //initialise values from the default array above only if not set to 0xFFFF
      if( defaults[i] != 0xffff )
        writeEEPROM(offset+i, defaults[i]);
    }

    SerialPrint(title, offset, range );
}



short EEPROMHistory::init(int eepromBaseOffset)
{
    m_EEPROMBaseoffset = eepromBaseOffset;

    //  warning. this will reset the EEPROM   
		//hardResetAll();

    // initialise our local variable from EEPROM
    for(int i=0; i< EEPROM_HOURS;i++)
    {
      m_hourConsumed[i] = 0;
      m_hourGenerated[i] = 0;
    }
    
    init("dayConsumed", EEPROM_DAY_CONSUMED_OFFSET, EEPROM_DAYS, dayConsumedDefaults);
    init("dayGenerated", EEPROM_DAY_GENERATED_OFFSET, EEPROM_DAYS, dayGeneratedDefaults );    
    init("monthConsumed", EEPROM_MONTH_CONSUMED_OFFSET, EEPROM_MONTHS, monthConsumedDefaults );    
    init("monthGenerated", EEPROM_MONTH_GENERATED_OFFSET, EEPROM_MONTHS, monthGeneratedDefaults );    
    init("dayRainfall", EEPROM_DAY_RAINFALL_OFFSET, EEPROM_DAYS, dayRainfallDefaults );    
    init("monthRainfall", EEPROM_MONTH_RAINFALL_OFFSET, EEPROM_MONTHS, monthRainfallDefaults );    

    resetMonitoredValues();

   return   m_EEPROMBaseoffset + (EEPROM_MONTH_RAINFALL_OFFSET + EEPROM_MONTHS) * sizeof(unsigned short);
}

void EEPROMHistory::hardResetAll()
{
    //Overwrite EEPROM memory and reset for good
    for(int i=0; i<EEPROM_END; i++)
    {
        Serial.print( i );
        Serial.print( ", ");
				Serial.print(readEEPROM(i), HEX);
				writeEEPROM(i, 0xffff);
        Serial.print( ", ");
        Serial.println( readEEPROM(i), HEX );
    }
}

void EEPROMHistory::resetValue(HistoryIndex hdm, short unit )
{
  if(unit < 0 || unit >= getIndexRange(hdm) )
     return; 
  
  switch(hdm)
  {
     case eHour: 
         m_hourConsumed[unit]  = 0;
         m_hourGenerated[unit] = 0;
       break;
     case eDay:
        writeEEPROM(EEPROM_DAY_CONSUMED_OFFSET+unit, 0 );
        writeEEPROM(EEPROM_DAY_GENERATED_OFFSET+unit, 0);
     break;
     case eMonth:
        writeEEPROM(EEPROM_MONTH_CONSUMED_OFFSET+unit, 0 );
        writeEEPROM(EEPROM_MONTH_GENERATED_OFFSET+unit, 0);
      break;     
  }
}    

void EEPROMHistory::addValue(HistoryIndex hdm, short unit, unsigned short consumed, unsigned short generated )
{
  if(unit < 0 || unit >= getIndexRange(hdm) )
     return; 
  unsigned short alreadyConsumed, alreadyGenerated;
  switch(hdm)
  {
     case eHour: 
         m_hourConsumed[unit]  += consumed;
         m_hourGenerated[unit] += generated;
       break;
     case eDay:
        getValue(eDay, unit, &alreadyConsumed, &alreadyGenerated );
        writeEEPROM(EEPROM_DAY_CONSUMED_OFFSET+unit, alreadyConsumed + consumed );
        writeEEPROM(EEPROM_DAY_GENERATED_OFFSET+unit, alreadyGenerated + generated);
      break;     
     case eMonth:
        getValue(eMonth, unit, &alreadyConsumed, &alreadyGenerated );
        //only tally 10Whrs for the month so we can fit into unsigned short!
        writeEEPROM(EEPROM_MONTH_CONSUMED_OFFSET+unit, alreadyConsumed + (consumed/100));
        writeEEPROM(EEPROM_MONTH_GENERATED_OFFSET+unit, alreadyGenerated + (generated/100));
      break;     
  }
}
    
void EEPROMHistory::getValue(HistoryIndex hdm, short unit, unsigned short* pConsumed, unsigned short* pGenerated )
{
  if(unit < 0 || unit >= getIndexRange(hdm) )
  {
    (*pConsumed) = 0;
    (*pGenerated) = 0; 
    return; 
  }
  
  switch(hdm)
  {
     case eHour: 
         (*pConsumed) = m_hourConsumed[unit];
         (*pGenerated) = m_hourGenerated[unit];
       break;
     case eDay:
         *pConsumed = readEEPROM(EEPROM_DAY_CONSUMED_OFFSET+unit);
         *pGenerated = readEEPROM(EEPROM_DAY_GENERATED_OFFSET+unit);
      break;     
     case eMonth:
         *pConsumed = readEEPROM(EEPROM_MONTH_CONSUMED_OFFSET+unit);
         *pGenerated = readEEPROM(EEPROM_MONTH_GENERATED_OFFSET+unit);
      break;     
  }
}

void EEPROMHistory::getTotalTo(HistoryIndex hdm, short unit, unsigned short* pConsumed, unsigned short* pGenerated )
{
  unsigned long ulConsumed, ulGenerated;

  (*pConsumed)  = 0;
  (*pGenerated) = 0; 
  ulConsumed = 0;
  ulGenerated = 0;

  if(unit < 0 || unit > getIndexRange(hdm) )
  {
    return; 
  }

  for(int i =0; i<=unit; i++)
  {  
    unsigned short consumed, generated;
    getValue(hdm, i, &consumed, &generated );
    ulConsumed += consumed;
    ulGenerated += generated;
  }
  //Serial.print("Total consumed:");
  //Serial.print(ulConsumed, DEC);
  //unsigned short us = (unsigned short) ulConsumed;
  //Serial.print(" as unsigned short:");
  //Serial.print(us, DEC);
  //us = (unsigned short) (ulConsumed/10);
  //Serial.print(" as unsigned short /10:");
  //Serial.print(us, DEC);
  
  
  if( hdm == eDay )
  {
    //return day totals in 10Wh as wHrs overflows unsigned short!
    (*pConsumed) = (unsigned short) (ulConsumed/10);  
    (*pGenerated) = (unsigned short) (ulGenerated/10);
  }
  else
  {
    //hour returned as unsigned short. Month values already stored as kWh
    (*pConsumed) = (unsigned short) ulConsumed;  
    (*pGenerated) = (unsigned short) ulGenerated;
  }      
}
        
short EEPROMHistory::getIndexRange(HistoryIndex hdm )
{
  switch(hdm)
  {
     case eHour: 
       return EEPROM_HOURS;
       break;
     case eDay:
       return EEPROM_DAYS;
      break;     
     case eMonth:
       return EEPROM_MONTHS;
      break;  
     default:
       return 0;
  }
} 

void EEPROMHistory::addRainfall(HistoryIndex hdm, short unit, unsigned short rainfall)
{
  if(unit < 0 || unit >= getIndexRange(hdm) )
     return; 
  switch(hdm)
  {
     case eHour: 
       break;
     case eDay:
        writeEEPROM(EEPROM_DAY_RAINFALL_OFFSET+unit, getRainfall(hdm, unit) + rainfall );
      break;     
     case eMonth:
        writeEEPROM(EEPROM_MONTH_RAINFALL_OFFSET+unit, getRainfall(hdm, unit) + rainfall );
      break;     
  }

}

unsigned short EEPROMHistory::getRainfall(HistoryIndex hdm, short unit )
{
  if(unit < 0 || unit >= getIndexRange(hdm) )
     return 0; 

  switch(hdm)
  {
     case eHour: 
         return 0;
     case eDay:
         return readEEPROM(EEPROM_DAY_RAINFALL_OFFSET+unit);
     case eMonth:
         return readEEPROM(EEPROM_MONTH_RAINFALL_OFFSET+unit);
  }
  return 0;
}

unsigned short EEPROMHistory::getRainfallTo(HistoryIndex hdm, short unit )
{
  if(unit < 0 || unit >= getIndexRange(hdm) )
     return 0; 

  unsigned short totalRainfall = 0;
  for(int i =0; i<=unit; i++)
  {  
    totalRainfall += getRainfall(hdm, i );
  }

  return totalRainfall;
}


void EEPROMHistory::resetRainfall(HistoryIndex hdm, short unit )
{
  if(unit < 0 || unit >= getIndexRange(hdm) )
     return; 
  switch(hdm)
  {
     case eHour: 
       break;
     case eDay:
        writeEEPROM(EEPROM_DAY_RAINFALL_OFFSET+unit, 0);
     break;
     case eMonth:
        writeEEPROM(EEPROM_MONTH_RAINFALL_OFFSET+unit, 0 );
      break;     
  }
}

unsigned short EEPROMHistory::readEEPROM(int offset )
{
    unsigned short value = 0;
    char* pc = (char*) &value;

    for(long l=0; l< sizeof(unsigned short);l++)
    {
      *(pc+l) = m_eeprom.read(m_EEPROMBaseoffset + offset*sizeof(unsigned short) + l);
    }

    return value;
}
    
void EEPROMHistory::writeEEPROM(int offset, unsigned short value )
{
    char* pc = (char*) &value;

    for(long l=0; l< sizeof(unsigned short);l++)
    {
      m_eeprom.write(m_EEPROMBaseoffset + offset*sizeof(unsigned short) + l, *(pc+l));
    }
}   

void EEPROMHistory::addMonitoredValues(const int* temperature, const unsigned short voltage )
{
    for(int t=0; t< m_NUM_THERMOMETERS;t++)
    {
      if( temperature[t] < m_temperature[t][0] )
        m_temperature[t][0] = temperature[t];
      if( temperature[t] > m_temperature[t][1] )
        m_temperature[t][1] = temperature[t];

      m_temperature[t][2] = (int)(((double)m_temperature[t][2]* m_N + temperature[t] )/(m_N+1.0));
    }

    if( voltage < m_voltage[0] )
      m_voltage[0] = voltage;
    if( voltage > m_voltage[1] )
      m_voltage[1] = voltage;
    m_voltage[2] = (unsigned short)(((double)m_voltage[2]* m_N + voltage )/(m_N+1.0));
    
    m_N++;
}

void EEPROMHistory::getMonitoredValues(ValueStatistic stats, int *temperature, unsigned short *pVoltage)
{
  for(int t=0; t< m_NUM_THERMOMETERS;t++)
  {
    temperature[t] = m_temperature[t][(int) stats];  
  }
	if ( pVoltage != NULL )
		(*pVoltage) = m_voltage[(int) stats];  
}

void EEPROMHistory::resetMonitoredValues()
{
  for(int t=0; t< m_NUM_THERMOMETERS;t++)
  {
    m_temperature[t][0] = 10000;
    m_temperature[t][1] = -10000;
    m_temperature[t][2] = 0;
  }

  m_voltage[0] = 1000;
  m_voltage[1] = 0;
  m_voltage[2] = 0;

  m_N = 0;
}
