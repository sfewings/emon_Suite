// Emon_SerialToMQTT.cpp : This file contains the 'main' function. Program execution begins and ends there.
//

#include <iostream>
/**************************************************

file: demo_rx.c
purpose: simple demo that receives characters from
the serial port and print them on the screen,
exit the program by pressing Ctrl-C

compile with the command: gcc demo_rx.c rs232.c -Wall -Wextra -o2 -o test_rx

**************************************************/

#include <stdlib.h>
#include <stdio.h>

#ifdef _WIN32
#include <Windows.h>
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


#include "rs232.h"
#include "../EmonShared/EmonShared.h"
#include "PayloadFactory.h"

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



int main(int argc, char** argv)
{
	InputParser input(argc, argv);
	if (input.cmdOptionExists("-h"))
	{
		std::cout << "Emon_SerialToMQTT [-l logging folder]	[-c COM port #]" << std::endl;
		return 0;
	}

	std::string loggingFolder = input.getCmdOption("-l");

	int comPort = -1;
	std::string comPortStr = input.getCmdOption("-c");
	if (!comPortStr.empty())
	{
		comPort = atoi(comPortStr.c_str()) -1;	//COM1 == comPort0
	}

	if (comPort >= 0)
	{
		int n, bdrate = 9600;       /* 9600 baud */

		PayloadFactory pf;


		unsigned char buf[4096];

		char mode[] = { '8','N','1',0 };


		if (RS232_OpenComport(comPort, bdrate, mode, 0))
		{
			printf("Can not open comport\n");

			return(0);
		}

		while (1)
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
				std::cout << str << std::endl;

				if (pf.PublishPayload((char*)buf) &&
					!loggingFolder.empty())
				{

					//log the reading to a log file
					std::string fullPath = string_format("%s/%04d%02d%02d.TXT", loggingFolder.c_str(), now.tm_year + 1900, now.tm_mon + 1, now.tm_mday);
					std::ofstream f(fullPath, std::ios::app);
					if (!f.bad())
					{
						std::string line = string_format("%02d/%02d/%02d %02d:%02d:%02d,%s", now.tm_mday, now.tm_mon + 1, now.tm_year + 1900, now.tm_hour, now.tm_min, now.tm_sec, str.c_str());
						f << line << std::endl;
					}
					std::cout << " logged" << std::endl;
				}
			}
			std::cout << std::endl;

	#ifdef _WIN32
			Sleep(100);
	#else
			usleep(100000);  /* sleep for 100 milliSeconds */
	#endif
		}
	}

	return(0);
}

