import argparse
import datetime
import time
import serial
import yaml
from pyemonlib import emon_mqtt

import queue
import threading


def check_int(s):
    if s[0] in ('-', '+'):
        return s[1:].isdigit()
    return s.isdigit()


def writeLog(logPath, line):
    time = datetime.datetime.now()
    path = f"{logPath}/{time.strftime('%Y%m%d_emonSerialToMQTT.TXT')}"
    #09/07/2021 00:00:22
    logLine = f"{time.strftime('%d/%m/%Y %H:%M:%S')},{line}"
    f=open(path, "a+", encoding= 'utf-8')
    f.write(logLine)
    f.write('\n')
    f.close()
    print(logLine)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Connect emonRaspPiSerial to serial port and publish to MQTT")
    parser.add_argument("-c", "--Serial", help= "serial port to listen", default="/dev/ttyUSB0")
    parser.add_argument("-s", "--settingsPath", help= "Path to emon_config.yml containing emon configuration", default="/share/emon_Suite/python/emon_config.yml")
    parser.add_argument("-l", "--logPath", help= "Path to log", default="/share/Output/emonSerialToMQTT")
    parser.add_argument("-m", "--MQTT", help= "IP address of MQTT server", default="localhost")
    args = parser.parse_args()
    mqttServer = str(args.MQTT)
    serialPort = str(args.Serial)
    logPath = str(args.logPath)
    
    writeLog(logPath, args)

    # get the node names from the settings file
    # nodes = ['rain','temp','disp','pulse','hws','wtr','scl','bat','inv','bee','air','leaf']
    nodes = []
    settingsFile = open(args.settingsPath, 'r')
    settings = yaml.full_load(settingsFile)
    for i,key in enumerate(settings):
        nodes.append(key)
    nodes.append('base')

    emonMQTT = emon_mqtt.emon_mqtt(mqtt_server=mqttServer, mqtt_port = 1883, settingsPath=args.settingsPath)

    lastSentTimeUpdate = datetime.datetime.now()
    lastReceivedDataPacket = datetime.datetime.now()

    RSSIvalue = 0

    with serial.Serial(serialPort, 9600, timeout=5) as ser:
        while ((datetime.datetime.now()-lastReceivedDataPacket).total_seconds() < 600):
            line = ser.readline().decode('utf-8').rstrip('\r\n')
            writeLog(logPath, line)
            if(line.startswith("RSSI")):
                RSSIvalue = int(line[6:])     #parse -36 from "RSSI: -36"
            else:
                lineFields = line.split(',',2)
                if( len(lineFields)>2 and lineFields[0].rstrip('0123456789') in nodes and check_int(lineFields[1]) ):
                    if(RSSIvalue!=0):
                        line = f"{line}:{RSSIvalue}"
                    emonMQTT.process_line(lineFields[0].rstrip('0123456789'), line)
                    #writeLog(logPath, line)
                    #print(line)
                    RSSIvalue = 0
                    lastReceivedDataPacket = datetime.datetime.now()

            #send a time update every 30 seconds
            t = datetime.datetime.now()
            if( (t-lastSentTimeUpdate).total_seconds() >30):
                lastSentTimeUpdate = t
                offset = time.timezone if (time.localtime().tm_isdst == 0) else time.altzone
                baseMsg = f"base,{int(t.timestamp())-offset}"
                ser.write(baseMsg.encode('utf-8'))
                writeLog(logPath, baseMsg)
                #print(baseMsg)
    
    writeLog(logPath, f"emonSerialToMQTT closing. No serial recieved for {(datetime.datetime.now()-lastReceivedDataPacket).total_seconds()} seconds.")
    #print(f"emonSerialToMQTT closing. No serial recieved for {(datetime.datetime.now()-lastReceivedDataPacket).total_seconds()} seconds.")

    writeLog(logPath, "Terminating" )