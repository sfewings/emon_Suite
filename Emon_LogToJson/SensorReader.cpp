#include <fstream>




#include "..\\EmonShared\EmonShared.h"
#include "SensorReader.h"

#include <time.h>
#include <iomanip>
#include <sstream>
#include <filesystem>
#include <iostream>
namespace fs = std::experimental::filesystem;

extern "C" char* strptime(const char* s,
	const char* f,
	struct tm* tm) {
	// Isn't the C++ standard lib nice? std::get_time is defined such that its
	// format parameters are the exact same as strptime. Of course, we have to
	// create a string stream first, and imbue it with the current C locale, and
	// we also have to make sure we return the right things if it fails, or
	// if it succeeds, but this is still far simpler an implementation than any
	// of the versions in any of the C standard libraries.
	std::istringstream input(s);
	input.imbue(std::locale(setlocale(LC_ALL, nullptr)));
	input >> std::get_time(tm, f);
	if (input.fail()) {
		return nullptr;
	}
	return (char*)(s + (int) input.tellg());
}



SensorReader::SensorReader(std::string rootPath):
	m_temperatures("temp", rootPath, eReading, eReading, eReading),
	m_power("power", rootPath, eReading, eRatePerSecond, eRatePerSecond),
//	m_powerTotal("powerTotal", rootPath, eRatePerSecond),
	m_rainFall("rain", rootPath, eCounterTotal, eCounterTotal, eCounterTotal),
	m_supplyV("supplyV", rootPath, eReading, eReading, eReading),
	m_HWS("HWS", rootPath, eReading, eReading, eReading),
	m_water("water", rootPath, eReading, eReading, eReading),
	m_waterUsage("waterUsage", rootPath, eCounterTotal, eCounterPeriod, eCounterPeriod)
{
	m_rootPath = rootPath;
	if (fs::is_directory(rootPath) && rootPath.length()> 5)
	{
		fs::remove_all(rootPath);
	}
	fs::create_directory(rootPath);
	fs::create_directory(rootPath + "/temp");
	fs::create_directory(rootPath + "/rain");
	fs::create_directory(rootPath + "/hws");
	fs::create_directory(rootPath + "/water");
	fs::create_directory(rootPath + "/waterUsage");
	fs::create_directory(rootPath + "/power");
	fs::create_directory(rootPath + "/supplyV");
}

void SensorReader::AddFile(std::string path)
{
	std::cout << path << std::endl;

	int lineCount = 0;

	std::ifstream file(path);
	if (file.is_open())
	{
		std::string line;
		while (std::getline(file, line))
		{
			tm time;
			size_t pos = GetTime(line, time);
			if (pos != std::string::npos)
			{
				AddReading(line.substr(pos+1), time);
			}
			if (++lineCount % 100 == 0)
				std::cout << '\r' << lineCount;
		}
		file.close();
		std::cout << '\r' << lineCount << std::endl;
	}
}

unsigned short SensorReader::StringToNode(std::string line)
{
	size_t len = line.length();
	if (line.compare(0, 5, "pulse") == 0) return PULSE_JEENODE;
	if (line.compare(0, 4, "disp" ) == 0) return DISPLAY_NODE;
	if (line.compare(0, 4, "base" ) == 0) return BASE_JEENODE;
	if (line.compare(0, 4, "temp" ) == 0) return TEMPERATURE_JEENODE;
	if (line.compare(0, 3, "wtr"  ) == 0) return WATERLEVEL_NODE;
	if (line.compare(0, 3, "hws"  ) == 0) return HWS_JEENODE;
	if (line.compare(0, 4, "rain" ) == 0) return RAIN_NODE;
	if (line.compare(0, 3, "scl"  ) == 0) return SCALE_NODE;
	if (line.compare(0, 3, "log"  ) == 0) return EMON_LOGGER;
	return 0;
}




size_t SensorReader::GetTime(std::string line, tm &time)
{
	size_t pos = line.find_first_of(",", 0);
	if (pos != std::string::npos)
	{
		std::string timeString = line.substr(0, pos);
		strptime(timeString.c_str(), "%d/%m/%Y %H:%M:%S", &time);
		mktime(&time);	// call to fill out all of time struct

		//long long ll = atoll(timeString.c_str());
		//if (ll == 0)
		//	return std::string::npos;
		//gmtime_s(&time,  &ll);
	}

	return pos;
}

