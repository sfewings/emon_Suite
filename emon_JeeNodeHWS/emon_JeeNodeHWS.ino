//Heattrap solar system serial reader, parser and transmit of HWS packet
//https://heat-trap.com.au/

//Radiohead RF_69 support
#include <SPI.h>
#include <RH_RF69.h>

#include <time.h>					//required for EmonShared.h
#include <EmonShared.h>

RH_RF69 g_rf69;
PayloadHWS g_hwsPayload;

void LED_On(int ms)
{
	//Connect LED to Jeenode port 2. On Arduino pin 5
	pinMode(5, OUTPUT);
	digitalWrite(5, 1);
	delay(ms);
	digitalWrite(5, 0);
}

void setup()
{
	Serial.begin(9600);

	delay(500);

	Serial.println(F("Fewings Heattrap solar HWS node for emon network"));

	LED_On(500);

	EmonSerial::PrintHWSPayload(NULL);

	if (!g_rf69.init())
		Serial.println("g_rf69 init failed");
	if (!g_rf69.setFrequency(915.0))
		Serial.println("setFrequency failed");
	g_rf69.setHeaderId(HWS_JEENODE);

	// If you are using a high power g_rf69 eg RFM69HW, you *must* set a Tx power with the
	// ishighpowermodule flag set like this:
	//g_rf69.setTxPower(14, true);

	// The encryption key has to be the same as the one in the client
	uint8_t key[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
					0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	g_rf69.setEncryptionKey(key);
}

void loop()
{
	char tok[] = ",";
	char line[256] = "";
	char* pch= NULL;
	
	//format is THx, 097, 066, 066, 062, 064, 060,PCB,042 ,PUMPS 1-4, ON  , ON  , OFF , OFF , Pump mA,2694\r\n
	if (Serial.readBytesUntil('\n', line, 256))
	{
		pch = strtok(line, tok);

		if (strcmp(pch, "THx") == 0)
		{
			for (int i = 0; i < HWS_TEMPERATURES - 1; i++)
			{
				pch = strtok(NULL, tok);
				g_hwsPayload.temperature[i] = (byte)atoi(pch);
			}
			pch = strtok(NULL, tok);	//swallow the "PCB"
			pch = strtok(NULL, tok);
			g_hwsPayload.temperature[HWS_TEMPERATURES - 1] = (byte)atoi(pch);
			pch = strtok(NULL, tok);	//swallow the "PUMPS 1-4"
			for (int i = 0; i < HWS_PUMPS; i++)
			{
				pch = strtok(NULL, tok);
				g_hwsPayload.pump[i] = strcmp(pch, " OFF ");
			}

			//transmit
			g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_STDBY);
			g_rf69.send((const uint8_t*) &g_hwsPayload, sizeof(PayloadHWS));
			if( g_rf69.waitPacketSent() )
			{
				EmonSerial::PrintHWSPayload(&g_hwsPayload);
			}
			else
			{
				Serial.println(F("No packet sent"));
			}
			g_rf69.setIdleMode(RH_RF69_OPMODE_MODE_SLEEP);

			//turn the led on pin 5 (port 2) on for 20ms
			LED_On(100);

			delay(50);	//time for the serial buffer to empty
		}
	}
	LED_On(1);
}
