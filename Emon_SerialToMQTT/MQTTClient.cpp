
#include <iostream>
#include <cstdlib>
#include <string>
#include <map>
#include <vector>
#include <cstring>
#include "mqtt\client.h"
#include "..\Emon_SerialToMQTT\EmonMQTTClient.h"
//#include "..\..\Libraries\paho.mqtt.c-win64\include\MQTTClient.h"


const std::string SERVER_ADDRESS{ "tcp://192.168.1.111:1883" };
const std::string CLIENT_ID{ "emon_publish_cpp" };
const std::string TOPIC{ "hello" };

const int QOS = 1;


EmonMQTTClient::EmonMQTTClient():
	m_client(SERVER_ADDRESS, CLIENT_ID, NULL)
{
}

EmonMQTTClient::~EmonMQTTClient()
{
	try {
		std::cout << "\nMQTT Disconnecting..." << std::endl;
		m_client.disconnect();
		std::cout << "...OK" << std::endl;
	}
	catch (const mqtt::exception& exc) {
		std::cerr << exc.what() << std::endl;
	}

	std::cout << "\nMQTT Exiting" << std::endl;
}

bool EmonMQTTClient::Initialise()
{
	std::cout << "MQTT Initialzing..." << std::endl;

	m_client.set_callback( m_callBack);

	mqtt::connect_options connOpts;
	connOpts.set_keep_alive_interval(20);
	connOpts.set_clean_session(true);
	std::cout << "...OK" << std::endl;

	try 
	{
		std::cout << "\nMQTT Connecting..." << std::endl;
		m_client.connect(connOpts);
		std::cout << "...OK" << std::endl;
	}
	catch (const mqtt::exception& exc) {
		std::cerr << exc.what() << std::endl;
		return false;
	}
	return true;
}

int EmonMQTTClient::Publish(char* topic, char* msg)
{
	try {

		//std::cout << "\nSending message..." << std::endl;
		//auto pubmsg = mqtt::make_message(TOPIC, PAYLOAD1);
		//pubmsg->set_qos(QOS);
		//m_client.publish(pubmsg);
		//std::cout << "...OK" << std::endl;

		// Now try with itemized publish.

		//std::cout << "\nSending next message..." << std::endl;
		m_client.publish(topic, msg, strlen(msg) + 1);
		//std::cout << "...OK" << std::endl;

		// Now try with a listener, no token, and non-heap message

		//std::cout << "\nSending final message..." << std::endl;
		//m_client.publish(mqtt::message(TOPIC, PAYLOAD3, QOS, false));
		//std::cout << "OK" << std::endl;
	}
	catch (const mqtt::exception& exc) 
	{
		std::cerr << exc.what() << std::endl;
		return 0;
	}

	return 1;
}
