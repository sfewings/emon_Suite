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

#define TEMPERATURE_DESPIKE 2000.0				//Despike any temperature ereading greater than 20 celcius from the moving average
																					// Note: If all reading are greater than the despike value then the moving average will never change!
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



SensorReader::SensorReader(std::string rootPath, bool removeAll):
	m_temperatures("temp", rootPath, eReading, eReading, eReading),
	m_power("power", rootPath, eReading, eRatePerSecond, eRatePerSecond),
	m_rainFall("rain", rootPath, eCounterTotal, eCounterTotal, eCounterTotal),
	m_supplyV("supplyV", rootPath, eReading, eReading, eReading),
	m_HWS("hws", rootPath, eReading, eReading, eReading),
	m_water("water", rootPath, eReading, eReading, eReading),
	m_waterUsage("waterUsage", rootPath, eCounterTotal, eCounterPeriod, eCounterPeriod),
	m_scale("scale", rootPath, eReading, eReading, eReading),
	m_batteryCurrent("batteryCurrent", rootPath, eReading, eRatePerSecond, eRatePerSecond),
	m_batteryVoltage("batteryVoltage", rootPath, eReading, eReading, eReading),
	m_inverter("inverter", rootPath, eReading, eRatePerSecond, eRatePerSecond),
	m_beehive("beehive", rootPath, eReading, eRatePerSecond, eRatePerSecond)
{
	m_rootPath = rootPath;
	if (removeAll && fs::is_directory(rootPath) && rootPath.length()> 5 )
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
	fs::create_directory(rootPath + "/batteryCurrent");
	fs::create_directory(rootPath + "/batteryVoltage");
	fs::create_directory(rootPath + "/inverter");
	fs::create_directory(rootPath + "/beehive");

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
	if (line.compare(0, 3, "log") == 0) return EMON_LOGGER;
	if (line.compare(0, 3, "bat") == 0) return BATTERY_NODE;
	if (line.compare(0, 3, "inv") == 0) return INVERTER_NODE;
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
				if( pulse.subnode == 0)
				{
					std::string sensor[PULSE_MAX_SENSORS] = { "HWS", "Produced", "Consumed", "Imported", "Car", "unused" };
					for (int i = 0; i< PULSE_MAX_SENSORS; i++)
					{
							m_power.Add(sensor[i], time, pulse.power[i]);
					}
					m_power.Add("Exported", time, ((pulse.power[1] > pulse.power[2]) ? (pulse.power[1] - pulse.power[2]): 0.0));
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
					{"Garage", "Beer fridge", "BeerFridge 2", "unused1"},
					{"unused2", "unused3", "unused4", "unused5"},
					{"unused6", "unused7", "unused8", "unused9"}
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
				{"Hot water", "unused"},
				{"Mains water", "Bore"}
			};
			unsigned long scaleFactor[2] = { 1000, 1 };	//The hot water is 1000 pulse/litre while mains meter is 1ppl
			PayloadWater water;
			int version = EmonSerial::ParseWaterPayload((char*)reading.c_str(), &water);
			if (version)
			{
				if (water.subnode < 2)
				{
					for(int i=0; i<((water.numSensors&0xF0)>>4);i++)
					{
						if (water.waterHeight[i] < 2200 && water.waterHeight[i] > 0) //waterHeight == 0 is no sensor connected.
							m_water.Add("Rain water tank", time, water.waterHeight[i]);
					}
					for(int i=0; i<(water.numSensors & 0xF);i++)
					{
						if (water.flowCount != 0 && (time.tm_year > 119 || (time.tm_year >= 119 && time.tm_yday > 205))  //didn't log correctly until 24Jul2019
							|| (water.subnode == 1 && i == 1 && time.tm_year == 119 && time.tm_yday > 283)) //bore didn't read correctly until 10Oct2019
						{
							if( version < 3)
								m_waterUsage.Add(sensor[water.subnode][i], time, water.flowCount[i] / scaleFactor[water.subnode]);
							else
								m_waterUsage.Add(sensor[water.subnode][i], time, water.flowCount[i] / 10);	//version 3 standardised all water flows to decilitres
						}
					}
					if (water.supplyV / 1000.0 < 5)
						m_supplyV.Add("w" + std::to_string(water.subnode), time, water.supplyV / 1000.0);
				}
			}
			break;
		}
		case SCALE_NODE:
		{
			PayloadScale scale;
			std::string sensor[5] = { "Dog food", "Compost", "Rubish", "Recycle", "Greenwaste" };

			if (EmonSerial::ParseScalePayload((char*)reading.c_str(), &scale))
			{
				if (scale.subnode < 5)
				{
					m_scale.Add(sensor[scale.subnode], time, scale.grams);
					if (scale.supplyV / 1000.0 < 5)
						m_supplyV.Add("s" + std::to_string(scale.subnode), time, scale.supplyV / 1000.0);
				}
			}
			break;
		}
		case BATTERY_NODE:
		{
			PayloadBattery bat;

			if (int version = EmonSerial::ParseBatteryPayload((char*)reading.c_str(), &bat))
			{
				if (bat.subnode == 0) //main battery monitoring unit
				{
					if (version == 1)
					{
						std::string currents[BATTERY_SHUNTS] = { "BBB", "Giant", "Li-ion" };
						double totalIn = 0.0;
						double totalOut = 0.0;
						for (int i = 0; i < BATTERY_SHUNTS; i++)
						{
							if (bat.power[i] < 0)
							{
								m_batteryCurrent.Add(currents[i] + " Out", time, bat.power[i]);
								m_batteryCurrent.Add(currents[i] + " In", time, 0);
								totalOut += bat.power[i];
							}
							else
							{
								m_batteryCurrent.Add(currents[i] + " Out", time, 0);
								m_batteryCurrent.Add(currents[i] + " In", time, bat.power[i]);
								totalIn += bat.power[i];
							}
						}
						m_batteryCurrent.Add("Total In", time, totalIn);
						m_batteryCurrent.Add("Total Out", time, totalOut);

						m_batteryVoltage.Add("Rail", time, bat.voltage[0] / 100.0);
						double midVoltage = bat.voltage[0] / 100.0 / 2.0;

						if (time.tm_year > 120 || (time.tm_year == 120 && time.tm_yday >= 122))  //changed the voltage takeoff points on 2May20
						{
							std::string sensor[8] = { "Rail", "Giant", "BBB-A", "BBB-B", "BBB-C", "BBB-4", "BBB-B2", "CPU" };
							m_batteryVoltage.Add(sensor[1], time, midVoltage - bat.voltage[1] / 100.0);
							m_batteryVoltage.Add(sensor[2], time, midVoltage / 2 - bat.voltage[2] / 100.0);
							m_batteryVoltage.Add(sensor[3], time, midVoltage - bat.voltage[3] / 100.0);
							m_batteryVoltage.Add(sensor[4], time, midVoltage / 2 * 3 - bat.voltage[4] / 100.0);
							m_batteryVoltage.Add(sensor[5], time, midVoltage - bat.voltage[5] / 100.0);
							//m_batteryVoltage.Add(sensor[6], time, midVoltage - bat.voltage[6] / 100.0);
							//m_batteryVoltage.Add(sensor[7], time, midVoltage - bat.voltage[7] / 100.0);
						}
						else
						{
							std::string sensor[8] = { "Rail", "Giant", "BBB-1", "BBB-2", "BBB-3", "BBB-4", "BBB-5", "CPU" };
							for (int i = 1; i < 8 - 1; i++)
							{
								m_batteryVoltage.Add(sensor[i], time, midVoltage - bat.voltage[i] / 100.0); //battery values are in 100th of a volt
							}
						}
						if (bat.voltage[8 - 1] / 1000.0 < 5)
							m_supplyV.Add("b" + std::to_string(bat.subnode), time, bat.voltage[8 - 1] / 1000.0);	//Arduino power supply is in mv
					}
					else  //version == 2
					{
						std::string currents[BATTERY_SHUNTS] = { "Bank 2", "Bank 1", "Unused" };
						double totalIn = 0.0;
						double totalOut = 0.0;
						for (int i = 0; i < BATTERY_SHUNTS; i++)
						{
							if (bat.power[i] < 0)
							{
								m_batteryCurrent.Add(currents[i] + " Out", time, bat.power[i]);
								m_batteryCurrent.Add(currents[i] + " In", time, 0);
								totalOut += bat.power[i];
							}
							else
							{
								m_batteryCurrent.Add(currents[i] + " Out", time, 0);
								m_batteryCurrent.Add(currents[i] + " In", time, bat.power[i]);
								totalIn += bat.power[i];
							}
						}
						m_batteryCurrent.Add("Total In", time, totalIn);
						m_batteryCurrent.Add("Total Out", time, totalOut);

						m_batteryVoltage.Add("Rail", time, bat.voltage[0] / 100.0);
						double midVoltage = bat.voltage[0] / 100.0 / 2.0;

						std::string sensor[MAX_VOLTAGES] = { "Rail","B1-4","B1-3","B1-2","B1-1","B2-4","B2-3","B2-2","B2-1"};
						for (int i = 1; i < MAX_VOLTAGES; i++)
						{
							m_batteryVoltage.Add(sensor[i], time, midVoltage - bat.voltage[i] / 100.0); //battery values are in 100th of a volt
						}
					}
				}
				else if( bat.subnode == 1 ) //wooden current measuring device with one current and one voltage
				{
					if (bat.power[0] < 0)
					{
						m_batteryCurrent.Add("Tester Out", time, bat.power[0]);
						m_batteryCurrent.Add("Tester In", time, 0);
					}
					else
					{
						m_batteryCurrent.Add("Tester Out", time, 0);
						m_batteryCurrent.Add("Tester In", time, bat.power[0]);
					}
					m_batteryVoltage.Add("Tester", time, bat.voltage[0] / 100.0);
					if (bat.voltage[MAX_VOLTAGES - 1] / 1000.0 < 5)
						m_supplyV.Add("b" + std::to_string(bat.subnode), time, bat.voltage[MAX_VOLTAGES - 1] / 1000.0);	//Arduino power supply is in mv
				}
			}
			break;
		}
		case INVERTER_NODE:
		{
			PayloadInverter inv;
			if (EmonSerial::ParseInverterPayload((char*)reading.c_str(), &inv))
			{
				m_inverter.Add("Inv" + std::to_string(inv.subnode + 1) + " Out", time, inv.activePower);
				m_inverter.Add("Inv" + std::to_string(inv.subnode + 1) + " In", time, inv.pvInputPower);
				m_inverter.Add("Inv" + std::to_string(inv.subnode + 1) + "Batt", time, inv.batteryVoltage/10.0);

				m_inverter.Add("Inv" + std::to_string(inv.subnode + 1) + "Bat capacity", time, inv.batteryCapacity);
				m_inverter.Add("Inv" + std::to_string(inv.subnode + 1) + "Bat charging", time, inv.batteryCharging);
				m_inverter.Add("Inv" + std::to_string(inv.subnode + 1) + "Bat dicharge", time, -inv.batteryDischarge);
				m_inverterCurrentIn[std::to_string(inv.subnode + 1)] = inv.batteryCharging;
				m_inverterCurrentOut[std::to_string(inv.subnode + 1)] = -inv.batteryDischarge;

				double totalIn = 0.0;
				double totalOut = 0.0;
				for (auto it = m_inverterCurrentIn.begin(); it != m_inverterCurrentIn.end(); ++it)
				{
					totalIn += it->second;
				}
				for (auto it = m_inverterCurrentOut.begin(); it != m_inverterCurrentOut.end(); ++it)
				{
					totalOut += it->second;
				}
				m_inverter.Add("Total charging", time, totalIn);
				m_inverter.Add("Total discharging", time, totalOut);
			}
			break;
		}
		case BEEHIVEMONITOR_NODE:
		{
			PayloadBeehive beehive;
			if (EmonSerial::ParseBeehivePayload((char*)reading.c_str(), &beehive))
			{
				m_beehive.Add("Bee" + std::to_string(beehive.subnode + 1) + " Out", time, beehive.beeOutRate);
				m_beehive.Add("Bee" + std::to_string(beehive.subnode + 1) + " In", time, beehive.beeInRate);

				double smoothedTemperature;

				if (FilterTemperature("Beehive"+std::to_string(beehive.subnode + 1)+" Inside", beehive.temperatureIn, smoothedTemperature))
					m_temperatures.Add("Beehive" + std::to_string(beehive.subnode + 1) + " Inside", time, smoothedTemperature / 100.0);

				if (FilterTemperature("Beehive" + std::to_string(beehive.subnode + 1) + " Outside", beehive.temperatureOut, smoothedTemperature))
					m_temperatures.Add("Beehive" + std::to_string(beehive.subnode + 1) + "Outside", time, smoothedTemperature / 100.0);

				if (beehive.supplyV / 1000.0 < 5)
					m_supplyV.Add("Beehive" + std::to_string(beehive.subnode + 1), time, beehive.supplyV / 1000.0);
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
	m_batteryCurrent.Close(false);
	m_batteryVoltage.Close(false);
	m_inverter.Close(false);
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
	m_batteryCurrent.Close();
	m_batteryVoltage.Close();
	m_inverter.Close();
}
