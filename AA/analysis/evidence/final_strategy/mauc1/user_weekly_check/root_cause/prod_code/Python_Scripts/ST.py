# -*- coding: utf-8 -*-
"""
Created on Wed Feb 22 15:07:54 2023

@author: manur
"""

#%%

import Python_Scripts.QuantBacktester as qd
import pandas as pd
import numpy as np
import logging
import datetime


#%%
excelReaderfObj = qd.ExcelInputReader()

#%%
def getLinearWeighing(dataPoints):
    
    numbers = range(1, dataPoints+1)
    weightNum = numbers/np.sum(numbers)
    return weightNum


#%%
def getRequiredIndex(mainDf, colName):
    
    # diffSr = mainDf[colName].diff()
    # gainSr = pd.Series(np.where(diffSr>0 , diffSr, 0), index = diffSr.index)
    # lossSr = pd.Series(np.where(diffSr<0 , -diffSr, 0), index = diffSr.index)
    # deltaSr = pd.Series(np.maximum(np.sign(diffSr),0), index = mainDf.index)
    
    # for idx in mainDf.index:
    #     mainDf.loc[idx, 'Chg_' + colName] = diffSr.loc[idx]
    #     mainDf.loc[idx,'Gain_' + colName] = gainSr.loc[idx]
    #     mainDf.loc[idx,'Loss_' + colName] = lossSr.loc[idx]
    #     mainDf.loc[idx,'Delta_' + colName] = deltaSr.loc[idx]
    
    # for idx, row in mainDf.iterrows():
    #     if idx > 0:
    #         mainDf.at[idx, colName] = mainDf.at[idx, colName]-mainDf.at[idx-1, colName]

    mainDf['Chg_' + colName] =  mainDf[colName].diff()
    mainDf['Gain_' + colName] = pd.Series(np.where(mainDf['Chg_' + colName]>0 , mainDf['Chg_' + colName], 0), index = mainDf.index)
    mainDf['Loss_' + colName] = pd.Series(np.where(mainDf['Chg_' + colName]<0 , -mainDf['Chg_' + colName], 0), index = mainDf.index)
    mainDf['Delta_' + colName] = pd.Series(np.maximum(np.sign(mainDf['Chg_' + colName]),0), index = mainDf.index)

#%%

# def setData(filePathName , sDate, code): 
#     allTradingDatesDf = excelReaderfObj.getTradingDatesDataFrame(excelFile= universeFilePath, sheetName = 'Sheet1', startDate = sDate)
#     allTradingDatesDf.reset_index(drop = True, inplace = True)
#     monthEndDatesDf = allTradingDatesDf.loc[allTradingDatesDf.groupby('YearMonth').Date.idxmax()]
#     monthEndDatesDf.sort_values(by=['Date'], inplace = True)
    
#%%

def setData(df, col):
    
    dfEndSr = df.groupby(col).tail(1)
    dfIndexValueDf = pd.DataFrame(index = dfEndSr.index)
    
    dfHighSr =  df.groupby(col)['High'].max()
    dfHighSr.index = dfIndexValueDf.index
    
    dfLowSr =  df.groupby(col)['Low'].min()
    dfLowSr.index = dfIndexValueDf.index
    
    dfVolSr =  df.groupby(col)['Volume'].sum()
    dfVolSr.index = dfIndexValueDf.index
    
    dfIndexValueDf['High'] = dfHighSr
    dfIndexValueDf['Low'] = dfLowSr
    dfIndexValueDf['Close'] = dfEndSr['Close']
    dfIndexValueDf['Volume'] = dfVolSr
    dfIndexValueDf['HML'] = dfIndexValueDf['High'] - dfIndexValueDf['Low']
    dfIndexValueDf['PClose'] = dfIndexValueDf['Close'].shift()
    
    dfIndexValueDf['HMC'] = (dfIndexValueDf['High'] - dfIndexValueDf['PClose']).abs()
    dfIndexValueDf['LMC'] = (dfIndexValueDf['Low'] - dfIndexValueDf['PClose']).abs()
    dfIndexValueDf['TR'] = (dfIndexValueDf[['HML', 'HMC','LMC']]).max(axis =1 )
    dfIndexValueDf['Ret'] =  dfIndexValueDf['Close'].pct_change()
    dfIndexValueDf['AHML'] = 0.5* dfIndexValueDf['High'] + 0.5* dfIndexValueDf['Low']
    
    return dfIndexValueDf
