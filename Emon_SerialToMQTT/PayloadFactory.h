#pragma once

#include "../EmonShared/EmonShared.h"
#include "EmonMQTTClient.h"

class PayloadFactory
{
public:
	PayloadFactory(std::string serverAddress, std::string clientID);
	~PayloadFactory();

	bool Initialise();

	bool PublishPayload(char* string);

	PayloadRelay* pBasePayload;		//everything is derived from PayloadRelay
private:
	EmonMQTTClient m_MQTTClient;

};

