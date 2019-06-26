#include "PayloadFactory.h"
#include "EmonMQTTClient.h"


PayloadFactory::PayloadFactory()
{
	pBasePayload = NULL;
	
	m_MQTTClient.Initialise();
}


PayloadFactory::~PayloadFactory()
{
	if (pBasePayload != NULL)
		delete pBasePayload;
	pBasePayload = NULL;

}

bool PayloadFactory::PublishPayload(char* s)
{
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
			pBasePayload = temp;

			char buf[100];
			char topic[100];
			for( int i=0; i< temp->numSensors;i++)
			{
				sprintf_s(topic, "temperature/temp/%d/%d", temp->subnode,i);
				sprintf_s(buf, "%d.%02d", temp->temperature[i] / 100, temp->temperature[i] % 100);
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
			pBasePayload = pulse;
			
			char buf[100];
			char topic[100];

			for (int i = 0; i < 4; i++)
			{
				sprintf_s(topic, "power/%d", i);
				sprintf_s(buf, "%d", pulse->power[i]);
				m_MQTTClient.Publish(topic, buf);
				sprintf_s(topic, "pulse/%d", i);
				sprintf_s(buf, "%d", pulse->pulse[i]);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
			sprintf_s(topic, "supplyV/pulse");
			sprintf_s(buf, "%d", pulse->supplyV);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
		}
	}
	else if (strncmp(s, "scl", 3) == 0)
	{
		PayloadScale* p = new PayloadScale();
		if (EmonSerial::ParseScalePayload(s, p))
		{
			pBasePayload = p;
			char buf[100];
			char topic[100];
			sprintf_s(topic, "scales/%d", p->subnode);
			_ltoa_s(p->grams, buf, sizeof(buf),10);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf_s(topic, "supplyV/scales/%d", p->subnode);
			sprintf_s(buf, "%d", p->supplyV);
			m_MQTTClient.Publish(topic, buf);
		}
	}
	else if (strncmp(s, "rain", 4) == 0)
	{
		PayloadRain* rain = new PayloadRain();
		if (EmonSerial::ParseRainPayload(s, rain))
		{
			pBasePayload = rain;
			char buf[100];
			char topic[100];
			sprintf_s(topic, "rain");
			sprintf_s(buf, "%d", rain->rainCount);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf_s(topic, "temperature/rain/0");
			sprintf_s(buf, "%d.%02d", rain->temperature / 100, rain->temperature % 100);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf_s(topic, "supplyV/rain");
			sprintf_s(buf, "%d", rain->supplyV);
			m_MQTTClient.Publish(topic, buf);
		}
	}
	else if (strncmp(s, "base", 4) == 0)
	{
		PayloadBase* p = new PayloadBase();
		if (EmonSerial::ParseBasePayload(s, p))
		{
			pBasePayload = p;

			char buf[100];
			char topic[100];
			sprintf_s(topic, "base");
			sprintf_s(buf, "%d", (int)p->time);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
		}
	}
	else if (strncmp(s, "disp", 4) == 0)
	{
		PayloadDisp* disp = new PayloadDisp();
		if (EmonSerial::ParseDispPayload(s, disp))
		{
			pBasePayload = disp;

			char buf[100];
			char topic[100];
			sprintf_s(topic, "temperature/disp/%d/0", disp->subnode);
			sprintf_s(buf, "%d.%02d", disp->temperature / 100, disp->temperature % 100);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
		}
	}
	else if (strncmp(s, "hws", 3) == 0)
	{
		PayloadHWS* hws = new PayloadHWS();
		if (EmonSerial::ParseHWSPayload(s, hws))
		{
			pBasePayload = hws;

			char buf[100];
			char topic[100];
			for (int i = 0; i < 7; i++)
			{
				sprintf_s(topic, "temperature/hws/%d", i);
				sprintf_s(buf, "%d", hws->temperature[i] );
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
			for (int i = 0; i < 3; i++)
			{
				sprintf_s(topic, "pump/hws/%d", i);
				sprintf_s(buf, "%d", hws->pump[i]);
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
			pBasePayload = water;

			char buf[100];
			char topic[100];

			sprintf_s(topic, "water/height/0");
			sprintf_s(buf, "%d", water->waterHeight);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf_s(topic, "water/flowCount/0");
			sprintf_s(buf, "%d", water->flowCount);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			
			sprintf_s(topic, "water/flowRate/0");
			sprintf_s(buf, "%d", water->flowRate);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
		}
	}
	
	return pBasePayload != NULL;
}
