#include <stdarg.h>  // For va_start, etc.
#include <memory>    // For std::unique_ptr
#include <fstream> 
#include <sstream> 
#include <cstring>
#include <iostream>
#include <float.h>  //DBL_MAX
#include "SensorDataArray.h"


template<typename ... Args>
std::string string_format(const std::string& format, Args ... args)
{
	size_t size = snprintf(nullptr, 0, format.c_str(), args ...) + 1; // Extra space for '\0'
	std::unique_ptr<char[]> buf(new char[size]);
	snprintf(buf.get(), size, format.c_str(), args ...);
	return std::string(buf.get(), buf.get() + size - 1); // We don't want the '\0' inside
}


/////////////////////////

template<std::size_t F>
void BaseDataArray<F>::Add(std::string name, tm time, double data)
{
	if (m_baseTime.tm_year == 0)
	{
		m_baseTime = time;
	}

	////_ASSERT(mktime(&time) >= mktime(&m_maxTime));
	m_maxTime = time;		//always in chronological order so the latest reading is the latest time!

	int index = GetIndex(time);

	//Can't index outside the array size
	//_ASSERT(index < Size() );
	if ((size_t)index >= Size())
		return;

	if (m_sensorData.find(name) == m_sensorData.end())
	{
		for (size_t l = 0; l < Size(); l++)
			m_sensorData[name][l] = -DBL_MAX;
	}

	switch (m_readingDataType)
	{
	case eReading:
		m_sensorData[name][index] = std::max(m_sensorData[name][index], data);
		break;
	case eCounterTotal:
		if (m_startCount.find(name) == m_startCount.end())
		{
			m_startCount[name] = (long)data;
		}
		if(data >= m_startCount[name] )	//can't go backwards!
			m_sensorData[name][index] = data - m_startCount[name];
		break;
	case eCounterPeriod:
	{
		int indexes = 1;
		if (m_lastIndex.find(name) == m_lastIndex.end())
		{
			m_startCount[name] = (long)data;
			m_lastCount[name] = (long)data;
			m_lastIndex[name] = index;
		}
		else if (m_lastIndex[name] != index)
		{
			m_startCount[name] = (long)m_lastCount[name];
			indexes = index - m_lastIndex[name];
			m_lastIndex[name] = index;
		}
		m_lastCount[name] = (long)data;
		m_sensorData[name][index] = (data - m_startCount[name]) /(double)indexes ;
		break;
	}
	case eRatePerSecond:
		if (m_lastTime.find(name) == m_lastTime.end() )
		{
			m_lastTime[name] = mktime(&time);
		}
		else
		{
			time_t thisTime = mktime(&time);
			time_t elapsed =  thisTime - m_lastTime[name];			//returns seconds since last reading
			m_lastTime[name] = thisTime;
			if (m_sensorData[name][index] == -DBL_MAX)
				m_sensorData[name][index] = 0;	//first reading for this index
			m_sensorData[name][index] += data/3600.0 * elapsed;		//convert rate per second to rate per hour
		}
		break;
	}
};


template<std::size_t F>
inline int BaseDataArray<F>::SaveToFile(std::string path)
{
	bool jsonOk = false;
	bool textOk = false;

	if (m_sensorData.size())
	{
		char buf[2048];

		sprintf(buf, "%s.json", path.c_str());
		std::string jsonPath = buf;
		jsonOk = SaveToJson(jsonPath);

		sprintf(buf, "%s.txt", path.c_str());
		std::string textPath = buf;
		textOk = SaveToText(textPath);
	}
	return jsonOk && textOk;
}

template<std::size_t F>
bool BaseDataArray<F>::SaveToJson(std::string path)
{
	std::ofstream ofs(path, std::ios_base::out | std::ios_base::trunc);
	if (!ofs.bad())
	{
		//[{"series":["Power","Solar","HWS"],"data":[[{"x":1562314758226,"y":0},{"x":1562314758226,"y":0}, ...],[...],[...]],"labels":[""]}]
		ofs << "[{\"series\":[\"\",";
		bool first = true;
		for (auto it = m_sensorData.begin(); it != m_sensorData.end(); ++it)
		{
			if (!first)
				ofs << ",";
			first = false;
			ofs << "\"" << it->first << "\"";
		}

		ofs << "],\"data\":[";

		ofs << "[";
		first = true;
		long long periodStart = GetStartTime();
		for (int i = 0; i < Size(); i++)
		{
			if (!first)
				ofs << ",";
			first = false;
			ofs << "{\"x\":" << (periodStart +i*TimeStep())* 1000 << ",\"y\":" << 0 << "}";
//			ofs << "{\"x\":" << (periodStart + TimeStep() * Size()) * 1000 << ",\"y\":" << 0 << "}],";
		}
		ofs << "],";

		std::string lastLine;
		first = true;
		for (auto it = m_sensorData.begin(); it != m_sensorData.end(); ++it)
		{
			if (!first)
				ofs << ",";
			ofs << "[";
			first = false;

			bool innerFirst = true;
			for (int i = GetIndex(m_baseTime); i <= GetIndex(m_maxTime); i++)
//			for (int i = 0; i < Size(); i++)
			{
				if (it->second[i] != -DBL_MAX)	//skip outputs if no value has been set
				{
					long long t = mktime(&m_baseTime) + ((time_t)i - (time_t)GetIndex(m_baseTime)) * TimeStep();
					t -= (t + m_GMTOffset) % TimeStep(); //remove the fraction of a TimeStep based on GMT time-base
					//t -= t % TimeStep();	//remove the fraction of a TimeStep
					if (!innerFirst)
						ofs << ",";
					innerFirst = false;
					ofs << "{\"x\":" << t*1000 << ",\"y\":" << it->second[i]* m_counterScaleFactor << "}";

				}
			}
			ofs << "]";
		}
		ofs << "]";
		ofs << ",\"labels\": [\"\"]}]";

		ofs.close();
		return true;
	}

	return false;
}


