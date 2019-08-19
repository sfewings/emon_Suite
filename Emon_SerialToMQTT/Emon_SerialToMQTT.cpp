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

#include <fstream>
#include <iostream>
#include <algorithm>

#include "rs232.h"
#include "../EmonShared/EmonShared.h"
#include "PayloadFactory.h"


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
		std::cout << "Emon_SerialToMQTT	[-c COM port #]" << std::endl;
		return 0;
	}

	int comPort = -1;
	std::string str = input.getCmdOption("-c");
	if (!str.empty())
	{
		comPort = atoi(str.c_str()) -1;	//COM1 == comPort0
	}

	if (comPort >= 0)
	{
		int i, n,
			bdrate = 9600;       /* 9600 baud */

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

				for (i = 0; i < n; i++)
				{
					if (buf[i] < 32)  /* replace unreadable control-codes by dots */
					{
						buf[i] = '.';
					}
				}

				printf("received %i bytes: %s", n, (char*)buf);
				if(! pf.PublishPayload((char*) buf) )
					std::cout << "...not parsed" << std::endl;

			}

	#ifdef _WIN32
			Sleep(100);
	#else
			usleep(100000);  /* sleep for 100 milliSeconds */
	#endif
		}
	}

	return(0);
}

