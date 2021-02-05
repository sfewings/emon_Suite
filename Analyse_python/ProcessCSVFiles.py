import pandas as pd
import datetime
import os
import numpy
import re

def CreateStats(inPath, outPath=None, coll=None):
    df = pd.read_csv (inPath, sep = ",", header=0,parse_dates=[0], index_col=0 )

    print ("count={} ".format(df["Consumed"].count() ),end="")

    dates = pd.date_range(start=df.index[0], end=df.index[-1], normalize=True)

    rows_list = []
    for d in dates:
        df2 = df.loc[str(d.date())]
        dict1 = {}
        dict1.update( {"Consumed":d.date()              } )
        dict1.update( {"count":df2["Consumed"].count()  } )
        dict1.update( {"mean":df2["Consumed"].mean()   } )
        dict1.update( {"median":df2["Consumed"].median() } )
        dict1.update( {"max":df2["Consumed"].max()     } )
        dict1.update( {"min":df2["Consumed"].min()     } )
        dict1.update( {"std":df2["Consumed"].std()     } )
        dict1.update( {"var":df2["Consumed"].var()     } )
        if(not coll is None):
            coll.append(dict1)

    if( not outPath is None):
        dfOut = pd.DataFrame(rows_list)
        dfOut.set_index("date")
        dfOut.to_csv(outPath)
        print("Exported"+ outPath)
    else:
        print("Collected"  + str(len(coll) ) )
    

def process():
    inPath = ".\\data"

    files = list_files(inPath)
    collectionList = None #[]
    for f in files:
        newPath = f.replace(inPath,inPath+"stats\\").replace(".csv","_stats.csv")
        #newPath = newPath.replace(".csv","_stats.csv")
        folder = newPath[0:newPath.rfind("\\")]
        if not os.path.exists(folder):
            os.makedirs(folder)
        if not os.path.exists(newPath):
            print("Reading {} ".format(f),end="")
            #CreateStats(f, newPath)
            CreateStats(f, newPath, coll = collectionList)

    if(not collectionList is None):
        collectionList.sort(key=lambda x: x['date'])
        dfOut = pd.DataFrame(collectionList)
        dfOut.set_index("date")
        dfOut.to_csv("Output.csv")
        print("Exported"+"Output.csv")

#=========================================

def list_files(dir, regExp):
    r = []
    for root, dirs, files in os.walk(dir):
        for name in files:
            if( re.search(regExp,name) != None):
            # if(name.find(".txt") >= 0 and root.find("\\stats\\") == -1):
            #     r.append(os.path.join(root, name))
            #if(name.find(".txt") >= 0 and name.find('.') == 8 ):
                r.append(os.path.join(root, name))
    return r

def CreateOutputProfile(files, outputName):
    dfSum = None
    count = 1
    for f in files:
        df = pd.read_csv(f, sep = ",", header=0,parse_dates=[0], index_col=0 )
        df.fillna(0, inplace=True)
        if( df.shape[0] == 1440):
            if( dfSum is None ):
                dfSum = df
            else:
                dfSum = dfSum.add( df.values )
                count +=1
    #dfSum['time'] = pd.to_datetime(dfSum['time']).dt.date
    dfSum.div(count).to_csv(outputName )

def processSeasons():
    #inPath = "input"
    inPath = "C:/Users/StephenFewings/OneDrive - PenningtonScott/My_Documents/Home/HomePower/Emon_logs/Output/power"
    months = ["Jan", "Feb", "Mar","Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    mNum = 1
    for m in months:
        CreateOutputProfile(list_files(inPath, r"20\d\d{:02d}\d\d.txt".format(mNum) ), "./output/" +m +".txt" ) 
        mNum += 1
    CreateOutputProfile(list_files(inPath, r"20\d\d0(4|5|6|7|8|9)\d\d.txt" ), "./output/Winter.txt")
    CreateOutputProfile(list_files(inPath, r"20\d\d(10|11|12|01|02|03)\d\d.txt" ), "./output/Summer.txt")
    CreateOutputProfile(list_files(inPath, r"20\d\d\d\d\d\d.txt" ), "./output/Allyear.txt")
    CreateOutputProfile(list_files(inPath, r"2020\d\d\d\d.txt" ), "./output/2020.txt")

processSeasons()