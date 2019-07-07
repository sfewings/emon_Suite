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

#include "..\\EmonShared\EmonShared.h"
#include "SensorReader.h"

#include <fstream>
#include <iostream>
#include <experimental/filesystem>
namespace fs = std::experimental::filesystem;

int g_count = 0;
std::array<std::string, 300> g_paths;
void getPaths(std::string rootPath)
{
	std::string ext(".TXT");
	for (auto& p : fs::recursive_directory_iterator(rootPath) )
	{
		if (p.path().extension() == ext)
			g_paths[g_count++] = p.path().string();
		std::cout << p << '\n';
	}
	
	std::sort(g_paths.begin(), g_paths.end());
	
	return;
}


int main()
{
	SensorReader sensorReader("C:\\EmonData\\Output");
	getPaths("C:\\EmonData\\Input");

	for (int i = 0; i < 300; i++)
	{
		if(g_paths[i].length() != 0)
			sensorReader.AddFile(g_paths[i]);
	}
//		sensorReader.AddFile("C:\\EmonData\\Input\\20190704.TXT");

	sensorReader.Close();

	return(0);
}

