import argparse
import datetime
import time
import serial
import yaml
from pyemonlib import emon_mqtt

def check_int(s):
    if s[0] in ('-', '+'):
        return s[1:].isdigit()
    return s.isdigit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Connect emonRaspPiSerial to serial port and publish to MQTT")
    parser.add_argument("-c", "--Serial", help= "serial port to listen", default="/dev/ttyUSB0")
    parser.add_argument("-c2", "--Serial2", help= "serial port 2 to listen", default="none")
    parser.add_argument("-s", "--settingsPath", help= "Path to emon_config.yml containing emon configuration", default="/share/emon_Suite/python/emon_config.yml")
    parser.add_argument("-m", "--MQTT", help= "IP address of MQTT server", default="localhost")
    args = parser.parse_args()
    mqttServer = str(args.MQTT)
    serialPort = str(args.Serial)
    serialPort2 = str(args.Serial2)

    # get the node names from the settings file
    # nodes = ['rain','temp','disp','pulse','hws','wtr','scl','bat','inv','bee','air','leaf']
    nodes = []
    settingsFile = open(args.settingsPath, 'r')
    settings = yaml.full_load(settingsFile)
    for i,key in enumerate(settings):
        nodes.append(key)
    nodes.append('base')

    emonMQTT = emon_mqtt.emon_mqtt(mqtt_server=mqttServer, mqtt_port = 1883, settingsPath=args.settingsPath)

    RSSIvalue = 0
    lastSentTimeUpdate = datetime.datetime.now()

    sers = []
    sers.append( serial.Serial(serialPort, 9600, timeout=1) )

    if(serialPort2 != "none"):
        sers.append( serial.Serial(serialPort2,9600, timeout=1))

    while 1:
        for ser in sers:
            line = ser.readline().decode('utf-8').rstrip('\r\n')
            print(line)
            if(line.startswith("RSSI")):
                RSSIvalue = int(line[6:])     #parse -36 from "RSSI: -36"
            else:
                lineFields = line.split(',',2)
                if( len(lineFields)>2 and lineFields[0].rstrip('0123456789') in nodes and check_int(lineFields[1]) ):
                    if(RSSIvalue!=0):
                        line = f"{line}:{RSSIvalue}"
                    emonMQTT.process_line(lineFields[0].rstrip('0123456789'), line)
                    print(line)
                    RSSIvalue = 0

        #send a time update every 30 seconds
        t = datetime.datetime.now()
        if( (t-lastSentTimeUpdate).total_seconds() >30):
            lastSentTimeUpdate = t
            for ser in sers:
                offset = time.timezone if (time.localtime().tm_isdst == 0) else time.altzone
                baseMsg = f"base,{int(t.timestamp())-offset}"
                ser.write(baseMsg.encode('utf-8'))
                print(baseMsg)
    


