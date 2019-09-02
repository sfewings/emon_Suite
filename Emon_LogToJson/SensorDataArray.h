#pragma once
#include <time.h> 
#include <map>
#include <string>
#include <chrono>
#include <ctime>
#include <array>

typedef enum {
	eReading,					//display the actual reading
	eCounterTotal,		//tally the total since start of readings
	eCounterPeriod,		//tally the total usage within each index range
	eRatePerSecond		//calculate the total based on rate/second readings
} ReadingDataType;

template <std::size_t F>
class BaseDataArray
{
public:
	BaseDataArray(ReadingDataType readingDataType)
	{
		m_maxTime = { 0 };
		m_baseTime = { 0 };
		m_readingDataType = readingDataType;

		//calculate GMT offset for later export time operations
		time_t gmt, rawtime = time(NULL);
		struct tm* ptm;
		ptm = gmtime(&rawtime);
		// Request that mktime() looksup dst in timezone database
		ptm->tm_isdst = -1;
		gmt = mktime(ptm);
		m_counterScaleFactor = 1.0;  //default. All counters represent 1 unit of measure

		m_GMTOffset = rawtime - gmt;
	};

	void Add(std::string name, tm time, double data);
	bool ContainsData() { return m_baseTime.tm_year != 0; }
	virtual int SaveToFile(std::string path);
	void ResetReadingDataType(ReadingDataType readingDataType);
	void Clear();
	void SetCounterScaleFactor(double scaleFactor) { m_counterScaleFactor = scaleFactor; }

private:
	bool SaveToJson(std::string path);
	bool SaveToText(std::string path);
	time_t m_GMTOffset;

protected:
	size_t Size() { return F; }
	std::map<std::string, std::array<double, F> > m_sensorData;
	tm m_baseTime;		//minimum time reading
	tm m_maxTime;			//maximum time reading
	ReadingDataType m_readingDataType;
	double m_counterScaleFactor;		//for rain guage where each counter is 0.2mm of rain
	std::map < std::string, long>		m_startCount;			//for eCounterTotal. the counter at start of readings
	std::map < std::string, time_t> m_lastTime;				// for eRatePerSecond. the last second reading
	std::map < std::string, int> m_lastIndex;					// for eCounterPeriod. the last index
	std::map < std::string, long> m_lastCount;				// for eCounterPeriod. the last reading

	virtual time_t GetStartTime() { return 0; }
	virtual int GetIndex(tm time) { return 0; }
	virtual time_t TimeStep()			{	return 0;	}
};
///////////////////

class DayDataArray:public BaseDataArray<(24 * 60)>
{
public:
	DayDataArray(ReadingDataType readingDataType)
		:BaseDataArray(readingDataType)
	{	}

	int Day();
	virtual int SaveToFile(std::string path);

protected:
	virtual time_t GetStartTime();
	virtual int GetIndex(tm time);
	virtual time_t TimeStep();
};

class MonthDataArray :public BaseDataArray<31>
{
public:
	MonthDataArray(ReadingDataType readingDataType)
		:BaseDataArray(readingDataType)
	{	}

	int Month();
	virtual int SaveToFile(std::string path);

protected:
	virtual time_t GetStartTime();
	virtual int GetIndex(tm time);
	virtual time_t TimeStep();
};

class YearDataArray :public BaseDataArray<366>
{
public:
	YearDataArray(ReadingDataType readingDataType)
		:BaseDataArray(readingDataType)
	{}
	
	int Year();
	virtual int SaveToFile(std::string path);

protected:
	virtual time_t GetStartTime();
	virtual int GetIndex(tm time);
	virtual time_t TimeStep();
};

/////////////////
class SensorData
{
public:
	SensorData(std::string dataName, std::string rootPath, 
							ReadingDataType dayReadingDataType, 
							ReadingDataType monthReadingDataType, 
							ReadingDataType yearReadingDataType);


	void Add(std::string name, tm time, double data);
	void Close(bool clear = true);
	void ResetReadingDataType(ReadingDataType dayReadingDataType,
		ReadingDataType monthReadingDataType,
		ReadingDataType yearReadingDataType);
	void SetCounterScaleFactor(double scaleFactor) 
			{
				m_day.SetCounterScaleFactor(scaleFactor);
				m_month.SetCounterScaleFactor(scaleFactor);
				m_year.SetCounterScaleFactor(scaleFactor);
			}

private:
	std::string m_rootPath;
	std::string m_dataName;

	DayDataArray m_day;
	MonthDataArray m_month;
	YearDataArray m_year;
};

