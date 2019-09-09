#include <fstream>


#include "../EmonShared/EmonShared.h"
#include "SensorReader.h"

#include <time.h>
#include <iomanip>
#include <sstream>
#include <math.h>

#include <experimental/filesystem>
//#include <filesystem>
#include <iostream>

#define TEMPERATURE_DESPIKE 500.0				//Despike any temperature ereading greater than 5 celcius from the moving average
#define TEMPERATURE_SMOOTHING_WINDOW 5.0	// the moving average for smoothing temperature values

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
	m_rainFall("rain", rootPath, eCounterTotal, eCounterTotal, eCounterTotal),
	m_supplyV("supplyV", rootPath, eReading, eReading, eReading),
	m_HWS("hws", rootPath, eReading, eReading, eReading),
	m_water("water", rootPath, eReading, eReading, eReading),
	m_waterUsage("waterUsage", rootPath, eCounterTotal, eCounterPeriod, eCounterPeriod),
	m_scale("scale", rootPath,eReading, eReading, eReading)
{
	m_rootPath = rootPath;
	if (fs::is_directory(rootPath) && rootPath.length()> 5)
	{
		fs::remove_all(rootPath);
		#ifdef __linux__
			usleep(100000);  /* sleep for 100 milliSeconds */
		#else
			Sleep(100);
		#endif
	}
	fs::create_directory(rootPath);
	fs::create_directory(rootPath + "/temp");
	fs::create_directory(rootPath + "/rain");
	fs::create_directory(rootPath + "/hws");
	fs::create_directory(rootPath + "/water");
	fs::create_directory(rootPath + "/waterUsage");
	fs::create_directory(rootPath + "/power");
	fs::create_directory(rootPath + "/supplyV");
	fs::create_directory(rootPath + "/scale");

	m_rainFall.SetCounterScaleFactor(0.2); //rainfall is 0.2mm for every counter
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
	}

	return pos;
}

bool SensorReader::FilterTemperature(std::string sensorName, double temperature, double& smoothedTemperature)
{
	bool useReading = false;
	if (temperature > 0 && temperature / 100 < 100)	//filter out some noisy temperature values
	{
		//initialise. Hope the inital value is not bogus as all subsequent values will be despiked!
		if (m_temperatureMovingAverage.find(sensorName) == m_temperatureMovingAverage.end())
		{
			m_temperatureMovingAverage[sensorName] = temperature;
		}
		//despike
		if (fabs(m_temperatureMovingAverage[sensorName] - temperature) < TEMPERATURE_DESPIKE)
		{
			//smooth
			smoothedTemperature = ((TEMPERATURE_SMOOTHING_WINDOW - 1) * m_temperatureMovingAverage[sensorName] + temperature) / TEMPERATURE_SMOOTHING_WINDOW;
			m_temperatureMovingAverage[sensorName] = smoothedTemperature;
			useReading = true;
		}
	}
	return useReading;
}



