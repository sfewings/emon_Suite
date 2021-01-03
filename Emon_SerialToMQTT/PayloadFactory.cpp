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
			for(int i=0; i<((water->numSensors & 0xF0)>>4);i++ )
			{
				sprintf(topic, "water/height/%d/%d", water->subnode,i);
				sprintf(buf, "%d", water->waterHeight[i]);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
			for(int i=0; i<(water->numSensors & 0xF);i++ )
			{
				sprintf(topic, "water/flowCount/%d/%d", water->subnode,i);
				sprintf(buf, "%d", water->flowCount[i]);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
			
			sprintf(topic, "supplyV/water/%d", water->subnode);
			sprintf(buf, "%d", water->supplyV);
			m_MQTTClient.Publish(topic, buf);
		}
	}
	else if (strncmp(s, "bat", 3) == 0)
	{
		PayloadBattery* bat = new PayloadBattery();
		if (EmonSerial::ParseBatteryPayload(s, bat))
		{
			parsed = true;
			pBasePayload = bat;

			char buf[100];
			char topic[100];
			for (int i = 0; i < BATTERY_SHUNTS; i++)
			{
				sprintf(topic, "battery/power/%d/%d", bat->subnode, i);
				sprintf(buf, "%d", bat->power[i]);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
			for (int i = 0; i < BATTERY_SHUNTS; i++)
			{
				sprintf(topic, "battery/pulseIn/%d/%d", bat->subnode, i);
				sprintf(buf, "%d", bat->pulseIn[i]);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
			for (int i = 0; i < BATTERY_SHUNTS; i++)
			{
				sprintf(topic, "battery/pulseOut/%d/%d", bat->subnode, i);
				sprintf(buf, "%d", bat->pulseOut[i]);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
			for (int i = 0; i < MAX_VOLTAGES; i++)
			{
				sprintf(topic, "battery/voltage/%d/%d", bat->subnode, i);
				sprintf(buf, "%d", bat->voltage[i]);
				m_MQTTClient.Publish(topic, buf);
				std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
			}
		}
	}
	else if (strncmp(s, "inv", 3) == 0)
	{
		PayloadInverter* inv = new PayloadInverter();
		if (EmonSerial::ParseInverterPayload(s, inv))
		{
			parsed = true;
			pBasePayload = inv;

			char buf[100];
			char topic[100];

			sprintf(topic, "inverter/activePower/%d", inv->subnode);
			sprintf(buf, "%d", inv->activePower);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "inverter/power/%d", inv->subnode);
			sprintf(buf, "%d", inv->pvInputPower);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "inverter/batteryCapacity/%d", inv->subnode);
			sprintf(buf, "%d", inv->batteryCapacity);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "inverter/batteryCharging/%d", inv->subnode);
			sprintf(buf, "%d", inv->batteryCharging);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "inverter/batteryDischarge/%d", inv->subnode);
			sprintf(buf, "%d", inv->batteryDischarge);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "inverter/batteryVoltage/%d", inv->subnode);
			sprintf(buf, "%d", inv->batteryVoltage);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;
		}
	}
	else if (strncmp(s, "bee", 3) == 0)
	{
		PayloadBeehive* beehive = new PayloadBeehive();
		if (EmonSerial::ParseBeehivePayload(s, beehive))
		{
			parsed = true;
			pBasePayload = beehive;

			char buf[100];
			char topic[100];

			sprintf(topic, "beehive/beeInRate/%d", beehive->subnode);
			sprintf(buf, "%d", beehive->beeInRate);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "beehive/beeOutRate/%d", beehive->beeOutRate);
			sprintf(buf, "%d", beehive->beeOutRate);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "beehive/beesIn/%d", beehive->subnode);
			sprintf(buf, "%d", beehive->beesIn);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "beehive/beesOut/%d", beehive->subnode);
			sprintf(buf, "%d", beehive->beesOut);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "temperature/beehiveInside/%d/0", beehive->subnode);
			sprintf(buf, "%d.%02d", beehive->temperatureIn / 100, beehive->temperatureIn % 100);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "temperature/beehiveOutside/%d/0", beehive->subnode);
			sprintf(buf, "%d.%02d", beehive->temperatureOut / 100, beehive->temperatureOut % 100);
			m_MQTTClient.Publish(topic, buf);
			std::cout << " publish topic=" << topic << " payload=" << buf << std::endl;

			sprintf(topic, "supplyV/beehive/%d", beehive->subnode);
			sprintf(buf, "%d", beehive->supplyV);
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
