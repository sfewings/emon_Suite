import argparse
import datetime
import paho.mqtt.client as mqtt
import serial


def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")

# def on_publish(client,userdata,result):
#     print("published")

# def on_message(client, settings, msg):
#     line = msg.payload.decode("utf-8")
#     message = msg.topic
#     print( f"MQTT received {msg.topic}, {line}" )

def check_int(s):
    if s[0] in ('-', '+'):
        return s[1:].isdigit()
    return s.isdigit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Connect emonRaspPiSerial to serial port and publish to MQTT")
    parser.add_argument("-s", "--Serial", help= "serial port to listen", default="/dev/ttyUSB0")
    parser.add_argument("-m", "--MQTT", help= "IP address of MQTT server", default="localhost")
    args = parser.parse_args()
    mqttServer = str(args.MQTT)
    serialPort = str(args.Serial)

    mqttClient = mqtt.Client()
    mqttClient.on_connect = on_connect
    #mqttClient.on_publish = on_publish
    #mqttClient.on_message = on_message
    mqttClient.connect(mqttServer, 1883, 60)

    nodes = ['rain','temp','disp','pulse','hws','wtr','scl','bat','inv','bee','air']
    RSSIvalue = 0
    lastSentTimeUpdate = datetime.datetime.now()

    with serial.Serial(serialPort, 9600, timeout=5) as ser:
        while 1:
            line = ser.readline().decode('utf-8').rstrip('\r\n')
            if(line.startswith("RSSI")):
                RSSIvalue = int(line[6:])     #parse -36 from "RSSI: -36"
            else:
                lineFields = line.split(',',2)
                if( len(lineFields)>2 and lineFields[0].rstrip('0123456789') in nodes and check_int(lineFields[1]) ):
                    if(RSSIvalue!=0):
                        line = f"{line}:{RSSIvalue}"
                    mqttClient.publish("EmonLog",line)
                    print(line)
                    RSSIvalue = 0
            #send a time update every 30 seconds
            time = datetime.datetime.now()
            if( (time-lastSentTimeUpdate).total_seconds() >30):
                baseMsg = f"base,{int(time.timestamp())+60*60*8}"       #Perth timezone!
                #ser.write(baseMsg.encode('utf-8'))
                print(baseMsg)
                lastSentTimeUpdate = time