unsigned short SensorReader::AddReading(std::string reading, tm time)
{
	unsigned short node = StringToNode(reading);
	switch (node)
	{
		case RAIN_NODE:	
		{
			PayloadRain rain;
			if (EmonSerial::ParseRainPayload((char*)reading.c_str(), &rain))
			{
				if (rain.rainCount != 0)
				{
					double smoothedTemperature;
					if(FilterTemperature("Outside", rain.temperature, smoothedTemperature) )
						m_temperatures.Add("Outside", time, smoothedTemperature / 100.0);

					m_rainFall.Add("Rain", time, rain.rainCount);
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
				//if( time.tm_yday <180)
				//{
					for (int i = 0; i< PULSE_NUM_PINS; i++)
					{
							m_power.Add(sensor[i], time, pulse.power[i]);
					}
					if(pulse.power[1] > pulse.power[2])
					m_power.Add("Exported", time, pulse.power[1] - pulse.power[2] );
				//}
				//else
				//{
				//	m_power.ResetReadingDataType(eReading, eCounterPeriod, eCounterPeriod);
					//for (int i = 0; i < PULSE_NUM_PINS; i++)
					//{
					//	m_power.Add(sensor[i], time, pulse.pulse[i]);
					//}
				//}
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
				if (disp.subnode < 4)
				{
					double smoothedTemperature;
					if (FilterTemperature(sensor[disp.subnode], disp.temperature, smoothedTemperature))
						m_temperatures.Add(sensor[disp.subnode], time, smoothedTemperature / 100.0);
				}
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

				if (temp.subnode < 4)
				{
					for (int i = 0; i < temp.numSensors; i++)
					{
						double smoothedTemperature;
						if (FilterTemperature(sensor[temp.subnode][i], temp.temperature[i], smoothedTemperature))
						{
							m_temperatures.Add(sensor[temp.subnode][i], time, smoothedTemperature / 100.0);
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
			std::string hwsTemp[HWS_TEMPERATURES] = {"Top of Panel (T1)", "Water (T3)", "Inlet (T6)", "Water 2 (T2)", "Water 3 (T5)", "(T4)", "PCB" };
			std::string hwsPump[HWS_PUMPS] = {"Solar Pump", "Heat Exchange Pump", "Heat Pump"};

			PayloadHWS hws;
			if (EmonSerial::ParseHWSPayload((char*)reading.c_str(), &hws))
			{
				for (int i = 0; i < HWS_TEMPERATURES; i++)
				{
					if(hws.temperature[i] > 0 && hws.temperature[i] < 110)
					m_HWS.Add(hwsTemp[i], time, hws.temperature[i]);
				}
				for (int i = 0; i < HWS_PUMPS; i++)
				{
					m_HWS.Add(hwsPump[i], time, (double)hws.pump[i]*(i+5));
				}
			}
			break;
		}
		case EMON_LOGGER: 
			//nothing to log
			break;
		case WATERLEVEL_NODE:
		{
			std::string sensor[2][2] = {
				{"Rain water tank", "Hot water"},
				{"unused", "Mains water"}
			};
			unsigned long scaleFactor[2] = { 1000, 1 };	//The hot water is 1000 pulse/litre while mains meter is 1ppl
		PayloadWater water;
			if (EmonSerial::ParseWaterPayload((char*)reading.c_str(), &water))
			{
				if (water.subnode < 2)
				{
					if (water.waterHeight < 2200 && water.waterHeight > 0) //waterHeight == 0 is no sensor connected.
						m_water.Add(sensor[water.subnode][0], time, water.waterHeight);
					if (water.flowCount != 0 && (time.tm_year > 119 || (time.tm_year >= 119 && time.tm_yday > 205))) //didn't log correctly until 24Jul2019
						m_waterUsage.Add(sensor[water.subnode][1], time, water.flowCount / scaleFactor[water.subnode]);
				}
			}
			break;
		}
		case SCALE_NODE:
		{
			PayloadScale scale;
			std::string sensor[2] = { "Dog food", "unused" };

			if (EmonSerial::ParseScalePayload((char*)reading.c_str(), &scale))
			{
				if (scale.subnode < 2)
				{
					m_scale.Add(sensor[scale.subnode], time, scale.grams);
					if (scale.supplyV / 1000.0 < 5)
						m_supplyV.Add("s" + std::to_string(scale.subnode), time, scale.supplyV / 1000.0);
				}
			}
			break;
		}
		default: 
			break;
	}
	return node;
}

void SensorReader::SaveAll()
{
	m_temperatures.Close(false);
	m_power.Close(false);
	m_rainFall.Close(false);
	m_supplyV.Close(false);
	m_HWS.Close(false);
	m_water.Close(false);
	m_waterUsage.Close(false);
	m_scale.Close(false);
}

void SensorReader::Close()
{
	m_temperatures.Close();
	m_power.Close();
	m_rainFall.Close();
	m_supplyV.Close();
	m_HWS.Close();
	m_water.Close();
	m_waterUsage.Close();
	m_scale.Close();
}
