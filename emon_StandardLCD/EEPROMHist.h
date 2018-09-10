//Data structure to store in EEPROM the last days and months records
//Note EEPROM has a limited (100000) writes so don't overuse the store methods

#define EEPROM_HOURS         24
#define EEPROM_DAYS          31
#define EEPROM_MONTHS        12

typedef enum {
  eHour  = 0
  ,eDay 
  ,eMonth
}  HistoryIndex;

typedef enum {
  eValueStatisticMin = 0,
  eValueStatisticMax,
  eValueStatisticAverage,
} ValueStatistic;
  
typedef enum {
 eTemperature1,
 eTemperature2,
 eVoltage,
 eConsumed,
 eGenerated
} MonitoredValue;

  

class EEPROMHistory
{
  public:
    EEPROMHistory();

    short init(int eepromBaseffset );
    void hardResetAll();
    void resetValue(HistoryIndex hdm, short unit );
    void addValue(HistoryIndex hdm, short unit, unsigned short consumed, unsigned short generated );
    void getValue(HistoryIndex hdm, short unit, unsigned short *pConsumed, unsigned short *pGenerated );
    void getTotalTo(HistoryIndex hdm, short unit, unsigned short *pConsumed, unsigned short *pGenerated );
    short getIndexRange(HistoryIndex hdm );

    void addRainfall(HistoryIndex hdm, short unit, unsigned short rainfall);
    unsigned short getRainfall(HistoryIndex hdm, short unit );
    unsigned short getRainfallTo(HistoryIndex hdm, short unit );
    void resetRainfall(HistoryIndex hdm, short unit );

    void addMonitoredValues(const int* temperature, const unsigned short voltage );
    void getMonitoredValues(ValueStatistic stats, int* temperature, unsigned short *pVoltage );
    void resetMonitoredValues();
    
    
  private:
    unsigned short m_EEPROMBaseoffset;
    EEPROMClass   m_eeprom;
    static const short m_NUM_THERMOMETERS = 3;
    int m_temperature[m_NUM_THERMOMETERS][3];
    unsigned short m_voltage[3];
    int  m_N;
    
    unsigned short m_hourConsumed[EEPROM_HOURS];
    unsigned short m_hourGenerated[EEPROM_HOURS];

	void init(const char* title, int offset, int range, const uint16_t *defaults); // prog_uint16_t *defaults); // const unsigned short *defaults);
    void SerialPrint( const char* title, int EepromOffset, int range );
    unsigned short readEEPROM(int offset );
    void writeEEPROM(int offset, unsigned short value );
};
