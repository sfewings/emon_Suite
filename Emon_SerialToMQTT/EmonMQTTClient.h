#pragma once

#include "mqtt/client.h"


/////////////////////////////////////////////////////////////////////////////
// Class to receive callbacks

// --------------------------------------------------------------------------
class user_callback : public virtual mqtt::callback
{
	void connection_lost(const std::string& cause) override {
		std::cout << "\nConnection lost" << std::endl;
		if (!cause.empty())
			std::cout << "\tcause: " << cause << std::endl;
	}

	void delivery_complete(mqtt::delivery_token_ptr tok) override {
		std::cout << "\n\t[Delivery complete for token: "
			<< (tok ? tok->get_message_id() : -1) << "]" << std::endl;
	}

public:
};

class EmonMQTTClient
{
public:
	EmonMQTTClient(std::string serverAddress, std::string clientID);
	~EmonMQTTClient();

	bool Initialise();
	int Publish(char* topic, char* msg);

private:
	user_callback m_callBack;
	mqtt::client m_client;
};

