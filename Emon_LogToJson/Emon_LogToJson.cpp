// Emon_LogToJson.cpp : This file contains the 'main' function. Program execution begins and ends there.
//


#include <stdlib.h>
#include <stdio.h>

#ifdef _WIN32
	#include <Windows.h>
	#include <conio.h>	//for _kbhit()
#else
	#include <unistd.h>
#endif

#include <iostream>
#include <cstdlib>
#include <string>
#include <cstring>
#include <cctype>
#include <thread>
#include <chrono>
#include <fstream>
#include <experimental/filesystem>
#include <algorithm>
#include <iomanip>

#include "mqtt/client.h"
#include "rs232.h"

#include "../EmonShared/EmonShared.h"
#include "SensorReader.h"


//MQTT support
const std::string SERVER_ADDRESS("tcp://192.168.1.111:1883");
const std::string CLIENT_ID("Emon_LogToJson");

const int QOS = 0;


namespace fs = std::experimental::filesystem;

template<typename ... Args>
std::string string_format(const std::string& format, Args ... args)
{
	size_t size = snprintf(nullptr, 0, format.c_str(), args ...) + (size_t)1; // Extra space for '\0'
	std::unique_ptr<char[]> buf(new char[size]);
	snprintf(buf.get(), size, format.c_str(), args ...);
	return std::string(buf.get(), buf.get() + size - 1); // We don't want the '\0' inside
}


class InputParser {
public:
	InputParser(int& argc, char** argv) {
		for (int i = 1; i < argc; ++i)
			this->tokens.push_back(std::string(argv[i]));
	}
	/// @author iain
	const std::string& getCmdOption(const std::string& option) const {
		std::vector<std::string>::const_iterator itr;
		itr = std::find(this->tokens.begin(), this->tokens.end(), option);
		if (itr != this->tokens.end() && ++itr != this->tokens.end()) {
			return *itr;
		}
		static const std::string empty_string("");
		return empty_string;
	}
	/// @author iain
	bool cmdOptionExists(const std::string& option) const {
		return std::find(this->tokens.begin(), this->tokens.end(), option)
			!= this->tokens.end();
	}
private:
	std::vector <std::string> tokens;
};




// --------------------------------------------------------------------------
// Simple function to manually reconect a client.

bool try_reconnect(mqtt::client& cli)
{
	constexpr int N_ATTEMPT = 30;

	for (int i = 0; i < N_ATTEMPT && !cli.is_connected(); ++i) {
		try {
			cli.reconnect();
			return true;
		}
		catch (const mqtt::exception&) {
			std::this_thread::sleep_for(std::chrono::seconds(1));
		}
	}
	return false;
}
// --------------------------------------------------------------------------

std::vector<std::string> getPaths(std::string rootPath)
{
	 std::vector<std::string> paths;
	std::string ext(".TXT");
	for (auto& p : fs::recursive_directory_iterator(rootPath) )
	{
		if (p.path().extension() == ext)
			paths.push_back( p.path().string() );
		std::cout << p << std::endl;
	}
	
	std::sort(paths.begin(), paths.end());
	
	return paths;
}


