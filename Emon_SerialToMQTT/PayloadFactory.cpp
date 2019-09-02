#include "PayloadFactory.h"
#include "EmonMQTTClient.h"


PayloadFactory::PayloadFactory()
{
	pBasePayload = NULL;
}

bool PayloadFactory::Initialise()
{
	return m_MQTTClient.Initialise();
}


PayloadFactory::~PayloadFactory()
{
	if (pBasePayload != NULL)
		delete pBasePayload;
	pBasePayload = NULL;

}

bool PayloadFactory::PublishPayload(char* s)
{
	bool parsed = false;
	std::string copyOfPayload(s);

	//char* pch, *pNextCh = NULL;
	if (pBasePayload != NULL)
	{
		delete pBasePayload;
		pBasePayload = NULL;
	}

	if( strncmp( s, "temp", 4 )== 0 )
	{
		PayloadTemperature *temp = new PayloadTemperature();
		if (EmonSerial::ParseTemperaturePayload(s, temp))
		{
			parsed = true;
			pBasePayload = temp;

			char buf[100];
			char topic[100];
			for( int i=0; i< temp->numSensors;i++)
			{
				sprintf(topic, "temperature/temp/%d/%d", temp->subnode,i);
				sprintf(buf, "%d.%02d", temp->temperature[i] / 100, temp->temperature[i] % 100);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
		}
	}
	else if (strncmp(s, "pulse", 5) == 0)
	{
		PayloadPulse* pulse = new PayloadPulse();
		if (EmonSerial::ParsePulsePayload(s, pulse))
		{
			parsed = true;
			pBasePayload = pulse;
			
			char buf[100];
			char topic[100];

			for (int i = 0; i < 4; i++)
			{
				sprintf(topic, "power/%d", i);
				sprintf(buf, "%d", pulse->power[i]);
				m_MQTTClient.Publish(topic, buf);
				sprintf(topic, "pulse/%d", i);
				sprintf(buf, "%d", pulse->pulse[i]);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
			sprintf(topic, "supplyV/pulse");
			sprintf(buf, "%d", pulse->supplyV);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
		}
	}
	else if (strncmp(s, "scl", 3) == 0)
	{
		PayloadScale* p = new PayloadScale();
		if (EmonSerial::ParseScalePayload(s, p))
		{
			parsed = true;
			pBasePayload = p;
			char buf[100];
			char topic[100];
			sprintf(topic, "scales/%d", p->subnode);
			sprintf(buf, "%d", p->grams);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "supplyV/scales/%d", p->subnode);
			sprintf(buf, "%d", p->supplyV);
			m_MQTTClient.Publish(topic, buf);
		}
	}
	else if (strncmp(s, "rain", 4) == 0)
	{
		PayloadRain* rain = new PayloadRain();
		if (EmonSerial::ParseRainPayload(s, rain))
		{
			parsed = true;
			pBasePayload = rain;
			char buf[100];
			char topic[100];
			sprintf(topic, "rain");
			sprintf(buf, "%d", rain->rainCount);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "temperature/rain/0");
			sprintf(buf, "%d.%02d", rain->temperature / 100, rain->temperature % 100);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "supplyV/rain");
			sprintf(buf, "%d", rain->supplyV);
			m_MQTTClient.Publish(topic, buf);
		}
	}
	else if (strncmp(s, "base", 4) == 0)
	{
		PayloadBase* p = new PayloadBase();
		if (EmonSerial::ParseBasePayload(s, p))
		{
			parsed = true;
			pBasePayload = p;

			char buf[100];
			char topic[100];
			sprintf(topic, "base");
			sprintf(buf, "%d", (int)p->time);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
		}
	}
	else if (strncmp(s, "disp", 4) == 0)
	{
		PayloadDisp* disp = new PayloadDisp();
		if (EmonSerial::ParseDispPayload(s, disp))
		{
			parsed = true;
			pBasePayload = disp;

			char buf[100];
			char topic[100];
			sprintf(topic, "temperature/disp/%d/0", disp->subnode);
			sprintf(buf, "%d.%02d", disp->temperature / 100, disp->temperature % 100);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
		}
	}
	else if (strncmp(s, "hws", 3) == 0)
	{
		PayloadHWS* hws = new PayloadHWS();
		if (EmonSerial::ParseHWSPayload(s, hws))
		{
			parsed = true;
			pBasePayload = hws;

			char buf[100];
			char topic[100];
			for (int i = 0; i < 7; i++)
			{
				sprintf(topic, "temperature/hws/%d", i);
				sprintf(buf, "%d", hws->temperature[i] );
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
			for (int i = 0; i < 3; i++)
			{
				sprintf(topic, "pump/hws/%d", i);
				sprintf(buf, "%d", hws->pump[i]);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
		}
	}
	else if (strncmp(s, "wtr", 3) == 0)
	{
		PayloadWater* water = new PayloadWater();
		if (EmonSerial::ParseWaterPayload(s, water))
		{
			parsed = true;
			pBasePayload = water;

			char buf[100];
			char topic[100];

			sprintf(topic, "water/height/0");
			sprintf(buf, "%d", water->waterHeight);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "water/flowCount/0");
			sprintf(buf, "%d", water->flowCount);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			
			sprintf(topic, "water/flowRate/0");
			sprintf(buf, "%d", water->flowRate);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
		}
	}
	
	if (parsed)
	{
		char topic[10] = { "EmonLog" };

		m_MQTTClient.Publish(topic ,(char*) copyOfPayload.c_str());


	}

	return parsed;
}
