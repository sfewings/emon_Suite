#include <stdarg.h>  // For va_start, etc.
#include <memory>    // For std::unique_ptr
#include <fstream> 
#include <sstream> 

#include "SensorDataArray.h"


//std::string string_format(const std::string fmt, ...) {
//	int size = ((int)fmt.size()) * 2 + 50;   // Use a rubric appropriate for your code
//	std::string str;
//	va_list ap;
//	while (1) {     // Maximum two passes on a POSIX system...
//		str.resize(size);
//		va_start(ap, fmt);
//		int n = vsnprintf((char*)str.data(), size, fmt.c_str(), ap);
//		va_end(ap);
//		if (n > -1 && n < size) {  // Everything worked
//			str.resize(n);
//			return str;
//		}
//		if (n > -1)  // Needed size returned
//			size = n + 1;   // For null char
//		else
//			size *= 2;      // Guess at a larger size (OS specific)
//	}
//	return str;
//}

std::string string_format(const std::string fmt_str, ...) {
	int final_n, n = ((int)fmt_str.size()) * 2; /* Reserve two times as much as the length of the fmt_str */
	std::unique_ptr<char[]> formatted;
	va_list ap;
	while (1) {
		formatted.reset(new char[n]); /* Wrap the plain char array into the unique_ptr */
		strcpy_s(&formatted[0],n, fmt_str.c_str());
		va_start(ap, fmt_str);
		final_n = vsnprintf(&formatted[0], n, fmt_str.c_str(), ap);
		va_end(ap);
		if (final_n < 0 || final_n >= n)
			n += abs(final_n - n + 1);
		else
			break;
	}
	return std::string(formatted.get());
}

/////////////////////////

template<std::size_t F>
void BaseDataArray<F>::Add(std::string name, tm time, double data)
{
	if (m_baseTime.tm_year == 0)
	{
		m_baseTime = time;
	}

	_ASSERT(mktime(&time) > mktime(&m_maxTime));
	m_maxTime = time;		//always in chronological order so the latest reading is the latest time!

	int index = GetIndex(time);
	switch (m_readingDataType)
	{
	case eReading:
		m_sensorData[name][index] = std::max(m_sensorData[name][index], data);
		break;
	case eCounter:
		if (m_startCount.find(name) == m_startCount.end())
		{
			m_startCount[name] = (long)data;
		}
		m_sensorData[name][index] = data - m_startCount[name];
		break;
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
			m_sensorData[name][index] += data * elapsed;		//gives the units for the period
		}

		break;
	}
};

template<std::size_t F>
inline int BaseDataArray<F>::SaveToFile(std::string path)
{
	std::string jsonPath = string_format("%s.json", path);
	bool jsonOk = SaveToJson(jsonPath);
	std::string textPath = string_format("%s.txt", path);
	bool textOk = SaveToText(textPath);
	
	return jsonOk && textOk;
}

template<std::size_t F>
bool BaseDataArray<F>::SaveToJson(std::string path)
{
	std::ofstream ofs(path);
	if (!ofs.bad())
	{
		//[{"series":["Power","Solar","HWS"],"data":[[{"x":1562314758226,"y":0},{"x":1562314758226,"y":0}, ...],[...],[...]],"labels":[""]}]
		ofs << "[{\"series\":[";
		bool first = true;
		for (auto it = m_sensorData.begin(); it != m_sensorData.end(); ++it)
		{
			if (!first)
				ofs << ",";
			first = false;
			ofs << "\"" << it->first << "\"";
		}

		ofs << "],\"data\":[";
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
			{
				if (it->second[i] != 0.0)
				{
					time_t t = mktime(&m_baseTime) + (i - GetIndex(m_baseTime)) * TimeStep();
					t -= t % TimeStep();	//remove the fraction of a TimeStep
					if (!innerFirst)
						ofs << ",";
					innerFirst = false;
					ofs << "{\"x\":" << t * 1000 << ",\"y\":" << it->second[i] << "}";
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


template<std::size_t F>
bool BaseDataArray<F>::SaveToText(std::string path)
{
	std::ofstream ofs(path);
	if (!ofs.bad())
	{
		std::string lastLine;
		for (int i = GetIndex(m_baseTime); i <= GetIndex(m_maxTime); i++)
		{
			std::ostringstream line;
			bool hasValues = false;
			time_t t = mktime( &m_baseTime ) + (i-GetIndex(m_baseTime)) * TimeStep();
			t -= t % TimeStep();	//remove the fraction of a TimeStep
			tm time;
			localtime_s(&time, &t);
			ofs << "{\"time\":" << time.tm_year + 1900 << "-" << time.tm_mon + 1 << "-" << time.tm_mday << " ";
			ofs << (time.tm_hour < 10 ? "0" : "") << time.tm_hour << ":"<< (time.tm_min<10?"0":"") <<time.tm_min << ":"<< (time.tm_sec < 10 ? "0" : "") << time.tm_sec ;
			for (auto it = m_sensorData.begin(); it != m_sensorData.end(); ++it)
			{
				if( it->second[i] != 0)
					hasValues = true;
				line << ",\"" << it->first << "\":" << it->second[i];
			}
			line << "},\n";
			if (!hasValues && lastLine.length() != 0)
				ofs << lastLine;
			else
			{
				lastLine = line.str();
				ofs << lastLine;
			}
		}
		ofs.close();
		return true;
	}  	
	
	return false;
}


/////////////////////////

int DayDataArray::SaveToFile(std::string path)
{
	std::string fullPath = string_format("%s\\%02d%02d%02d", path.c_str(), m_baseTime.tm_year + 1900, m_baseTime.tm_mon+1, m_baseTime.tm_mday);

	return BaseDataArray::SaveToFile(fullPath);
}

int MonthDataArray::SaveToFile(std::string path)
{
	return BaseDataArray::SaveToFile(string_format("%s\\%02d%02d", path.c_str(), m_baseTime.tm_year +1900, m_baseTime.tm_mon+1));
}

int YearDataArray::SaveToFile(std::string path)
{
	return BaseDataArray::SaveToFile(string_format("%s\\%02d", path.c_str(), m_baseTime.tm_year + 1900));
}

///////////////////////////

SensorData::SensorData(std::string dataName, std::string rootPath, ReadingDataType readingDataType):
	m_day(readingDataType), 
	m_month(readingDataType),
	m_year(readingDataType)
{
	m_dataName = dataName;
	m_rootPath = rootPath;
}

void SensorData::Add(std::string name, tm time, double data)
{
	if (time.tm_mday != m_day.Day() && m_day.ContainsData())
	{
		m_day.SaveToFile(string_format("%s\\%s", m_rootPath.c_str(), m_dataName.c_str()));
		m_day.Clear();
	}
	m_day.Add(name, time, data);

	if (time.tm_mon != m_month.Month() && m_month.ContainsData())
	{
		m_month.SaveToFile(string_format("%s\\%s", m_rootPath.c_str(), m_dataName.c_str()));
		m_month.Clear();
	}
	m_month.Add(name, time, data);

	if (time.tm_year != m_year.Year() && m_year.ContainsData())
	{
		m_year.SaveToFile(string_format("%s\\%s", m_rootPath.c_str(), m_dataName.c_str()));
		m_year.Clear();
	}
	m_year.Add(name, time, data);
}

void SensorData::Close()
{
	std::string path = string_format("%s\\%s", m_rootPath.c_str(), m_dataName.c_str());
	
	m_day.SaveToFile(path);
	m_day.Clear();
	
	m_month.SaveToFile(path);
	m_month.Clear();
	
	m_year.SaveToFile(path);
	m_year.Clear();
}