#%%
def getRequiredDf(scripDf,sD, scipID, universeFilePath, mondayClose, lastDate = None):
    
    if lastDate is None:
        allTradingDatesDf = excelReaderfObj.getTradingDatesDataFrame(excelFile= universeFilePath, sheetName = 'Sheet1', startDate = sD)
    else:
        allTradingDatesDf = excelReaderfObj.getTradingDatesDataFrame(excelFile= universeFilePath, sheetName = 'Sheet1', startDate = sD, lastDate = lastDate)
    allTradingDatesDf.reset_index(drop = True, inplace = True)
    monthEndDatesDf = allTradingDatesDf.loc[allTradingDatesDf.groupby('YearMonth').Date.idxmax()]
    monthEndDatesDf.sort_values(by=['Date'], inplace = True)
    
    
    tindexValueDf = scripDf[0]
    indexVolDf = scripDf[1]
    indexHighDf = scripDf[2]
    indexLowDf = scripDf[3]
    
    # tindexValueDf = excelReaderfObj.getDataFrame(excelFile = scripExcel ,sheetName = 'Close')
    # tindexValueDf.drop(tindexValueDf.columns[2:], inplace = True, axis = 1)
    # tindexValueDf.set_index('Date', inplace = True)
    # tindexValueDf.columns = ['Close']   
    
    #Close
    indexValueDf =pd.DataFrame(index = allTradingDatesDf.set_index('Date').index)
    # indexValueDf['Close'] = tindexValueDf['Close']
    
    #extra
    indexValueDf['Close'] = tindexValueDf[scipID]
    
    #Volume
    # indexVolDf = excelReaderfObj.getDataFrame(excelFile =  scripExcel  ,sheetName = 'Volume')
    # indexVolDf.set_index('Date', inplace = True)
    indexValueDf['Volume'] = indexVolDf[scipID]
    
    # print("indexValueDf duplicates:", indexValueDf.index[indexValueDf.index.duplicated()])
    # print("indexHighDf duplicates:", indexHighDf.index[indexHighDf.index.duplicated()])

    
    #High
    # indexHighDf = excelReaderfObj.getDataFrame(excelFile = scripExcel  ,sheetName = 'High')
    # indexHighDf.set_index('Date', inplace = True)
    indexValueDf['High'] = indexHighDf[scipID]
    
    #Low
    # indexLowDf = excelReaderfObj.getDataFrame(excelFile = scripExcel  ,sheetName = 'Low')
    # indexLowDf.set_index('Date', inplace = True)
    indexValueDf['Low'] = indexLowDf[scipID]

    indexValueDf.fillna(method='ffill', inplace = True)
    
    #Week Conversion
    indexValueDf['Week'] = indexValueDf.index.isocalendar().week
    
    indexValueDf['Two_Week'] = (indexValueDf['Week'] + 1) // 2
    
    #Month conversion
    indexValueDf['Month'] = indexValueDf.index.month
    # indexValueDf['Month'] = [str(x.month) + "_" + str(x.year) for x in indexValueDf.index]
        
    
    wConSr = pd.Series(index = indexValueDf.index, dtype = 'float64')
    wConSr.loc[indexValueDf.index[0]] = 1

    mConSr = pd.Series(index = indexValueDf.index, dtype = 'float64')
    mConSr.loc[indexValueDf.index[0]] = 1    
    
    twowConSr = pd.Series(index = indexValueDf.index, dtype = 'float64')
    twowConSr.loc[indexValueDf.index[0]] = 1  
    
    
    for i in indexValueDf.index[1:]:
        
        ind = indexValueDf.index.get_loc(i)
        wDiff = int(indexValueDf.iloc[ind]['Week']) - int(indexValueDf.iloc[ind-1]['Week'])
        
        mDiff = int(indexValueDf.iloc[ind]['Month']) - int(indexValueDf.iloc[ind-1]['Month'])
        
        twowDiff = int(indexValueDf.iloc[ind]['Two_Week']) - int(indexValueDf.iloc[ind-1]['Two_Week'])
        
        indWcon = wConSr.index.get_loc(i)
        
        if wDiff ==0 :
            wConSr.loc[i] = wConSr.iloc[indWcon-1]
        else:
            wConSr.loc[i] = wConSr.iloc[indWcon-1] + 1
        
        if mDiff == 0:
            mConSr.loc[i] = mConSr.iloc[indWcon-1]
        else:
            mConSr.loc[i] = mConSr.iloc[indWcon-1] + 1
            
        if twowDiff == 0:
            twowConSr.loc[i] = twowConSr.iloc[indWcon-1]
        else:
            twowConSr.loc[i] = twowConSr.iloc[indWcon-1] + 1
            
    
    
    if mondayClose:
        wConSr = wConSr.shift(1)
        
    
    indexValueDf['Week_Con'] = wConSr
    indexValueDf['Month_Con'] = mConSr
    indexValueDf['2Week_Con'] = twowConSr
    
    
    indexValueDf['HML'] = indexValueDf['High'] - indexValueDf['Low']
    indexValueDf['Ret'] = indexValueDf['Close'].pct_change()
    indexValueDf['PClose'] = indexValueDf['Close'].shift()
    
    indexValueDf['HMC'] = (indexValueDf['High'] - indexValueDf['PClose']).abs()
    indexValueDf['LMC'] = (indexValueDf['Low'] - indexValueDf['PClose']).abs()
    indexValueDf['TR'] = (indexValueDf[['HML', 'HMC','LMC']]).max(axis =1 )
    indexValueDf['AHML'] = 0.5* indexValueDf['High'] + 0.5* indexValueDf['Low']
    
    
    weekIndexValueDf = setData(indexValueDf, 'Week_Con')
    monthIndexValueDf = setData(indexValueDf, 'Month_Con')
    
    # weekEndSr = indexValueDf.groupby('Week_Con').tail(1)
    # weekIndexValueDf = pd.DataFrame(index = weekEndSr.index)
    
    # weekHighSr =  indexValueDf.groupby('Week_Con')['High'].max()
    # weekHighSr.index = weekIndexValueDf.index
    
    # weekLowSr =  indexValueDf.groupby('Week_Con')['Low'].min()
    # weekLowSr.index = weekIndexValueDf.index
    
    # weekVolSr =  indexValueDf.groupby('Week_Con')['Volume'].sum()
    # weekVolSr.index = weekIndexValueDf.index
    
    # weekIndexValueDf['High'] = weekHighSr
    # weekIndexValueDf['Low'] = weekLowSr
    # weekIndexValueDf['Close'] = weekEndSr['Close']
    # weekIndexValueDf['Volume'] = weekVolSr
    # weekIndexValueDf['HML'] = weekIndexValueDf['High'] - weekIndexValueDf['Low']
    # weekIndexValueDf['PClose'] = weekIndexValueDf['Close'].shift()
    
    # weekIndexValueDf['HMC'] = (weekIndexValueDf['High'] - weekIndexValueDf['PClose']).abs()
    # weekIndexValueDf['LMC'] = (weekIndexValueDf['Low'] - weekIndexValueDf['PClose']).abs()
    # weekIndexValueDf['TR'] = (weekIndexValueDf[['HML', 'HMC','LMC']]).max(axis =1 )
    # weekIndexValueDf['Ret'] =  weekIndexValueDf['Close'].pct_change()
    # weekIndexValueDf['AHML'] = 0.5* weekIndexValueDf['High'] + 0.5* weekIndexValueDf['Low']
    
    attrs = ['Close', 'Volume', 'High', 'Low', 'HML', 'HMC', 'LMC', 'TR']
    dfs = [indexValueDf, weekIndexValueDf, monthIndexValueDf]
    
    for df in dfs:
        for attr in attrs:
            getRequiredIndex(df,attr)
    
    # getRequiredIndex(indexValueDf, 'Close')
    # getRequiredIndex(indexValueDf, 'Volume')
    # getRequiredIndex(indexValueDf, 'High')
    # getRequiredIndex(indexValueDf, 'Low')
    # getRequiredIndex(indexValueDf, 'HML')
    # getRequiredIndex(indexValueDf, 'HMC')
    # getRequiredIndex(indexValueDf, 'LMC')
    # getRequiredIndex(indexValueDf, 'TR')
    
    # getRequiredIndex(weekIndexValueDf, 'Close')
    # getRequiredIndex(weekIndexValueDf, 'Volume')
    # getRequiredIndex(weekIndexValueDf, 'High')
    # getRequiredIndex(weekIndexValueDf, 'Low')
    # getRequiredIndex(weekIndexValueDf, 'HML')
    # getRequiredIndex(weekIndexValueDf, 'HMC')
    # getRequiredIndex(weekIndexValueDf, 'LMC')
    # getRequiredIndex(weekIndexValueDf, 'TR')

    return indexValueDf, weekIndexValueDf, monthIndexValueDf, allTradingDatesDf