//save toi .csv text format
template<std::size_t F>
bool BaseDataArray<F>::SaveToText(std::string path)
{
	std::ofstream ofs(path, std::ios_base::out | std::ios_base::trunc);
	if (!ofs.bad())
	{
		ofs << "time";
		for (auto it = m_sensorData.begin(); it != m_sensorData.end(); ++it)
		{
			ofs << "," << it->first;
		}
		ofs << "\n";


		std::string lastLine;
		for (int i = GetIndex(m_baseTime); i <= GetIndex(m_maxTime); i++)
		{
			time_t t = mktime(&m_baseTime) + ((time_t)i - GetIndex(m_baseTime)) * TimeStep();
			t -= (t + m_GMTOffset) % TimeStep(); //remove the fraction of a TimeStep based on GMT time-base
			tm time;
			time = *localtime(&t);
			ofs << time.tm_year + 1900 << "-" << time.tm_mon + 1 << "-" << time.tm_mday << " ";
			ofs << (time.tm_hour < 10 ? "0" : "") << time.tm_hour << ":" << (time.tm_min < 10 ? "0" : "") << time.tm_min << ":" << (time.tm_sec < 10 ? "0" : "") << time.tm_sec;
			for (auto it = m_sensorData.begin(); it != m_sensorData.end(); ++it)
			{
				ofs << ",";
				if (it->second[i] != -DBL_MAX)
					ofs << it->second[i] * m_counterScaleFactor;
			}
			ofs << "\n";
		}
		ofs.close();
		return true;
	}

	return false;
}

//save to pree JSON txt format. Suitable for display in Flot charts. I think!
//template<std::size_t F>
//bool BaseDataArray<F>::SaveToText(std::string path)
//{
//	std::ofstream ofs(path);
//	if (!ofs.bad())
//	{
//		std::string lastLine;
//		for (int i = GetIndex(m_baseTime); i <= GetIndex(m_maxTime); i++)
//		{
//			std::ostringstream line;
//			bool hasValues = false;
//			time_t t = mktime( &m_baseTime ) + ((time_t)i-GetIndex(m_baseTime)) * TimeStep();
//			t -=  (t+ m_GMTOffset) % TimeStep(); //remove the fraction of a TimeStep based on GMT time-base
//			tm time;
//			time = *localtime(&t);
//			//localtime_s(&time, &t);
//			ofs << "{\"time\":" << time.tm_year + 1900 << "-" << time.tm_mon + 1 << "-" << time.tm_mday << " ";
//			ofs << (time.tm_hour < 10 ? "0" : "") << time.tm_hour << ":"<< (time.tm_min<10?"0":"") <<time.tm_min << ":"<< (time.tm_sec < 10 ? "0" : "") << time.tm_sec ;
//			for (auto it = m_sensorData.begin(); it != m_sensorData.end(); ++it)
//			{
//				if( it->second[i] != 0)
//					hasValues = true;
//				line << ",\"" << it->first << "\":" << it->second[i]* m_counterScaleFactor;
//			}
//			line << "},\n";
//			if (!hasValues && lastLine.length() != 0)
//				ofs << lastLine;
//			else
//			{
//				lastLine = line.str();
//				ofs << lastLine;
//			}
//		}
//		ofs.close();
//		return true;
//	}  	
//	
//	return false;
//}


template<std::size_t F>
void  BaseDataArray<F>::Clear()
{
	m_sensorData.clear();
	m_baseTime = { 0 };
	m_startCount.clear();
	//m_lastCount.clear();
	m_lastTime.clear();
	m_lastIndex.clear();
}

