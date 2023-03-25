import argparse
import datetime
import pytz
from pathlib import Path
#from pyemonlib import emon_influx
import paho.mqtt.client as mqtt

# The callback function of connection
def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe("EmonLog/#")
    
# The callback function for received message
def on_message(client, logPath, msg):
    line = msg.payload.decode("utf-8")
    node = line.split(',',1)[0].rstrip('0123456789')
    time = datetime.datetime.now()
    path = f"{logPath}/{time.strftime('%Y%m%d.TXT')}"
    #09/07/2021 00:00:22
    logLine = f"{time.strftime('%d/%m/%Y %H:%M:%S')},{line}"
    f=open(path, "a+", encoding= 'utf-8')
    f.write(logLine)
    f.write('\n')
    f.close()
    print(logLine)

def subscribe_mqtt( mqttServer, logPath ):   

    mqttClient = mqtt.Client()
    mqttClient.user_data_set( logPath )

    mqttClient.on_connect = on_connect
    mqttClient.on_message = on_message
    mqttClient.connect(mqttServer, 1883, 60)
    mqttClient.loop_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Log Emon mqtt messages to daily log.TXT files")
    parser.add_argument("-m", "--MQTT", help= "IP address of MQTT server", default="0.0.0.0")
    parser.add_argument("-l", "--logPath", help= "Path to log", default="/share/Input")
    args = parser.parse_args()
    mqttServer = str(args.MQTT)
    logPath = str(args.logPath)
    
    Path(logPath).mkdir(parents=True, exist_ok=True)

    print(f'mqttServer={mqttServer}')
    
    subscribe_mqtt(mqttServer, logPath)
