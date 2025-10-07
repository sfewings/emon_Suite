import argparse
import datetime
import time
import os
import yaml
from pyemonlib import emon_mqtt
from gpsdclient import GPSDClient   #pip install gpsdclient

def log_message(logPath, msg):
    time = datetime.datetime.now()
    path = f"{logPath}/{time.strftime('%Y%m%d_%H.TXT')}"
    #09/07/2021 00:00:22
    logLine = f"{time.strftime('%d/%m/%Y %H:%M:%S.%f')},{msg}"
    f=open(path, "a+", encoding= 'utf-8')
    f.write(logLine)
    f.write('\n')
    f.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Log data from gpsd sensor to hourly log.TXT files")
    parser.add_argument("-l", "--logPath", help= "Path to log", default="/share/Input/gps")
    parser.add_argument("-s", "--settingsPath", help= "Path to emon_config.yml containing emon configuration", default="/home/pi/code/emon/config/emon_config.yml")
    parser.add_argument("-m", "--MQTT", help= "IP address of MQTT server", default="localhost")
    parser.add_argument("-p", "--node", help= "Node number to publish GPS data to", default=0, type=int)
     
    args = parser.parse_args()
    logPath = str(args.logPath)
    mqttServer = str(args.MQTT)
    nodeNumber = int(args.node)
  
    settingsFile = open(args.settingsPath, 'r')
    settings = yaml.full_load(settingsFile)

    emonMQTT = emon_mqtt.emon_mqtt(mqtt_server=mqttServer, mqtt_port = 1883, settingsPath=args.settingsPath)

    numSatellites = 0   #update from SKY class and transmit as our RSSI !
    with GPSDClient(host="127.0.0.1") as client:
       for report in client.dict_stream(convert_datetime=True):
         if report['class'] == 'SKY':
             numSatellites = report['uSat']
         if report['class'] == 'TPV':
            log_message(logPath, report)
            #format for emon is "gps,subnode,latitude,longitude,course,speed"
            buf = "gps,%d,%.7f,%.7f,%.2f,%.2f:%d" %(nodeNumber, report.get('lat', 'n/a'), report.get('lon', 'n/a'), report.get('track', 'n/a'), report.get('speed', 'n/a'),numSatellites)
            emonMQTT.process_line('gps', buf)
            print(buf)