#%%

def getWeightedCol(mainDf, colName):
    
    mainDf['Weight_' + colName] = mainDf['Weight'] * mainDf[colName]
    mainDf['Weight_' + 'Gain_' + colName] = mainDf['Weight'] * mainDf['Gain_' + colName]
    mainDf['Weight_' + 'Loss_' + colName] = mainDf['Weight'] * mainDf['Loss_' + colName]
    mainDf['Weight_' + 'Delta_' + colName] = mainDf['Weight'] * mainDf['Delta_' + colName]
  

#%%

def getEMA(mainDf, colName, outPutDf, rebal):
    
    ecol = mainDf['Weight_' + colName].sum()
    outPutDf.loc[rebal]['EMA_' + colName] = ecol
    
    

#%%
    
def getSupertrend(mainDf, outputDf, rebal, multiplier, rebalDates, rebalIndex, rebalStartIndex):
    

    eatr = mainDf['Weight_TR'].sum()
    ahml = mainDf.tail(1)['AHML'].values[0]
    pclose = mainDf.tail(1)['PClose'].values[0]
    close = mainDf.tail(1)['Close'].values[0]
    
    
    bub = ahml + (multiplier * eatr)
    blb = ahml - (multiplier * eatr)

    
    outputDf.loc[rebal]['BUB'] = bub
    outputDf.loc[rebal]['BLB'] = blb
    
    
    if rebalIndex == rebalStartIndex:
        fub = bub
        flb = blb
        st = fub
    
    else:
        
        pfub = outputDf.loc[rebalDates[rebalIndex - 1]]['FUB']
        pflb = outputDf.loc[rebalDates[rebalIndex - 1]]['FLB']
        pst = outputDf.loc[rebalDates[rebalIndex - 1]]['ST']


        fub = bub if (bub < pfub or pclose > pfub) else pfub
        flb = blb if (blb > pflb or pclose < pflb) else pflb
        
        if (pst == pfub and close <= fub) :
            # sell trend continue
            st = fub
        elif (pst == pfub and close > fub) :
            # sell trend to buy trend
            st = flb
        elif (pst == pflb and close >= flb) :         
            # buy continue
            st = flb
        elif (pst == pflb and close < fub) :         
            # buy to sell 
            st = fub
        else :
            
            st = 0
        
    
    outputDf.loc[rebal]['FUB'] = fub
    outputDf.loc[rebal]['FLB'] = flb
    outputDf.loc[rebal]['ST'] = st   
    
