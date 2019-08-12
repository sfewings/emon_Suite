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

#ifndef MQTT_LIB
	#define MQTT_LIB
#endif

#include "../EmonShared/EmonShared.h"
#include "SensorReader.h"

#include <fstream>
#include <iostream>
#include <experimental/filesystem>
#include <algorithm>

namespace fs = std::experimental::filesystem;

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



int g_count = 0;
#define MAX_INPUT_FILES 365
std::array<std::string, MAX_INPUT_FILES> g_paths;
void getPaths(std::string rootPath)
{
	std::string ext(".TXT");
	for (auto& p : fs::recursive_directory_iterator(rootPath) )
	{
		if (p.path().extension() == ext)
			g_paths[g_count++] = p.path().string();
		std::cout << p << std::endl;
	}
	
	std::sort(g_paths.begin(), g_paths.end());
	
	return;
}


int main(int argc, char** argv) 
{
	InputParser input(argc, argv);
	if (input.cmdOptionExists("-h")) 
	{
		std::cout << "Emon_LogToJson	[-i inputFolder] [-o OutputFolder]" << std::endl;
		return 0;
	}
	std::string inputFolder = input.getCmdOption("-i");
	if (inputFolder.empty())
	{
		inputFolder = "C:/EmonData/Input";
	}

	std::string outputFolder = input.getCmdOption("-o");
	if (outputFolder.empty())
	{
		outputFolder = "C:/EmonData/Output";
	}

	getPaths(inputFolder);

	SensorReader sensorReader(outputFolder);

	for (int i = 0; i < MAX_INPUT_FILES; i++)
	{
		if(g_paths[i].length() != 0)
			sensorReader.AddFile(g_paths[i]);
	}

	sensorReader.Close();

	return(0);
}

