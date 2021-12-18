import csv
import glob

#enumerate through all the input data repairing the rain readings that went backwards because the eeprom was not writen
#between 20210823 and 20210911

def processFile(inPath, outPath):
    tempPath ="C:\\tmp\\emonTemp.txt" 
    repaired = 0
    skipped = 0
    unchanged = 0
    with open(tempPath, mode='w') as repaired_file:
        repair_writer = csv.writer(repaired_file, delimiter=',',lineterminator='\n')
        with open(inPath) as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=',')
            line_count = 0
            for row in csv_reader:
                if( row[1]== "rain"):
                    if(int(row[2]) >= 20000):   #this was a bad reading that we want to skip altogether
                        skipped = skipped+1
                        continue
                    if(int(row[2])< 16270 ):    #all readings less than this value need the difference added to them
                        row[2] = str(16270+int(row[2])-14693)
                        repaired = repaired + 1
                    else:
                        unchanged = unchanged+1
                    line_count += 1
                else:
                    line_count += 1
                repair_writer.writerow(row)
           
    #remove the CR added as part of the write process above
    with open(tempPath) as f:
        with open(outPath,mode='w',newline='\n') as out:
            for line in f:
                out.write(line.strip('\r'))
 
    print(f'Processed {inPath}, lines={line_count}, unchanged={unchanged}, repaired={repaired}, skipped={skipped}')
 

for file in glob.glob("C:\\Users\\sfewi\\Documents\\Home\\emonData\\2021_rainRepair\\*.txt"):
    processFile(file, file.replace("Repair\\","Repair\\repaired\\"))