void SensorReader::AddReading(std::string reading, tm time)
{
	switch (StringToNode(reading))
	{
		case RAIN_NODE:	
		{
			PayloadRain rain;
			if (EmonSerial::ParseRainPayload((char*)reading.c_str(), &rain))
			{
				if (rain.rainCount != 0)
				{
					m_temperatures.Add("Outside", time, rain.temperature / 100.0);
					m_rainFall.Add("Rain", time, rain.rainCount * 0.2);
					if (rain.supplyV / 1000.0 < 5)
						m_supplyV.Add("Rain Gauge", time, rain.supplyV / 1000.0);
				}
			}
			break;
		}
		case PULSE_JEENODE: 
		{
			PayloadPulse pulse;
			if (EmonSerial::ParsePulsePayload((char*)reading.c_str(), &pulse))
			{
				std::string sensor[4] = { "HWS", "Produced", "Consumed", "Imported" };
				for (int i = 0; i< PULSE_NUM_PINS; i++)
				{
					m_power.Add(sensor[i], time, pulse.power[i]);
					//m_powerTotal.Add(sensor[i], time, pulse.power[i] / 3600.0);
				}
			}
		break;
		}
		case BASE_JEENODE: 
		{
			//Nothing to log
			break;
		}
		case DISPLAY_NODE:
		{
			PayloadDisp disp;
			if (EmonSerial::ParseDispPayload((char*)reading.c_str(), &disp))
			{
				std::string sensor[4] = { "Kitchen", "Office", "unused", "Upstairs" };
				if(disp.subnode < 4)
					m_temperatures.Add(sensor[disp.subnode], time, disp.temperature/100.0);
			}
			break;
		}
		break;
		case TEMPERATURE_JEENODE: 
		{
			PayloadTemperature temp;
			if (EmonSerial::ParseTemperaturePayload((char*)reading.c_str(), &temp))
			{
				std::string sensor[4][4] = { 
					{"Under roof", "Living room slab", "Living room", "Ceiling space"}, 
					{"Garage", "Beer fridge", "unused", "unused"},
					{"unused", "unused", "unused", "unused"},
					{"unused", "unused", "unused", "unused"}
			};

				//_ASSERT(temp.subnode < 4);
				if (temp.subnode < 4)
				{
					for (int i = 0; i < temp.numSensors; i++)
					{
						if (temp.temperature[i] > 0 && temp.temperature[i] / 100 < 70 )	//filter out some noisy temperature values
						{
							m_temperatures.Add(sensor[temp.subnode][i], time, temp.temperature[i] / 100.0);
						}
					}
					if(temp.supplyV / 1000.0 < 5)
						m_supplyV.Add("t" + std::to_string(temp.subnode), time, temp.supplyV / 1000.0);
				}
			}
			break;
		}
		break;
		case HWS_JEENODE: 
		{
			PayloadHWS hws;
			if (EmonSerial::ParseHWSPayload((char*)reading.c_str(), &hws))
			{
				for (int i = 0; i < HWS_TEMPERATURES; i++)
				{
					if(hws.temperature[i] > 0 && hws.temperature[i] < 110)
					m_HWS.Add("Temp " + std::to_string(i), time, hws.temperature[i]);
				}
				for (int i = 0; i < HWS_PUMPS; i++)
				{
					m_HWS.Add("Pump " + std::to_string(i), time, hws.pump[i]*(i+5));
				}
			}
			break;
		}
		case EMON_LOGGER: 
			//nothing to log
			break;
		case WATERLEVEL_NODE:
		{
			PayloadWater water;
			if (EmonSerial::ParseWaterPayload((char*)reading.c_str(), &water))
			{
				if(water.waterHeight < 2200)
					m_water.Add("wh" + std::to_string(water.subnode), time, water.waterHeight);
				if(water.flowCount != 0 && (time.tm_year >119 || (time.tm_year >= 119 && time.tm_yday > 205)) ) //didn't log correctly until 24Jul2019
					m_waterUsage.Add("wf" + std::to_string(water.subnode), time, water.flowCount/1000);
			}
			break;
		}
		case SCALE_NODE:
			//todo:
			break;
		default: 
			break;
	}
}

void SensorReader::Close()
{
	m_temperatures.Close();
	m_power.Close();
	//m_powerTotal.Close();
	m_rainFall.Close();
	m_supplyV.Close();
	m_HWS.Close();
	m_water.Close();
	m_waterUsage.Close();
}
