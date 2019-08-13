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
	};

	void Add(std::string name, tm time, double data);
	bool ContainsData() { return m_baseTime.tm_year != 0; }
	virtual int SaveToFile(std::string path);

	void Clear()
	{
		m_sensorData.clear();
		m_baseTime = { 0 };
		m_startCount.clear();
		//m_lastCount.clear();
		m_lastTime.clear();
		m_lastIndex.clear();
	}
private:
	bool SaveToJson(std::string path);
	bool SaveToText(std::string path);
	size_t Size() { return F; }

protected:
	std::map<std::string, std::array<double, F> > m_sensorData;
	tm m_baseTime;		//minimum time reading
	tm m_maxTime;			//maximum time reading
	ReadingDataType m_readingDataType;
	std::map < std::string, long>		m_startCount;			//for eCounterTotal. the counter at start of readings
	std::map < std::string, time_t> m_lastTime;				// for eRatePerSecond. the last second reading
	std::map < std::string, int> m_lastIndex;					// for eCounterPeriod. the last index
	std::map < std::string, long> m_lastCount;				// for eCounterPeriod. the last reading


	virtual int GetIndex(tm time) { return 0; }
	virtual time_t TimeStep()			{	return 0;	}
};
///////////////////

class DayDataArray:public BaseDataArray<(24 * 12)>
{
public:
	DayDataArray(ReadingDataType readingDataType)
		:BaseDataArray(readingDataType)
	{
	}

	int Day()
	{ 
		return m_baseTime.tm_mday; 
	}
	virtual int SaveToFile(std::string path);

protected:
	virtual int GetIndex(tm time)
	{
		const int recordingsPerHour = 12;
		return time.tm_hour * recordingsPerHour + (int)(time.tm_min / 5);
	}

	virtual time_t TimeStep()
	{
		time_t t = time(NULL);
		tm tm1, tm2;
		tm1 = *localtime( &t );
		//localtime_s(&tm1, &t );
		tm2 = tm1;
		tm2.tm_min += 5;

		time_t time1 = mktime(&tm1);
		time_t time2 = mktime(&tm2);

		t = time2 - time1;
		return t;
	}
};

class MonthDataArray :public BaseDataArray<31>
{
public:
	MonthDataArray(ReadingDataType readingDataType)
		:BaseDataArray(readingDataType)
	{	}

	int Month()
	{
		return m_baseTime.tm_mon;
	}
	virtual int SaveToFile(std::string path);

	virtual time_t TimeStep()
	{
		time_t t = time(NULL);
		tm tm1, tm2;
		tm1 = *localtime( &t );
		//localtime_s(&tm1, &t);
		tm2 = tm1;
		tm2.tm_mday += 1;

		time_t time1 = mktime(&tm1);
		time_t time2 = mktime(&tm2);

		t = time2 - time1;
		return t;
	}

protected:
	virtual int GetIndex(tm time)
	{
		return time.tm_mday-1;
	}
};

class YearDataArray :public BaseDataArray<366>
{
public:
	YearDataArray(ReadingDataType readingDataType)
		:BaseDataArray(readingDataType)
	{}
	
	int Year()
	{
		return m_baseTime.tm_year;
	}
	virtual int SaveToFile(std::string path);

protected:
	virtual int GetIndex(tm time)
	{
		//return time.tm_mon;
		return time.tm_yday;
	}

	virtual time_t TimeStep()
	{
		time_t t = time(NULL);
		tm tm1, tm2;
		tm1 = *localtime( &t );
		//localtime_s(&tm1, &t);
		tm2 = tm1;
		//tm2.tm_mon += 1;
		tm2.tm_mday += 1;

		time_t time1 = mktime(&tm1);
		time_t time2 = mktime(&tm2);

		t = time2 - time1;
		return t;
	}
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
private:
	std::string m_rootPath;
	std::string m_dataName;

	DayDataArray m_day;
	MonthDataArray m_month;
	YearDataArray m_year;
};