int DayDataArray::SaveToFile(std::string path)
{
	return BaseDataArray::SaveToFile(string_format("%s/%02d%02d%02d", path.c_str(), m_baseTime.tm_year +1900, m_baseTime.tm_mon+1, m_baseTime.tm_mday));
}

int DayDataArray::Day()
{
	return m_baseTime.tm_mday;
}

time_t DayDataArray::GetStartTime() 
{ 
	tm time = m_baseTime;
	time.tm_hour = time.tm_min = time.tm_sec = 0;
	
	return mktime( &time) ;
}

int DayDataArray::GetIndex(tm time)
{
	const int recordingsPerHour = (int)Size() / 24;
	const int minutesPerIndex = 24 * 60 / (int)Size();
	return time.tm_hour * recordingsPerHour + (int)(time.tm_min / minutesPerIndex);
}

time_t DayDataArray::TimeStep()
{
	const int minutesPerIndex = 24 * 60 / (int)Size();
	time_t t = time(NULL);
	tm tm1, tm2;
	tm1 = *localtime(&t);
	tm2 = tm1;
	tm2.tm_min += minutesPerIndex;

	time_t time1 = mktime(&tm1);
	time_t time2 = mktime(&tm2);

	t = time2 - time1;
	return t;
}

/////////
int MonthDataArray::SaveToFile(std::string path)
{
	return BaseDataArray::SaveToFile(string_format("%s/%02d%02d", path.c_str(), m_baseTime.tm_year +1900, m_baseTime.tm_mon+1));
}

int MonthDataArray::Month()
{
	return m_baseTime.tm_mon;
}

time_t MonthDataArray::GetStartTime()
{
	tm time = m_baseTime;
	time.tm_mday = 1;
	time.tm_hour = time.tm_min = time.tm_sec = 0;

	return mktime(&time);
}

int MonthDataArray::GetIndex(tm time)
{
	return time.tm_mday - 1;
}

time_t MonthDataArray::TimeStep()
{
	time_t t = time(NULL);
	tm tm1, tm2;
	tm1 = *localtime(&t);
	tm2 = tm1;
	tm2.tm_mday += 1;

	time_t time1 = mktime(&tm1);
	time_t time2 = mktime(&tm2);

	t = time2 - time1;
	return t;
}

////////////////

int YearDataArray::Year()
{
	return m_baseTime.tm_year;
}

time_t YearDataArray::GetStartTime()
{
	tm time = m_baseTime;
	time.tm_mday = 1;
	time.tm_mon = time.tm_hour = time.tm_min = time.tm_sec = 0;

	return mktime(&time);
}


int YearDataArray::SaveToFile(std::string path)
{
	return BaseDataArray::SaveToFile(string_format("%s/%02d", path.c_str(), m_baseTime.tm_year + 1900));
}

int YearDataArray::GetIndex(tm time)
{
	return time.tm_yday;
}

time_t YearDataArray::TimeStep()
{
	time_t t = time(NULL);
	tm tm1, tm2;
	tm1 = *localtime(&t);
	tm2 = tm1;
	//tm2.tm_mon += 1;
	tm2.tm_mday += 1;

	time_t time1 = mktime(&tm1);
	time_t time2 = mktime(&tm2);

	t = time2 - time1;
	return t;
}


///////////////////////////

SensorData::SensorData(std::string dataName, std::string rootPath, 
	ReadingDataType dayReadingDataType, 
	ReadingDataType monthReadingDataType, 
	ReadingDataType yearReadingDataType ):
	m_day(dayReadingDataType),
	m_month(monthReadingDataType),
	m_year(yearReadingDataType)
{
	m_dataName = dataName;
	m_rootPath = rootPath;
}

void SensorData::Add(std::string name, tm time, double data)
{
	if (time.tm_mday != m_day.Day() && m_day.ContainsData())
	{
		m_day.SaveToFile(string_format("%s/%s", m_rootPath.c_str(), m_dataName.c_str()));
		m_day.Clear();
	}
	m_day.Add(name, time, data);

	if (time.tm_mon != m_month.Month() && m_month.ContainsData())
	{
		m_month.SaveToFile(string_format("%s/%s", m_rootPath.c_str(), m_dataName.c_str()));
		m_month.Clear();
	}
	m_month.Add(name, time, data);

	if (time.tm_year != m_year.Year() && m_year.ContainsData())
	{
		m_year.SaveToFile(string_format("%s/%s", m_rootPath.c_str(), m_dataName.c_str()));
		m_year.Clear();
	}
	m_year.Add(name, time, data);
}


void SensorData::Close(bool clear /*=true*/)
{
	std::string path = string_format("%s/%s", m_rootPath.c_str(), m_dataName.c_str());
	
	m_day.SaveToFile(path);
	if( clear )
		m_day.Clear();
	
	m_month.SaveToFile(path);
	if (clear)
		m_month.Clear();
	
	m_year.SaveToFile(path);
	if (clear)
		m_year.Clear();
}
