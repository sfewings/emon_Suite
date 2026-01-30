import argparse
import datetime
import time
import os
import yaml
#from pyemonlib import emon_mqtt
from pyEmon.pyemonlib import emon_mqtt


def check_int(s):
    """Check if a string is an integer"""
    if s[0] in ('-', '+'):
        return s[1:].isdigit()
    return s.isdigit()


def writeLog(logPath, line):
    """Write log message with timestamp"""
    current_time = datetime.datetime.now()
    logLine = f"{current_time.strftime('%d/%m/%Y %H:%M:%S')},{line}"
    print(logLine)
    if os.path.exists(logPath):
        filePath = f"{logPath}/{current_time.strftime('%Y%m%d_emonCSVToMQTT.TXT')}"
        with open(filePath, "a+", encoding='utf-8') as f:
            f.write(logLine)
            f.write('\n')


def parse_timestamp(timestamp_str):
    """Parse timestamp string in format DD/MM/YYYY HH:MM:SS"""
    return datetime.datetime.strptime(timestamp_str, '%d/%m/%Y %H:%M:%S')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read CSV file and publish to MQTT")
    parser.add_argument("-f", "--file", help="Path to CSV input file", required=True)
    parser.add_argument("-s", "--settingsPath", help="Path to emon_config.yml containing emon configuration", 
                        default="/share/emon_Suite/python/emon_config.yml")
    parser.add_argument("-l", "--logPath", help="Path to log directory", 
                        default="/share/Output/emonCSVToMQTT")
    parser.add_argument("-m", "--MQTT", help="IP address of MQTT server", default="localhost")
    args = parser.parse_args()
    
    mqttServer = str(args.MQTT)
    csvFile = str(args.file)
    logPath = str(args.logPath)
    
    writeLog(logPath, f"Starting emonCSVToMQTT with file: {csvFile}, MQTT: {mqttServer}")

     # Create MQTT instance
    try:
        emonMQTT = emon_mqtt.emon_mqtt(mqtt_server=mqttServer, mqtt_port=1883, 
                                        settingsPath=args.settingsPath)
        writeLog(logPath, f"Connected to MQTT server at {mqttServer}")
    except Exception as e:
        writeLog(logPath, f"Error connecting to MQTT: {str(e)}")
        exit(1)

    # Read and process CSV file
    try:
        with open(csvFile, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        if not lines:
            writeLog(logPath, "CSV file is empty")
            exit(1)

        previous_timestamp = None
        
        for line_num, line in enumerate(lines, 1):
            line = line.rstrip('\r\n')
            if not line.strip():
                continue  # Skip empty lines
            
            try:
                # Parse the line: timestamp,device_name,data...:RSSI
                parts = line.split(',', 2)
                
                if len(parts) < 3:
                    writeLog(logPath, f"Line {line_num}: Invalid format - {line}")
                    continue
                
                timestamp_str = parts[0]
                device_data = parts[1] + ',' + parts[2]
                
                # Parse timestamp
                current_timestamp = parse_timestamp(timestamp_str)
                
                # If not the first line, wait for the time difference
                if previous_timestamp is not None:
                    time_diff = (current_timestamp - previous_timestamp).total_seconds()
                    if time_diff > 0:
                        writeLog(logPath, f"Waiting {time_diff} seconds before processing next line")
                        time.sleep(time_diff)
                    elif time_diff < 0:
                        writeLog(logPath, f"Warning: Line {line_num} has earlier timestamp than previous line")
                
                # Extract device name (remove trailing digits)
                device_name_parts = device_data.split(',')
                device_name = device_name_parts[0].rstrip('0123456789')
                
                writeLog(logPath, f"Processing: {line}")
                emonMQTT.process_line(device_data)
                
                previous_timestamp = current_timestamp
                
            except ValueError as e:
                writeLog(logPath, f"Line {line_num}: Error parsing line - {str(e)}")
                writeLog(logPath, f"  Line content: {line}")
                continue
            except Exception as e:
                writeLog(logPath, f"Line {line_num}: Unexpected error - {str(e)}")
                writeLog(logPath, f"  Line content: {line}")
                continue
        
        writeLog(logPath, f"Successfully processed {len(lines)} lines from {csvFile}")
        
    except FileNotFoundError:
        writeLog(logPath, f"Error: CSV file not found - {csvFile}")
        exit(1)
    except Exception as e:
        writeLog(logPath, f"Error reading CSV file: {str(e)}")
        exit(1)
    
    writeLog(logPath, "emonCSVToMQTT completed successfully")