#%%
    
def getRsiBasedValues(mainDf, colName, outPutDf, rebal):
    
    rs = mainDf['Weight_Gain_' + colName ].sum() / mainDf['Weight_Loss_' + colName].sum()
    rsi = 100 - (100 / (1+ rs))
    delta = mainDf['Weight_Delta_' + colName].sum()
    outPutDf.loc[rebal]['RSI_' + colName] = rsi / 100
    outPutDf.loc[rebal]['CSI_' + colName] = delta


#%%

def checkPrevRun(allRebalDf, tmpallRebalDf, lastDate, scrip):
    checkColumn = allRebalDf.columns[~allRebalDf.columns.isin(['RSI_Volume'])]
    # print(checkColumn)
    runSuccess = True 
    allRebalSr = allRebalDf.loc[lastDate][allRebalDf.columns[:-1]]
    tmpAllRebalSr = tmpallRebalDf.loc[lastDate][tmpallRebalDf.columns[:-1]]
    diffSr = allRebalSr - tmpAllRebalSr
    diffBinSr = pd.Series(np.where(diffSr >0.001, 1,0), index = diffSr.index)
    diffBinSum = diffBinSr.sum()
    
    
    if diffBinSum != 0:
        print('---------------------------------------'+ 
              '----------------------------------------'+
              '========================================' + scrip[2] +
              '---------------------------------------check for the data mismatch between two runs for date '+ str(lastDate) +
                    '----------------------------------------'+
                    '========================================')
        runSuccess = False
        
    else:
        print('---------------------------------------' + scrip[2] + '-----Run successful for -------' + str(lastDate))
    
    return runSuccess
