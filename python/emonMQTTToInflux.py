import argparse
import datetime
import pytz
from pyemonlib import emon_influx
import paho.mqtt.client as mqtt

# The callback function of connection
def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe("EmonLog/#")
    
# The callback function for received message
def on_message(client, settings, msg):
    line = msg.payload.decode("utf-8")
    node = line.split(',',1)[0].rstrip('0123456789')
    time = datetime.datetime.now(pytz.utc)
    #print(f"command{node}, time {time}, settings {settings[node]}")
    settings.process_line(node, time, line)
    print( line )

def subscribe_mqtt( mqttServer, emonInflux ):   

    mqttClient = mqtt.Client()
    mqttClient.user_data_set( emonInflux )

    mqttClient.on_connect = on_connect
    mqttClient.on_message = on_message
    mqttClient.connect(mqttServer, 1883, 60)
    mqttClient.loop_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Subscribe to MQTT emon messages and parse to Influx")
    parser.add_argument("-m", "--MQTT", help= "IP address of MQTT server", default="localhost")
    parser.add_argument("-s", "--settingsPath", help= "Path to emon_config.yml containing emon configuration", default="/share/emon_Suite/python/emon_config.yml")
    parser.add_argument("-i", "--influx", help= "IP address of influxDB server", default="localhost")
    args = parser.parse_args()
    mqttServer = str(args.MQTT)

    url = f"http://{args.influx}:8086"
    emonInflux = emon_influx.emon_influx(url=url, settingsPath=args.settingsPath, batchProcess=False)

    subscribe_mqtt(mqttServer, emonInflux)
