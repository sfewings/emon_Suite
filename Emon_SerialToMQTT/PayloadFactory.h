#pragma once

#include "..\\EmonShared\EmonShared.h"
#include "EmonMQTTClient.h"

class PayloadFactory
{
public:
	PayloadFactory();
	~PayloadFactory();

	bool PublishPayload(char* string);

	PayloadRelay* pBasePayload;		//everything is derived from PayloadRelay
private:
	EmonMQTTClient m_MQTTClient;

};

