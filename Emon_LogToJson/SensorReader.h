#pragma once
#include <string>
#include "SensorDataArray.h"

class SensorReader
{
public:
	SensorReader(std::string rootPath);

	void AddFile(std::string path);
	void AddReading(std::string reading, tm time);
	void Close();

protected:
	size_t GetTime(std::string line, tm &time);
	unsigned short StringToNode(std::string line);

	SensorData m_temperatures;
	SensorData m_power;
	SensorData m_powerTotal;
	SensorData m_rainFall;
	SensorData m_supplyV;
	SensorData m_HWS;
	SensorData m_water;
	SensorData m_waterUsage;

	std::string m_rootPath;
};