int main(int argc, char** argv)
{
	InputParser input(argc, argv);
	if (input.cmdOptionExists("-h"))
	{
		std::cout << "Emon_LogToJson	[-i inputFolder] [-o OutputFolder] [-c COM port #] [-m MQTT server IP]" << std::endl;
		return 0;
	}
	std::string inputFolder = input.getCmdOption("-i");
	if (inputFolder.empty())
	{
#ifdef __linux__
		inputFolder = "/share/Input";
#else
		inputFolder = "C:/EmonData/Input";
#endif
	}

	std::string outputFolder = input.getCmdOption("-o");
	if (outputFolder.empty())
	{
#ifdef __linux__
		outputFolder = "/share/Output";
#else
		outputFolder = "C:/EmonData/Output";
#endif
	}
	int comPort = -1;
	std::string str = input.getCmdOption("-c");
	if (!str.empty())
	{
		comPort = atoi(str.c_str()) -1;	//COM1 == comPort0
	}



	std::vector<std::string> paths = getPaths(inputFolder);

	SensorReader sensorReader(outputFolder);

	for (auto it = begin(paths); it != end(paths); ++it)
	{
		if (it->length() != 0)
			sensorReader.AddFile(*it);
	}

	sensorReader.SaveAll();


	std::string MQTTIPAAddress = input.getCmdOption("-m");
	if (!MQTTIPAAddress.empty())
	{

		mqtt::connect_options connOpts;
		connOpts.set_keep_alive_interval(20);
		connOpts.set_clean_session(true);

		mqtt::client cli(MQTTIPAAddress, CLIENT_ID);

		const std::vector<std::string> TOPICS{ "EmonLog", "command" };
		const std::vector<int> QOS{ 0, 1 };

		try {
			std::cout << "Connecting to the MQTT server..." << std::flush;
			cli.connect(connOpts);
			cli.subscribe(TOPICS, QOS);
			std::cout << "OK\n" << std::endl;

			std::time_t lastSave = std::time(0);
			// Consume messages

#ifdef _WIN32
			while (!_kbhit())
#else
			while (1)
#endif			
			{
				auto msg = cli.consume_message();

				if (!msg) {
					if (!cli.is_connected()) {
						std::cout << "Lost connection. Attempting reconnect" << std::endl;
						if (try_reconnect(cli)) {
							cli.subscribe(TOPICS, QOS);
							std::cout << "Reconnected" << std::endl;
							continue;
						}
						else {
							std::cout << "Reconnect failed." << std::endl;
							break;
						}
					}
					else
						break;
				}
				if (msg->get_topic() == "command" &&
					msg->to_string() == "exit") {
					std::cout << "Exit command received" << std::endl;
					break;
				}

				std::time_t t = std::time(0);   // get time now
				std::tm now = *std::localtime(&t);

				std::cout << msg->to_string();
				if( sensorReader.AddReading(msg->get_payload_str(), now) )
					std::cout << "...added";
				std::cout <<std::endl;

				if (t - lastSave > 60 * 5)
				{
					sensorReader.SaveAll();
					lastSave = t;
				}
			}

			// Disconnect

			std::cout << "\nDisconnecting from the MQTT server..." << std::flush;
			cli.disconnect();
			std::cout << "OK" << std::endl;
		}
		catch (const mqtt::exception& exc) {
			std::cerr << exc.what() << std::endl;
		}
	}
	else if (comPort >= 0)
	{

		int n, bdrate = 9600;       /* 9600 baud */

		unsigned char buf[4096];
		std::time_t lastSave = std::time(0);

		char mode[] = { '8','N','1',0 };


		if (RS232_OpenComport(comPort, bdrate, mode, 0))
		{
			printf("Can not open comport\n");
		}
		else
		{
#ifdef _WIN32
			while (!_kbhit())
#else
			while(1)
#endif
			{
				n = RS232_PollComportLine(comPort, buf, 4095);

				if (n > 0)
				{
					buf[n] = 0;   /* always put a "null" at the end of a string! */

					//replace trailing chars with \0. Remove \r\n
					while (n && buf[n] < 32)
						buf[n--] = 0;

					std::string str = (char*)buf;

					std::time_t t = std::time(0);   // get time now
					std::tm now = *std::localtime(&t);

					if (sensorReader.AddReading(str, now))
					{
						//log the reading to a log file
						std::string fullPath = string_format("%s/%04d%02d%02d.TXT", inputFolder.c_str(), now.tm_year + 1900, now.tm_mon + 1, now.tm_mday);
						std::ofstream f(fullPath, std::ios::app);
						if (!f.bad())
						{
							std::string line = string_format("%02d/%02d/%02d %02d:%02d:%02d,%s", now.tm_mday, now.tm_mon + 1, now.tm_year + 1900, now.tm_hour, now.tm_min, now.tm_sec, str.c_str() );
							f << line << std::endl;
						}
						std::cout << str << " logged" << std::endl;
					}
					else
					{
						std::cout << str << std::endl;
					}

					if (t - lastSave > 60 * 5)
					{
						sensorReader.SaveAll();
						lastSave = t;
					}

				}
#ifdef _WIN32
				Sleep(100);
#else
				usleep(100000);  /* sleep for 100 milliSeconds */
#endif

			}
		}
	}

	sensorReader.Close();

	return(0);
}

