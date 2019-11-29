// TestPayloadWater.cpp : This file contains the 'main' function. Program execution begins and ends there.
//

#include <iostream>
//#define MQTT_LIB
#include "..\EmonShared\EmonShared.h"



void TestPayload(PayloadWater& pwSource)
{
	byte buf[100];

	int size = EmonSerial::PackWaterPayload(&pwSource, buf);
	std::cout << std::dec;
	std::cout << "pack from " << sizeof(PayloadWater) << " to " << size << "bytes" << std::endl;

	PayloadWater pwDest;

	EmonSerial::UnpackWaterPayload(buf, &pwDest);

	std::cout << "relay," << (short)pwSource.relay << "," << (short)pwDest.relay << std::endl;
	std::cout << "subnode," << (short)pwSource.subnode << "," << (short)pwDest.subnode << std::endl;
	std::cout << "supplyV," << pwSource.supplyV << "," << pwDest.supplyV << std::endl;
	std::cout << "numSensors," << (short)pwSource.numSensors << "," << (short)pwDest.numSensors << std::endl;

	std::cout << "flowCount[],";
	for (int i = 0; i < (pwSource.numSensors & 0xF); i++)
		std::cout << pwSource.flowCount[i] << " ";
	std::cout << ",";
	for (int i = 0; i < (pwDest.numSensors & 0xF); i++)
		std::cout << pwDest.flowCount[i] << " ";
	std::cout << std::endl;

	std::cout << "waterHeight[],";
	for (int i = 0; i < (pwSource.numSensors & 0xF0) >> 4; i++)
		std::cout << pwSource.waterHeight[i] << " ";
	std::cout << ",";
	for (int i = 0; i < (pwDest.numSensors & 0xF0) >> 4; i++)
		std::cout << pwDest.waterHeight[i] << " ";
	std::cout << std::endl;

	byte* p;
	p = (byte*)& pwSource;
	for (int i = 0; i < sizeof(PayloadWater); i++)
		std::cout << std::hex << (short)p[i] << ",";
	std::cout << std::endl;
	p = (byte*)& buf;
	for (int i = 0; i < size; i++)
		std::cout << std::hex << (short)p[i] << ",";
	std::cout << std::endl;
	p = (byte*)& pwDest;
	for (int i = 0; i < sizeof(PayloadWater); i++)
		std::cout << std::hex << (short)p[i] << ",";
	std::cout << std::endl;
}

void ResetPayload(PayloadWater& pw)
{
	for (int i = 0; i < 4; i++)
	{
		pw.flowCount[i] = 0xcccccccc;
		pw.waterHeight[i] = 0xcccccccc;
	}
}

int main()
{
	PayloadWater pwSource;

	pwSource.relay = 0;
	pwSource.subnode = 0;
	pwSource.supplyV = 3300;
	pwSource.numSensors = 0x11;
	pwSource.waterHeight[0] = 0x1234567;
	pwSource.flowCount[0] = 0x89abcdef;

	TestPayload(pwSource);

	ResetPayload(pwSource);
	pwSource.numSensors = 0x4;
	for (int i = 0; i < 4; i++)
		pwSource.flowCount[i] = i;
	TestPayload(pwSource);

	ResetPayload(pwSource);
	pwSource.numSensors = 0x40;
	for(int i=0;i<4;i++)
		pwSource.waterHeight[i] = i;
	TestPayload(pwSource);

	ResetPayload(pwSource);
	pwSource.numSensors = 0x22;
	for (int i = 0; i < 2; i++)
	{
		pwSource.flowCount[i] = i * 10;
		pwSource.waterHeight[i] = i;
	}
	TestPayload(pwSource);

	ResetPayload(pwSource);
	pwSource.numSensors = 0x44;
	for (int i = 0; i < 4; i++)
	{
		pwSource.flowCount[i] = i * 10;
		pwSource.waterHeight[i] = i;
	}
	TestPayload(pwSource);
}
// Run program: Ctrl + F5 or Debug > Start Without Debugging menu
// Debug program: F5 or Debug > Start Debugging menu

// Tips for Getting Started: 
//   1. Use the Solution Explorer window to add/manage files
//   2. Use the Team Explorer window to connect to source control
//   3. Use the Output window to see build output and other messages
//   4. Use the Error List window to view errors
//   5. Go to Project > Add New Item to create new code files, or Project > Add Existing Item to add existing code files to the project
//   6. In the future, to open this project again, go to File > Open > Project and select the .sln file
