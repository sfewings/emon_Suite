import os
import datetime
import argparse
from pyemonlib import emon_influx

#ei = emon_influx.emon_influx(settingsPath="/share/emon_Suite/PythonBindings/emon_config.yml")
#ei.process_files("/share/Input_all")

def process_file(path):
    ei = emon_influx.emon_influx(settingsPath="/share/emon_Suite/PythonBindings/emon_config.yml")
    ei.process_file(path)


def process_files(path, fromFile="", toFile=""):
    files = os.listdir(path)
    files.sort()

    start    = 0
    end = len(files)
    if( len(fromFile) != 0 ):
        start  = files.index(fromFile)
    if( len(toFile) != 0 ):
        end = files.index(toFile)
    
    for i in range(start, end):
        file = files[i]
        if file.endswith(".TXT"):
            print(f"{datetime.datetime.now()}, {i-start} of {end-start}, {file}")
            process_file(os.path.join(path,file))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import emon log.TXT files to Influx")
    parser.add_argument("--fromFile", help= "the start text file to import from", default="")
    parser.add_argument("--toFile", help= "the last text file to import from", default="")
    parser.add_argument("path", help= "Input folder to read .TXT files from", default="/share/Input")
    args = parser.parse_args()
    fromFile = str(args.fromFile)
    toFile = str(args.toFile)
    path = str(args.path)

    process_files(path , fromFile, toFile)
