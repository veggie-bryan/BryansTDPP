import sys
import clr
from System.Collections.Generic import List
import pandas as pd
import matplotlib.pyplot as plt

import time


### allow python to work with c++ NET objects and import OpenTD NET objects ##############################################################################

sys.path.append(r"C:\Windows\Microsoft.NET\assembly\GAC_MSIL\OpenTDv242\v4.0_24.2.0.0__65e6d95ed5c2e178")
sys.path.append(r"C:\Windows\Microsoft.NET\assembly\GAC_64\OpenTDv242.Results\v4.0_24.2.0.0__b62f614be6a1e14a")
sys.path.append(r"C:\Windows\Microsoft.NET\assembly\GAC_MSIL\OpenTDv242.CoSolver\v4.0_24.2.0.0__65e6d95ed5c2e178")
clr.AddReference("OpenTDv242")
clr.AddReference("OpenTDv242.Results")
clr.AddReference("OpenTDv242.CoSolver")
from OpenTDv242 import *
from OpenTDv242 import Results
from OpenTDv242.Results import Dataset
from OpenTDv242 import PostProcessing
from System import *


### sav/dwg file inputs #######################################################################################################################################

dwg = r'path_to_dwg.dwg'
sav = r'path_to_sav.sav'
td = ThermalDesktop()
td.Connect(dwg)

### main data structure ###################################################################################################################################

netSubmodels = Dataset.SaveFile(sav).GetThermalSubmodels()  
submodels = []
for i in range(len(netSubmodels)):
    submodels.append(netSubmodels[i])


Data = {i : [] for i in submodels}


netTime = Dataset.SaveFile(sav).GetTimes()
time_list = list(netTime)


startTime = time.time()

for i in submodels:
    netNodes = Dataset.SaveFile(sav).GetNodeIds(i)
    Data[i] = {j : [] for j in netNodes}
    for k in netNodes:
        Data[i][k] = {'time':[], 'temp':[]}
        Data[i][k]['time'].extend(time_list)

        
        tempTemps = Dataset.SaveFile(sav).GetData(i + '.T' + str(k)).GetValues(UnitsData('C'))
        for t in range(len(tempTemps)):
            Data[i][k]['temp'].extend(list(tempTemps[t]))

        plt.plot(Data[i][k]['time'], Data[i][k]['temp'])
        plt.xlabel('time')
        plt.ylabel('temp °C')
        plt.show()
        
        #print(Data[i][k])
        print('loading...', i, k)

endTime = time.time()
print(endTime - startTime, " seconds")


for i in submodels:
    for k in netNodes:
        plt.plot(Data[i][k]['time'], Data[i][k]['temp'])
plt.show()


print(Data)


"""
TODO : Future Features 

>> Generate an excel sheet with submodel and submodel nodes before extracting data for easy user verification.
>> Allow the user to filter uncessary nodes and add operational limits. (to set off alarms)
>> Add heater register data reading to generate heater duty cycles and period times.
>> Use data structure to find max and min temperature nodes of each submodel (to make post processing easier)
>> Increase effeciency of the script, it currently does the job... but slow.

POC: bryanaserrano3@gmail.com

"""