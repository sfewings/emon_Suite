import os
import datetime
import argparse
from pyemonlib import emon_influx
#from pyEmon.pyemonlib import emon_influx


def process_files(path, fromFile="", toFile="", influxURL="", settingsPath = ""):
    ei = emon_influx.emon_influx(url= influxURL, settingsPath=settingsPath, batchProcess=True)

    try:
        files = os.listdir(path)
        files.sort()

        start    = 0
        end = len(files)
        if( len(fromFile) != 0 ):
            start  = files.index(fromFile)
        if( len(toFile) != 0 ):
            end = files.index(toFile)+1
        
        for i in range(start, end):
            file = files[i]
            if file.endswith(".TXT"):
                print(f"{datetime.datetime.now()}, {i-start} of {end-start}, {file}")
                ei.process_file(os.path.join(path,file))
    finally:
        # Ensure all batches are flushed and written to influxdb before exiting
        print("Flushing and closing InfluxDB connection...")
        ei.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import emon log.TXT files to Influx")
    parser.add_argument("--fromFile", help= "the start text file to import from", default="")
    parser.add_argument("--toFile", help= "the last text file to import from", default="")
    parser.add_argument("-i", "--influx", help= "IP address of influxDB server", default="localhost")
    parser.add_argument("-s", "--settingsPath", help= "Path to emon_config.yml containing emon configuration", default="/share/emon_Suite/python/emon_config.yml")
    parser.add_argument("path", help= "Input folder to read .TXT files from", default="/share/Input")
    args = parser.parse_args()

    influxURL = f"http://{args.influx}:8086"
    
    process_files(str(args.path) , str(args.fromFile), str(args.toFile), influxURL, str(args.settingsPath))
