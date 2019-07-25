# emon_Suite
Arduino based home electricity and temperature monitoring
These libraries are based on much of the work from the [Open Energy Monitor project](https://openenergymonitor.org) which in turn was based on the JeeNode and [JeeLib libraries](https://github.com/jeelabs/jeelib) for low power and RFM12b/RFM69 support.


#Gereral usage
Data is captured on sensors connected to multiple Arduino based devices and transmitted by RF12b/RF69W 915MHz radios. Data is used in the following ways
1. Immeditely within the RF network for display on LCD devices.
2. Logged to SD card for archive and historic data processing
3. Posted to external IoT dataa store (Thingspeak) for mobile phone and internet charting
4. Published on MQTT for Raspberry Pi consumption and Node-Red usage 

##Shared libraries

###EmonShared
Definitions for packet data, print, store and parse routines

##EmonEEPROM
Definitions and routines for storing and retreiving node settings (subnode, relay, relay Nodes) from EEPROM

##Arduino based nodes and sources

###emon_NanodeReceiver
This is the hub receiver connected to the internet that receives NTP time and pushes data to [Thingspeak.com](https://thingspeak.com/channels/public?username=sfewings) . Based on the [Nanode](https://wiki.hackerspaces.org/Nanode) using the ENC28J60 it receives NTP time to provide current time to required nodes. 
 
###emon_logger
Stores all received packets in text format to an SD caard. This allows archive and historic data processing

###emon_loggerFromSerial
THis receives the serial log information from any of the nodes, parses the packet and logs to an SD card. It may collect the data from multiple serial inputs (if required)

###emon_StandardLCD
This is the display unit for household monitoring of energy, temperature, rain and water usage. The 2x16 LCD also displays node network diagnostics. The display also has a DS18B20 temperature sensor (room temperature).

###emon_JeenodePulse
Measures pulse inputs from multiple mains power monitors. These also transmit a total pulse count since installation that allows simple day/month/year totals to be calculated.

###emon_EEPROMConfig
This is used to configure the subnode and relay capability of the nextwork. Multiple nodes for sensors are supported (temperature, watre, display, scales). The subnode number is configured using this utility. 
Becuase of the limited range of the RF packets within a large house, nodes can be configured to _relay_ other node's packets. to prevent flooding of the network, each relay node has an id (maximum of 8) and so does not relay a packet is has already seen. A nodes _relay_ id and the range of nodes it may relay are configured using  emon_EEPROMConfig.

###emon_JeenodeHWS
This sketch captures the serial data from a [HeatTrap solar and heatpump hot water system](http://heat-trap.com.au/) and transmits the data on the network.

###emon_Scales
An Arduino connected to loadcells through a HX711 can monitor scale usage and transmit when a reading has been made.

###emon_WaterLevel
An Arduino based water measure. Supports the DS1603L non-intrusive water level sensor. This provides water height in a tank. It also supports pulse counts from a inline water sensor. The pulse value is a lifetime accumulative value.

###emon_JeenodeTemperature
Supports up to 4 DS18B20 temperaature sensors and transmits on the network.

###RainGaugeJeenode
Supports a rain guage with 0.2mm per pulse sensor. Also captures a DS18B20 temperature (outside temperature) and transmits on the network.

##Non-Arduino projects
These additional libraries allow integration with Raspberry Pi based monitoring and display software.

###Emon_SerialToMQTT
Takes packet data afrom a serial port and publishes on MQTT. C++ sources suitable for Windows and Linux

###Emon_LogToJson
Read logged daily text files and convert to .json ready for display of daily, monthly and annual charts.

