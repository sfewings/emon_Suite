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

#include "..\..\\Examples\RS-232\rs232.h"
#include "..\\EmonShared\EmonShared.h"
#include "PayloadFactory.h"


int main()
{
	int i, n,
		cport_nr = 6,        /* /dev/ttyS0 (COM1 on windows) */
		bdrate = 9600;       /* 9600 baud */

	PayloadFactory pf;


	unsigned char buf[4096];

	char mode[] = { '8','N','1',0 };


	if (RS232_OpenComport(cport_nr, bdrate, mode, 0))
	{
		printf("Can not open comport\n");

		return(0);
	}

	while (1)
	{
		n = RS232_PollComportLine(cport_nr, buf, 4095);

		if (n > 0)
		{
			buf[n] = 0;   /* always put a "null" at the end of a string! */

			for (i = 0; i < n; i++)
			{
				if (buf[i] < 32)  /* replace unreadable control-codes by dots */
				{
					buf[i] = '.';
				}
			}

			printf("received %i bytes: %s", n, (char*)buf);
			if(! pf.PublishPayload((char*) buf) )
				std::cout << "...not parsed" << std::endl;

		}

#ifdef _WIN32
		Sleep(100);
#else
		usleep(100000);  /* sleep for 100 milliSeconds */
#endif
	}

	return(0);
}

