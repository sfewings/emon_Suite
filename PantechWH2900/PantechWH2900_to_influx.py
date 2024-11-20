import argparse
import datetime
import pytz                     #pip install pytz
import paho.mqtt.client as mqtt #pip install paho-mqtt
import json
from influxdb_client import InfluxDBClient, Point   #pip install influxdb-client[ciso]
from influxdb_client.client.write_api import SYNCHRONOUS, WriteOptions

def append_to_file(logPath, new_entry):
    time = datetime.datetime.now()
    path = f"{logPath}/{time.strftime('%Y%m%d.TXT')}"
    f=open(path, "a+", encoding= 'utf-8')
    json.dump(new_entry, f, indent=4)
    f.close()
    print(f"Written to file => {path}")
    

# The callback function of connection
def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe("pantech/#")
    
# The callback function for received message
def on_message(client, user_data, msg):
    line = msg.payload.decode("utf-8")
    #node = line.split(',',1)[0].rstrip('0123456789')
    #$time = datetime.datetime.now(pytz.utc)
    #print(f"command{node}, time {time}, settings {settings[node]}")
    #settings.process_line(node, time, line)
    print( line )

    time = datetime.datetime.now(pytz.utc)
    json_dict = json.loads(line)
    for key, value in json_dict.items():
        print(f"Key: {key}, Value: {value}", end=''),
        if isinstance(value, str) or value is None:
            print(" => Not written")   
        else:
            p = Point("pantech").tag("sensor",f"pantech/{key}")\
                                .tag("sensorGroup","pantech")\
                                .tag("sensorName",f"{key}")\
                                .field("value",value/1.0).time(time)
            user_data["influx_write_api"].write(bucket="sensors", record=p)
            print(" => Written")
    
    new_entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        'data': json_dict
        }
    append_to_file( user_data["logPath"], new_entry )


def subscribe_mqtt( mqttServer, user_data ):   

    mqttClient = mqtt.Client()
    mqttClient.user_data_set( user_data )

    mqttClient.on_connect = on_connect
    mqttClient.on_message = on_message
    mqttClient.connect(mqttServer, 1883, 60)
    mqttClient.loop_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Subscribe to MQTT Pantech weather station messages and parse to Influx. Requires bancha/ecowitt2mqtt docker image")
    parser.add_argument("-m", "--MQTT", help= "IP address of MQTT server", default="localhost")
    parser.add_argument("-i", "--influx", help= "IP address of influxDB server", default="localhost" )
    parser.add_argument("-l", "--logPath", help= "Path to log", default="/share/Input")

    args = parser.parse_args()
    mqttServer = str(args.MQTT)

    url = f"http://{args.influx}:8086"
    
    #test_parse_json()
    client = InfluxDBClient(url, token="my-token", org="my-org")
    influx_write_api = client.write_api(write_options=WriteOptions(batch_size=50, flush_interval=10))
    user_data = {"influx_write_api" : influx_write_api,
                  "logPath": args.logPath}

    subscribe_mqtt( mqttServer, user_data )