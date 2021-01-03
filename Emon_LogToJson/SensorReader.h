#pragma once
#include <string>
#include "SensorDataArray.h"

class SensorReader
{
public:
	SensorReader(std::string rootPath, bool removeAll);

	void AddFile(std::string path);
	unsigned short AddReading(std::string reading, tm time);
	void SaveAll();
	void Close();

protected:
	size_t GetTime(std::string line, tm &time);
	unsigned short StringToNode(std::string line);
	bool FilterTemperature(std::string sensorName, double temperature, double& smoothedTemperature);

	SensorData m_temperatures;
	SensorData m_power;
	SensorData m_rainFall;
	SensorData m_supplyV;
	SensorData m_HWS;
	SensorData m_water;
	SensorData m_waterUsage;
	SensorData m_scale;
	SensorData m_batteryCurrent;
	SensorData m_batteryVoltage;
	SensorData m_inverter;
	SensorData m_beehive;

	std::string m_rootPath;
	std::map<std::string, double> m_temperatureMovingAverage;
	std::map<std::string, double > m_inverterCurrentIn;
	std::map<std::string, double > m_inverterCurrentOut;
};