#%%
def run(scrip, freq , mul, newRun,outputDCheckFilePath, outputWCheckFilePath, outputMCheckFilePath, existingFilePath, universeFilePath , daysToConsider = None, mondayClose = False, lastDate = None):
    
    # print(scrip)
    indexValueDf, weekIndexValueDf, monthIndexValueDf,allTradingDatesDf = getRequiredDf(scrip[0],scrip[1], scrip[2], universeFilePath, mondayClose, lastDate  = lastDate)
    
    indexValueDf.to_excel(outputDCheckFilePath)
    weekIndexValueDf.to_excel(outputWCheckFilePath)
    monthIndexValueDf.to_excel(outputMCheckFilePath)
    
    if daysToConsider is None:
        if freq == 'D':
            rebalDates = indexValueDf.index
            daysToConsider = 14
            rebalStartIndex = 14
        elif freq == 'W':    
            rebalDates = weekIndexValueDf.index
            daysToConsider = 5
            rebalStartIndex = 5
        elif freq == 'M':
            rebalDates = monthIndexValueDf.index
            daysToConsider = 5
            rebalStartIndex = 5
    else:
        if freq == 'D':
            rebalDates = indexValueDf.index
            daysToConsider = daysToConsider
            rebalStartIndex = daysToConsider
        else:    
            rebalDates = weekIndexValueDf.index
            daysToConsider = daysToConsider
            rebalStartIndex = daysToConsider
    
    weightSr = getLinearWeighing(daysToConsider)
    allRebalDf = pd.DataFrame(index = rebalDates, columns= ['RSI_Close', 'RSI_High', 'RSI_Low', 'RSI_HML', 'RSI_Volume', 'RSI_TR', 'RSI_HMC', 
                                                         'RSI_LMC', 'EMA_Close', 'EMA_TR', 'ST',
                                                         'Index', 'FUB', 'FLB', 'BUB',
                                                         'BLB', 'WGH_SRT'])
    
    
    if newRun:
        rebalIndex = rebalStartIndex
    else:
    
        tmpallRebalDf = excelReaderfObj.getDataFrame(existingFilePath, rowsToSkip=0, columnsToSkip=0)
        tmpallRebalDf.set_index('Date',inplace = True)
        # print(allRebalDf.tail())
        # print(tmpallRebalDf.tail())
        allRebalDf.loc[tmpallRebalDf.index] = tmpallRebalDf.loc[tmpallRebalDf.index]
        
        
        
        lastDate = tmpallRebalDf.index[-1]
        rebalIndex = allRebalDf.index.get_loc(lastDate) - 1
     
    # logger.info('Start')    
    for rebal in rebalDates[rebalIndex:]:
        
        rebalDateStr = pd.to_datetime(rebal).strftime('%Y-%m-%d')
        print(rebalDateStr)
        
        sliceObj = qd.SliceDataFrame()
        
        if freq == 'D':
            subIndexValueDf = sliceObj.getLengthSlice('EndIncl', endElement= rebal, days= daysToConsider, dfToSlice= indexValueDf)
        elif freq == 'W':
            subIndexValueDf = sliceObj.getLengthSlice('EndIncl', endElement= rebal, days= daysToConsider, dfToSlice= weekIndexValueDf)
        elif freq == 'M':
            subIndexValueDf = sliceObj.getLengthSlice('EndIncl', endElement= rebal, days= daysToConsider, dfToSlice= monthIndexValueDf)
        
        subIndexValueDf['Weight'] = pd.Series(weightSr, index = subIndexValueDf.index)
        
        getWeightedCol(subIndexValueDf, 'Close')
        getWeightedCol(subIndexValueDf, 'Volume')
        getWeightedCol(subIndexValueDf, 'High')
        getWeightedCol(subIndexValueDf, 'Low')
        getWeightedCol(subIndexValueDf, 'HML')
        getWeightedCol(subIndexValueDf, 'HMC')
        getWeightedCol(subIndexValueDf, 'LMC')
        getWeightedCol(subIndexValueDf, 'TR')
        # logger.info('WeightCol')  
        
        getEMA(subIndexValueDf,'Close', allRebalDf, rebal)
        getEMA(subIndexValueDf,'TR', allRebalDf, rebal)
        # logger.info('GetEMA')  
        
        getRsiBasedValues(subIndexValueDf,'Close', allRebalDf, rebal)
        getRsiBasedValues(subIndexValueDf,'Volume', allRebalDf, rebal)
        getRsiBasedValues(subIndexValueDf,'High', allRebalDf, rebal)
        getRsiBasedValues(subIndexValueDf,'Low', allRebalDf, rebal)
        getRsiBasedValues(subIndexValueDf,'HML', allRebalDf, rebal)
        getRsiBasedValues(subIndexValueDf,'HMC', allRebalDf, rebal)
        getRsiBasedValues(subIndexValueDf,'LMC', allRebalDf, rebal)
        getRsiBasedValues(subIndexValueDf,'TR', allRebalDf, rebal)
        
        # logger.info('RSI') 
        
        getSupertrend(subIndexValueDf, allRebalDf, rebal, mul, rebalDates, rebalIndex, rebalStartIndex)
        
        # logger.info('ST')
        
        dailyRebalIndex = allTradingDatesDf.set_index('Date').index.get_loc(rebal)
        if dailyRebalIndex < allTradingDatesDf.shape[0] -1:
            weightStartDate = allTradingDatesDf.set_index('Date').iloc[dailyRebalIndex + 1].name
        else:
            weightStartDate = ""
        allRebalDf.loc[rebal]['WGH_SRT'] = weightStartDate    
        
        if freq == 'D':
            allRebalDf.loc[rebal]['Index'] = indexValueDf.loc[rebal]['Close'] 
        elif freq == 'W':
            allRebalDf.loc[rebal]['Index'] = weekIndexValueDf.loc[rebal]['Close'] 
        elif freq == 'M':
            allRebalDf.loc[rebal]['Index'] = monthIndexValueDf.loc[rebal]['Close'] 
            
        rebalIndex += 1
        
        # logger.info(rebal)
    if not newRun:
        runSuccess = checkPrevRun(allRebalDf, tmpallRebalDf, lastDate, scrip)
    else:
        runSuccess = True
    
        
        
    return allRebalDf, runSuccess

#%%
def runRSI(tindexValueDf, indexVolDf, indexHighDf,indexLowDf,sd,ric,freq, universeFilePath, daysToConsider = None, rebalStartIndex =5):
    # tindexValueDf, indexVolDf, indexHighDf,indexLowDf, sD, scipID, universeFilePath, mondayClose
    indexValueDf, weekIndexValueDf, allTradingDatesDf = getRequiredDf(tindexValueDf, indexVolDf, indexHighDf,indexLowDf,sd, ric, universeFilePath, False)
    
    # indexValueDf.to_excel(outputDCheckFilePath)
    # weekIndexValueDf.to_excel(outputWCheckFilePath)
    
    if daysToConsider is None:
    
        if freq == 'D':
            rebalDates = indexValueDf.index
            daysToConsider = 14
            # rebalStartIndex = 14
        else:    
            rebalDates = weekIndexValueDf.index
            daysToConsider = 5
            # rebalStartIndex = 5
    else:
        if freq == 'D':
            rebalDates = indexValueDf.index
            daysToConsider = daysToConsider
            # rebalStartIndex = 14
        else:    
            rebalDates = weekIndexValueDf.index
            daysToConsider = daysToConsider
        
    
    weightSr = getLinearWeighing(daysToConsider)
    allRebalDf = pd.DataFrame(index = rebalDates, columns= ['RSI_Close', 'RSI_High', 'RSI_Low', 'RSI_HML', 'RSI_Volume', 'RSI_TR', 'RSI_HMC', 
                                                         'RSI_LMC', 'EMA_Close', 'EMA_TR', 'ST',
                                                         'Index', 'Resistance','Support', 'FUB', 'FLB', 'BUB',
                                                         'BLB', 'WGH_SRT'])
    
    # print(weekIndexValueDf)
    
    # print(newRun)
    rebalIndex = rebalStartIndex
    # if newRun:
    #     rebalIndex = rebalStartIndex
    # else:
    #     tmpallRebalDf = excelReaderfObj.getDataFrame(existingFilePath, rowsToSkip=0, columnsToSkip=0)
    #     tmpallRebalDf.set_index('Date',inplace = True)
    #     allRebalDf.loc[tmpallRebalDf.index] = tmpallRebalDf.loc[tmpallRebalDf.index]
        
    #     lastDate = tmpallRebalDf.index[-1]
    #     rebalIndex = allRebalDf.index.get_loc(lastDate) - 1
    
    # print(rebalDates)    
        
    for rebal in rebalDates[rebalIndex:]:
        
        rebalDateStr = pd.to_datetime(rebal).strftime('%Y-%m-%d')
        print(rebalDateStr)
        
        sliceObj = qd.SliceDataFrame()
        
        if freq == 'D':
            subIndexValueDf = sliceObj.getLengthSlice('EndIncl', endElement= rebal, days= daysToConsider, dfToSlice= indexValueDf)
        else:
            subIndexValueDf = sliceObj.getLengthSlice('EndIncl', endElement= rebal, days= daysToConsider, dfToSlice= weekIndexValueDf)
        
        subIndexValueDf['Weight'] = pd.Series(weightSr, index = subIndexValueDf.index)
        
        getWeightedCol(subIndexValueDf, 'Close')
        # getWeightedCol(subIndexValueDf, 'Volume')
        getWeightedCol(subIndexValueDf, 'High')
        getWeightedCol(subIndexValueDf, 'Low')
        # getWeightedCol(subIndexValueDf, 'HML')
        # getWeightedCol(subIndexValueDf, 'HMC')
        # getWeightedCol(subIndexValueDf, 'LMC')
        # getWeightedCol(subIndexValueDf, 'TR')
        
        # getEMA(subIndexValueDf,'Close', allRebalDf, rebal)
        # getEMA(subIndexValueDf,'TR', allRebalDf, rebal)
        
        getRsiBasedValues(subIndexValueDf,'Close', allRebalDf, rebal)
        # getRsiBasedValues(subIndexValueDf,'Volume', allRebalDf, rebal)
        getRsiBasedValues(subIndexValueDf,'High', allRebalDf, rebal)
        getRsiBasedValues(subIndexValueDf,'Low', allRebalDf, rebal)
        # getRsiBasedValues(subIndexValueDf,'HML', allRebalDf, rebal)
        # getRsiBasedValues(subIndexValueDf,'HMC', allRebalDf, rebal)
        # getRsiBasedValues(subIndexValueDf,'LMC', allRebalDf, rebal)
        # getRsiBasedValues(subIndexValueDf,'TR', allRebalDf, rebal)
    
    
    return allRebalDf
