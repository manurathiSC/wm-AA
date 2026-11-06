#!/usr/bin/env python
# coding: utf-8

# In[1]:


import pandas as pd
import numpy as np
import xlsxwriter
import math
import eikon as ek
# from openpyxl import load_workbook
# from IPython.core.debugger import Tracer
from sklearn import covariance
import scipy.optimize as sco
import scipy.stats as stats
# from openpyxl import load_workbook
import pickle
# from influxdb import InfluxDBClient
import datetime
from pandas.tseries.offsets import DateOffset

import time
# import pyfolio as pf

import logging

import Python_Scripts.ProspectTheory as pt

#%%
import warnings
warnings.filterwarnings("ignore")

#%%

logging.basicConfig(filename='windmillcheck_ALL.log',
                    filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.INFO)
logger = logging.getLogger('windmillcheck_ALL')
logger.setLevel(logging.INFO)

# fh = logging.FileHandler(r'C:\Users\manur\Google Drive\Manu\Windmill_ScidCheck\windmillcheck_ALL_2.log')
# fh.setLevel(logging.INFO)
# fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
# logger.addHandler(fh)

import os as _os
_log_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'windmillcheck_ALL_2.log')
fh = logging.FileHandler(_log_path)
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)


# from kiteconnect import KiteConnect
# In[68]:


# ****** No multi Index change accordingly
class ExcelInputReader:
#    import pandas as pd
#    import numpy as np

    def __init__(self, excelFile= None):
        self.excelFile = excelFile

    def getDataFrame(self, excelFile = None , sheetName = 'Sheet1', rowsToSkip =2, columnsToSkip = 1):
        if excelFile is None:
            excelFile = self.excelFile
        dataFrameToReturn = pd.read_excel(excelFile, sheetName, skiprows = rowsToSkip)
        dataFrameToReturn.drop(dataFrameToReturn.columns[0: columnsToSkip], axis =1, inplace = True)
        dataFrameToReturn['Date'] = pd.to_datetime(dataFrameToReturn['Date'])
        # dataFrameToReturn.set_index('Date', inplace = True)
        return dataFrameToReturn

    def getDataFrameWithoutDate(self, excelFile = None , sheetName = 'Sheet1', rowsToSkip =0, columnsToSkip = 0):

        if excelFile is None:
            excelFile = self.excelFile

        dataFrameToReturn = pd.read_excel(excelFile, sheetName, skiprows = rowsToSkip)
        dataFrameToReturn.drop(dataFrameToReturn.columns[0: columnsToSkip], axis =1, inplace = True)

        return dataFrameToReturn



    def getOustandingShareDataFrame(self, excelFile = None , sheetName = 'OutstandingShares', rowsToSkip =2, columnsToSkip = 1):
        if excelFile is None:
            excelFile = self.excelFile

        outstandingShares = pd.read_excel(excelFile, sheetName, skiprows = rowsToSkip)
        outstandingShares.drop(outstandingShares.columns[0:columnsToSkip], axis =1, inplace = True)
        outstandingShares['Date'] = pd.to_datetime(outstandingShares['Date'])
        outstandingShares['YearMonth'] = outstandingShares['Date'].dt.year.map(str) + outstandingShares['Date'].dt.month.map(str)
        outstandingShares.drop(columns=['Date'], inplace= True)
        return outstandingShares

    def getDividendDataFrame(self, stockuniverse, excelFile = None, sheetName = 'Dividend', rowsToSkip =2, columnsToSkip = 1, valueToRetrive = 'Adjusted Net Dividend Amount', monthLag = 0, updateDates = False, tradingDatesDf = None):
        if excelFile is None:
            excelFile = self.excelFile

        dividends = pd.read_excel(excelFile, sheetName, skiprows = rowsToSkip)
        dividendDf = dividends.pivot_table(index = 'Dividend Ex Date', columns= 'Stocks', values=valueToRetrive, aggfunc= np.sum)
        dividendsAllStocks = pd.DataFrame(index = dividendDf.index , columns= stockuniverse)
        dividendsAllStocks[dividendDf.columns] = dividendDf[dividendDf.columns]

        dividendsAllStocks.index = pd.DatetimeIndex(dividendsAllStocks.index)

#        logger.info(dividendsAllStocks.index)

        if monthLag != 0 :
            dividendsAllStocks.index = dividendsAllStocks.index + pd.DateOffset(months = monthLag)


        dividendsAllStocks.index.name = 'Date'

        if updateDates:
            self.updateRebalanceTradingDates(dividendsAllStocks, tradingDatesDf, methodTOFill= 'bfill')


        dividendsAllStocks.reset_index(inplace= True)

        return dividendsAllStocks

#
    def getDividendDataFrameFiscalYear(self, excelFile = None, sheetName = 'Dividend', rowsToSkip = 2, columnsToSkip = 0, month = 4, day =1):
        if excelFile is None:
            excelFile = self.excelFile

        dividendDf = pd.read_excel(excelFile, sheetName, skiprows = rowsToSkip)
        dividendDf.drop(dividendDf.columns[0: columnsToSkip], axis =1, inplace = True)

        dividendDf['Date'] = pd.to_datetime(dividendDf['Year']*10000 + month*100 + day, format='%Y%m%d')
        dividendDf.drop(columns=['Year'], inplace= True)

        return dividendDf

    def getFundamentalDataOnReportingDate(self, excelFile = None, reportingDateSheetName = 'ReportingDates', fundamentalDataSheetName = 'Dividend', rowsToSkip = 0, columnsToSkip = 0, fillNaValue = None, fundamentalDataName = None, monthsLag = 0):

        if excelFile is None:
            excelFile = self.excelFile


        reportDateDf = self.getDataFrameWithoutDate(excelFile = excelFile ,sheetName = reportingDateSheetName, rowsToSkip = 0, columnsToSkip = 0)
        dividendDf = self.getDataFrameWithoutDate(excelFile = excelFile, sheetName= fundamentalDataSheetName, rowsToSkip = 0, columnsToSkip= 0)


        reversePiovtReportDateDf = reportDateDf.melt(id_vars= 'Date')
        reversePivotDividendDf = dividendDf.melt(id_vars = 'Date')

        if fundamentalDataName is None:
            fundamentalDataName = fundamentalDataSheetName

        if fillNaValue is not None:
            reversePiovtReportDateDf[fundamentalDataName] = reversePivotDividendDf['value'].fillna(fillNaValue)
        reversePiovtReportDateDf['value'] = pd.to_datetime(reversePiovtReportDateDf['value'])

        reversePiovtReportDateDf.columns = ['DataFreq','Stocks', 'Date', fundamentalDataName]

        if monthsLag != 0:

            reversePiovtReportDateDf['Date'] = reversePiovtReportDateDf['Date'] +pd.DateOffset(months = monthsLag)



        return reversePiovtReportDateDf



    def getTradingDatesDataFrame(self, startYM = None, excelFile = None, sheetName = 'Sheet1', rowsToSkip =2, lastDate = None, startDate = None):

        if excelFile is None:
            excelFile = self.excelFile

        tradingDates = pd.read_excel(excelFile, sheetName, skiprows= rowsToSkip)
        # logger.info(tradingDates)
        tradingDates.drop(tradingDates.columns[0:1], axis = 1, inplace = True)
        tradingDates.drop(tradingDates.columns[1:], axis = 1, inplace = True)
#         tradingDatesDf.drop(tradingDatesDf.columns[1:], axis =1, inplace = True)
        tradingDates['Date'] = pd.to_datetime(tradingDates['Date'])
        tradingDates['Month'] = tradingDates['Date'].dt.month
        tradingDates['Year'] = tradingDates['Date'].dt.year
        tradingDates['YearMonth'] = tradingDates['Year'].map(str) + tradingDates['Month'].map(str)
        # getting the data for year month
        if startDate is None:

            if startYM is not None:
                locationYM = tradingDates['YearMonth'][tradingDates['YearMonth'] == startYM]
                startIndex = int(locationYM.index[0]) -1
            else:
                startIndex = 0
        else:
            
            locationYM = tradingDates['Date'][tradingDates['Date'] == startDate]
            startIndex = int(locationYM.index[0])

        if lastDate is not None:

            endLocation = tradingDates['Date'][tradingDates['Date'] == lastDate]
            endIndex = int(endLocation.index[0]) + 1
            subTradingDates = tradingDates[startIndex:endIndex]

        else:
            subTradingDates = tradingDates[startIndex:]

        return subTradingDates


    # format 1 : stocks, weight( sheet 1) : output : write uninverse, get Stocks and weights   only for 1 column please insert NULL / Nan in the excel file
    def getFormat1info(self, excelFile = None , tillColumn = None,sheetName = 'Sheet1', rowsToSkip =0, columnsToSkip = 0, stockOnlyBool = False, ricChangeDict = None, formType = 1):

        stocksList = []

        if excelFile is None:
            excelFile = self.excelFile

        allStocksDf = pd.read_excel(excelFile, sheetName, skiprows = rowsToSkip)
#        logger.info(type(allStocksDf))
#        logger.info(allStocksDf)
#        allStocksDf.reset_index(inplace = True)
        allStocksDf.drop(allStocksDf.columns[0: columnsToSkip], axis =1 , inplace = True)

        # logger.info(allStocksDf)
        
        if tillColumn is not None:
            allStocksDf.drop(allStocksDf.columns[tillColumn:], axis =1 , inplace = True)

        selectedStocksDf = pd.DataFrame(index= allStocksDf.columns)


        weightsDf = pd.DataFrame(index = allStocksDf.columns)
#        rebalanceDate = allStocksDf.columns

        # for each column in the sheet
        for col in allStocksDf.columns:
            columnValue = allStocksDf[col]
#            logger.info(columnValue.values.tolist())

            if not stockOnlyBool:
                naLoc = columnValue.values.tolist().index(np.nan)
                onlyStocks = columnValue.iloc[:naLoc]
#                logger.info(naLoc)
            else:
                naLoc = columnValue.last_valid_index()
                onlyStocks = columnValue.iloc[:naLoc+1]

#            display(naLoc)
            # stock till first Nan

#            logger.info(onlyStocks)
            if ricChangeDict is not None:
                onlyStocks.replace(ricChangeDict, inplace = True)

            if not stockOnlyBool:

                weightsCol = columnValue.iloc[naLoc:]
                # display(weightsCol)

                firstNonValue = weightsCol.first_valid_index()
                # display(firstNonValue)
                
                #^M
                # logger.info(weightsCol[firstNonValue:])
                
                if formType == 1:
                    lastNonValue = weightsCol.last_valid_index()
                    onlyWeights = weightsCol.loc[firstNonValue:lastNonValue]
                else:
                    lastNonValue = weightsCol.loc[firstNonValue:].values.tolist().index(np.nan)
                    # lastNonValue = weightsCol.last_valid_index()
                    # display(lastNonValue)
                    #^M
                    # onlyWeights = weightsCol.loc[firstNonValue:lastNonValue]
                    onlyWeights = weightsCol.loc[firstNonValue:lastNonValue+firstNonValue-1]
    #            onlyWeights = onlyWeightsStart.iloc[:onlyWeightsStart.values.tolist().index(np.nan)]
    #            display(onlyWeights)
                onlyWeights.index = onlyStocks

            for stocks in onlyStocks:
                # new column for new stock
                if not stocks in stocksList:
                    stocksList.append(stocks)
                    selectedStocksDf[stocks] = 0
                    if not stockOnlyBool:
                        weightsDf[stocks] = 0
            selectedStocksDf.loc[col][onlyStocks] = 1
            # logger.info(selectedStocksDf)
            # logger.info(selectedStocksDf.index)
            selectedStocksDf.index = pd.to_datetime(selectedStocksDf.index)
            selectedStocksDf.index.name = 'Date'
#            logger.info(onlyWeights)
#            logger.info(weightsDf)
            if not stockOnlyBool:
                weightsDf.update(pd.DataFrame(onlyWeights).T)
                weightsDf.index = pd.to_datetime(weightsDf.index)
                weightsDf.index.name = 'Date'
        return selectedStocksDf, weightsDf ,stocksList

    def writeStocksListInFile(self, stocksList, outputFile):

        workBook = xlsxwriter.Workbook(outputFile)
        workSheet = workBook.add_worksheet("ClosingPrice")
        row = col = 2
        for stock in stocksList:
            workSheet.write(row, col, stock)
            col += 1
        workBook.close()


    def updateRebalanceTradingDates(self, selectedStocksDf, tradingDatesDf, methodTOFill= 'ffill'):

        tmpTradingDatesDf = tradingDatesDf.set_index(['Date'])
        updatedDates = []
        for rebalDate in selectedStocksDf.index:
#            logger.info(rebalDate)
            dateIndex = tmpTradingDatesDf.index.get_loc(rebalDate, method = methodTOFill)
            updatedDates.append(tmpTradingDatesDf.index[dateIndex])
        selectedStocksDf['UDate'] = updatedDates
        selectedStocksDf.reset_index(inplace = True)
        selectedStocksDf.set_index(['UDate'], inplace = True)
        selectedStocksDf.drop(['Date'], axis =1, inplace = True)
        selectedStocksDf.index.name = 'Date'
        return selectedStocksDf

    def updateRics(self, selectedStocksDf, ricChangeDict):

        selectedStocksDf.rename(columns= ricChangeDict, inplace= True)
        return selectedStocksDf


    def getPivotTableOfDf(self, dfToPivot, orderdColumnNames, valueName, index = 'Date', columns= 'Stocks'):

        pivotedDf = dfToPivot.pivot_table(index = index, columns= columns, values= valueName, dropna= False)
        pivotFinalDf = pd.DataFrame(index = pivotedDf.index, columns = orderdColumnNames)
        pivotFinalDf[pivotedDf.columns] = pivotedDf[pivotedDf.columns]
        return pivotFinalDf





class EikonApiReader:


    def __init__(self, stocksList, startYear=None, endYear=None, fundaDataDict = None):
        self.stocksList = stocksList
        if startYear and endYear != None:
            self.yearsList = self.makeYearList(startYear, endYear)
            self.fDf = pd.DataFrame(index = self.stocksList, columns = self.yearsList)
        self.fundaDataDict = fundaDataDict
        

    def makeYearList(self,startyear, endYear):
        yearList = []
        year = startyear
        while year <= endYear:
            yearList.append('FY' + str(year))
            year = year + 1
        return yearList


    def setEikonConnection(self, user = 'A'):

        if user == 'A':
            ek.set_app_key('3772505fa02649eaa4eedf603af4dc5f6ca4f2ac')
        else:
            ek.set_app_key('abee6954a9c74216a5329b0bf307f5d3238128ea')

    def getFundamentalData(self, fundamentalDataItem, params, i = 0):

        # for fYear in self.yearsList:
        while i < len(self.yearsList):            
            
            fYear  = self.yearsList[i]
            params.update({'Period': fYear})
            fDataFields = ek.TR_Field(fundamentalDataItem, params)       
            
            try:    
                tmpDf = ek.get_data(self.stocksList, fDataFields)[0]
                tmpDf.set_index(['Instrument'], inplace = True)
#                logger.info(tmpDf.head())
                self.fDf[fYear] = tmpDf[tmpDf.columns[0]]
                logger.info(fYear)
#               logger.info(fDf.head())
            except ek.EikonError:
                logger.info("--- Got ERROR in " + fYear)
                time.sleep(15)
                self.getFundamentalData(fundamentalDataItem,params, i)
            i += 1

        return self.fDf


    def getTimeSeriesData(self, dataItem, params):

        fDataFields = ek.TR_Field(dataItem, params)
        tmpDf = ek.get_data(self.stocksList, fDataFields)[0]
        tmpDf.set_index(['Instrument'], inplace = True)

        return tmpDf



"""
class KiteApiReader:

    def __init__(self, apiKey = "", accessToken = ""):
        kite = KiteConnect(api_key = apiKey, access_token= accessToken)
        self.kiteObj = kite


    def getInstruments(self, exchg = "NSE"):
        instruments = self.kiteObj.instruments(exchange= exchg)
        return instruments


    def getNseSymbolInstrumentTokenMapping(self, exchg = "NSE"):

        instrumentDf = pd.DataFrame(columns = ['SYMBOL', 'INST_TOKEN'])

        instrumentDictList = self.getInstruments(exchg)

        symbolList = []
        instToken = []

        for instrumentDict in instrumentDictList:

            symbolList.append(instrumentDict.get('tradingsymbol'))
            instToken.append(instrumentDict.get('instrument_token'))

        instrumentDf['SYMBOL'] = symbolList
        instrumentDf['INST_TOKEN'] = instToken
        return instrumentDf


    def getCandleDfDict(self, nseSymbols, startDate, endDate, subTradingDates, frequency = 'day', dataFields = ['close']):

        instrumentDf =  self.getNseSymbolInstrumentTokenMapping()
        instrumentDf.set_index('SYMBOL', inplace = True)

#        instrumentTokens = instrumentDf.loc[nseSymbols]

#        allTradingDates['Date'][allTradingDates['Date'] == startDate]

        dfDict  = {}

        for dataField in dataFields:

            tmpDf = pd.DataFrame(index = pd.DatetimeIndex(subTradingDates), columns = nseSymbols)
            dfDict.update({dataField : tmpDf})


        # priceDf = pd.DataFrame(index = pd.DatetimeIndex(subTradingDates), columns = nseSymbols)

        for nseSymbol in nseSymbols:



            try :
                instrumentToken = instrumentDf.loc[nseSymbol]['INST_TOKEN']
                priceDictList = self.kiteObj.historical_data(instrumentToken, startDate, endDate, frequency)

                for priceDict in priceDictList:

                    if frequency == 'day':
                        date = pd.Timestamp(priceDict.get('date').date())
                    else:
                        date = pd.Timestamp(priceDict.get('date'))

                # logger.info(date)

                    for dataField in dataFields:

                        dataValue = priceDict.get(dataField)
                        dfDict.get(dataField).loc[date][nseSymbol] = dataValue



            except KeyError as error:

                logger.info('Key Error for ' + nseSymbol)

                pass


                # closePrice = priceDict.get('close')

                # # logger.info(date)
                # # logger.info(closePrice)

                # priceDf.loc[date][nseSymbol] = closePrice

        return dfDict

"""
#%% [Only for Prod Connection]
"""
class DbReader:

    def __init__(self, host = 'influxdb-replica.prod.tickertape.in', port = 8086, userName = None, password = None, dbName = 'interday'):

        client = InfluxDBClient(host, port, userName, password, dbName)
        self.clientObj = client
        self.dbNameObj = dbName

    def getDateList(self, sDate, eDate):

        if self.dbNameObj == "interday":
            subTradingDatesList = []
            delta = eDate - sDate
            subTradingDatesList.append(sDate)

            for ticDelta in range(1, delta.days +1):

                tmpDate = sDate + datetime.timedelta(days = ticDelta)
                # tmpDate = sDate + datetime.timedelta(minutes = ticDelta)
                subTradingDatesList.append(tmpDate)

            return subTradingDatesList

    def getQString(self, stocksList, ricType):
        allLst = ''
        allStocks = []
        index = 0
        for stock in stocksList:
            tempStock = "sid=" + "'" + stock.replace('.NS', '') + "'"
            if index == 0:
                allLst = allLst + tempStock
            allLst = allLst  + ' or ' + tempStock
            allStocks.append(stock.replace('.NS', ''))
            index = index + 1
            # logger.info(stock)
        return [allLst, allStocks]


    def getTimeSeriesData(self, sDate, eDate, stocksList, ricType, ohlc= 'close'):


        subTradingDatesList = self.getDateList(pd.Timestamp(sDate), pd.Timestamp(eDate))
        qStringAttr = self.getQString(stocksList, ricType)

        outputDf = pd.DataFrame(index = subTradingDatesList, columns = stocksList)

        qString = "select * from quotes where " + qStringAttr[0] + " and time >= " + "'%s'" %  sDate  + " and time <= " +  "'%s'" %  eDate

        logger.info(qString)
        result = self.clientObj.query(qString)
        point = result.get_points()
        index = 0
        for row in point:
            date = pd.to_datetime(row.get('time'))
            scid = row.get('sid')
            closePrice = row.get(ohlc)
            # logger.info(closePrice)
            outputDf.loc[date][scid+".NS"] = closePrice
            index = index +1

        return outputDf

"""

#%%
        
class TechnicalIndicators:
    
    def __init__(self):
        pass
    
    def rsi(self, indexValues):
        
        changeIndex = indexValues - indexValues.shift(1)
        gainIndex = pd.Series(np.where(changeIndex>0 , changeIndex, 0), index = changeIndex.index)
        lossIndex = pd.Series(np.where(changeIndex<0 , -changeIndex, 0), index = changeIndex.index)
        rsIndex = gainIndex.div(lossIndex)




#%%

class UtilsQB:

    def __init__(self):
        pass

    
    def getZ(self, inputDf, desiredColumns, window):
        for col in desiredColumns:  
            tmpWindowCol = inputDf[col].rolling(window)  
            inputDf['Z_' + col] = (inputDf[col] - tmpWindowCol.mean())/ tmpWindowCol.std()
            
        return inputDf
    
#    def countConsecutiveNA(self, dataFrame):
#        pass
##
#    def checkClosingPriceAvailibility(self, closePriceDf, selectedStocksDf):
#
#        selectedStocksPriceDf = pd.DataFrame()

    
    def setDatFrame(self, allTradingDatesDf, ricDict):
        excelReaderfObj = ExcelInputReader()
        mergeObj = Merger()
        openMergedDf = pd.DataFrame(index = allTradingDatesDf.Date)
        highMergedDf = pd.DataFrame(index = allTradingDatesDf.Date)
        closeMergedDf = pd.DataFrame(index = allTradingDatesDf.Date)
        lowMergedDf = pd.DataFrame(index = allTradingDatesDf.Date)
        
        for ric in ricDict:
            filePath = ricDict.get(ric)
            OpenDf = excelReaderfObj.getDataFrame(filePath, sheetName = 'Open')
            OpenDf = OpenDf[['Date',ric]]
            OpenDf.set_index('Date', inplace=True)
            tmpOpenMergedDf = mergeObj.getMergedBymethodDf(allTradingDatesDf, OpenDf)
            
            highDf = excelReaderfObj.getDataFrame(filePath, sheetName = 'High')
            highDf = highDf[['Date',ric]]
            highDf.set_index('Date', inplace=True)
            tmpHighMergedDf = mergeObj.getMergedBymethodDf(allTradingDatesDf, highDf)
            
            closeDf = excelReaderfObj.getDataFrame(filePath, sheetName = 'Close')
            closeDf = closeDf[['Date',ric]]
            closeDf.set_index('Date', inplace=True)
            tmpCloseMergedDf = mergeObj.getMergedBymethodDf(allTradingDatesDf, closeDf)
            
            lowDf = excelReaderfObj.getDataFrame(filePath, sheetName = 'Low')
            lowDf = lowDf[['Date',ric]]
            lowDf.set_index('Date', inplace=True)
            tmpLowMergedDf = mergeObj.getMergedBymethodDf(allTradingDatesDf, lowDf)
              
            openMergedDf[ric] = tmpOpenMergedDf[ric]
            highMergedDf[ric] = tmpHighMergedDf[ric]
            closeMergedDf[ric] = tmpCloseMergedDf[ric]
            lowMergedDf[ric] = tmpLowMergedDf[ric]
        
        return openMergedDf, highMergedDf,lowMergedDf ,closeMergedDf

    def getWeeklyDf(self, indexValueDf):
        
        
        indexValueDf['Week'] = indexValueDf.index.isocalendar().week
        
        wConSr = pd.Series(index = indexValueDf.index, dtype = 'float64')
        wConSr.loc[indexValueDf.index[0]] = 1
        
        for i in indexValueDf.index[1:]:
            
            ind = indexValueDf.index.get_loc(i)
            wDiff = int(indexValueDf.iloc[ind]['Week']) - int(indexValueDf.iloc[ind-1]['Week'])
            
            indWcon = wConSr.index.get_loc(i)
            
            if wDiff ==0 :
                wConSr.loc[i] = wConSr.iloc[indWcon-1]
            else:
                wConSr.loc[i] = wConSr.iloc[indWcon-1] + 1
                
        indexValueDf['Week_Con'] = wConSr
        
        
        weekEndSr = indexValueDf.groupby('Week_Con').tail(1)
        weekIndexValueDf = pd.DataFrame(index = weekEndSr.index)
        
        weekHighSr =  indexValueDf.groupby('Week_Con')['High'].max()
        weekHighSr.index = weekIndexValueDf.index
        
        weekLowSr =  indexValueDf.groupby('Week_Con')['Low'].min()
        weekLowSr.index = weekIndexValueDf.index
        
        
        
        weekVolSr =  indexValueDf.groupby('Week_Con')['Volume'].sum()
        weekVolSr.index = weekIndexValueDf.index
        
        weekIndexValueDf['High'] = weekHighSr
        weekIndexValueDf['Low'] = weekLowSr
        weekIndexValueDf['Close'] = weekEndSr['Close']
        
        

    # def getPickle(self,df, outputPickleFilePath):

    #     pickle_out=open(outputPickleFilePath,'wb')
    #     pickle.dump(df,pickle_out)
    #     pickle_out.close()


    def getAdjustedGrowthSr(self, numeratorSr, denomenatorSr, adjustmentCr = 1):

        gwthSr = (numeratorSr.div(denomenatorSr.where(denomenatorSr != 0)) - 1) *100

        if adjustmentCr == 1:

            firstFilter = pd.Series([firstCond and secondCond for firstCond, secondCond in zip(np.sign(denomenatorSr).astype(object) == -1 , np.sign(numeratorSr).astype(object) == -1)], index = numeratorSr.index)
            secondFilter = pd.Series([firstCond and secondCond for firstCond, secondCond in zip(np.sign(denomenatorSr).astype(object) == -1 , np.sign(numeratorSr).astype(object) == 1)], index = numeratorSr.index)


            firstFilterSr = pd.Series(np.where(firstFilter, -gwthSr.astype(object), gwthSr.astype(object)), index = firstFilter.index)
            finalFilterSr = pd.Series(np.where(secondFilter, np.abs(firstFilterSr.astype(object)), firstFilterSr.astype(object)), index = firstFilterSr.index)


        return finalFilterSr


    def getReversePivotDf(self,dataFrame, reportingDf,name):
        dfTransposeDf = dataFrame.T.reset_index()
        reversePivotDfdf = dfTransposeDf.melt(id_vars = 'index')

        # reverse pivoting report date
        reportDfTransposeDf = reportingDf.T.loc[dataFrame.T.index].reset_index()
        reversePivotReportDfDf = reportDfTransposeDf.melt(id_vars = 'index')

        # if reporting date available and fundamental data not present taken as Nan only if want to fill another value apply fillna at the end
        reversePivotReportDfDf[name] = reversePivotDfdf['value']
        #converting date to pandas datetime
        reversePivotReportDfDf['value'] = pd.to_datetime(reversePivotReportDfDf['value'])

        # changing names
        reversePivotReportDfDf.columns = ['DataFreq','Stocks', 'Date', name]

    #    reversePivotReportDfDf['Date'] = pd.to_datetime(reversePivotReportDfDf['Date']) + pd.offsets.MonthEnd(0)

        return reversePivotReportDfDf

    def getAdjustedMergedDf(self, reversePivotDf, stocksList, dataFieldName, monthEndDatesDf, monthsLag = 2, forwardMonths = 11):

        excelReaderObj = ExcelInputReader()
        pivotDf = excelReaderObj.getPivotTableOfDf(reversePivotDf, stocksList, valueName= dataFieldName)
        pivotDf.index = pivotDf.index + pd.DateOffset(months = monthsLag) + pd.offsets.MonthEnd(0)
        mergeObj = Merger()
        pivotMergedDf = mergeObj.getMergedBymethodDf(monthEndDatesDf, pivotDf,limit = forwardMonths)

        return pivotMergedDf
    

     
    def getNextDate(self, tradingDatesDf, rebalanceDates):
        
        nextRebalIndices = [tradingDatesDf.index.get_loc(rebal, method = 'ffill') + 1 for rebal in rebalanceDates]
        nextRebalDates = tradingDatesDf.iloc[nextRebalIndices]
        
        return nextRebalDates.index
        
            
    
    # def getExponentialWeighing(self, )



# In[3]:


class Merger:

    def __init__(self):
        pass

    def getMergedBymethodDf(self, firstDataFrame, secondDataFrame, mergerCol = 'Date', mergeMethod= 'left', fillNaMethod = 'ffill', limit = None):
        mergedDataFrame = pd.merge(firstDataFrame, secondDataFrame, on= mergerCol, how= mergeMethod)
        if fillNaMethod is not None:
            mergedDataFrame.fillna(method = fillNaMethod, inplace = True, limit = limit)
        mergedDataFrame.drop(columns = ['Month', 'Year', 'YearMonth'], axis = 1, inplace = True)
        mergedDataFrame.set_index(['Date'], inplace= True)
        return mergedDataFrame

    def getMergedByValueDf(self, firstDataFrame, secondDataFrame, mergerCol = 'Date', mergeMethod= 'left', fillNaValue = None):
        mergedDataFrame = pd.merge(firstDataFrame, secondDataFrame, on= mergerCol, how= mergeMethod)
        mergedDataFrame.fillna(fillNaValue, inplace = True)
        mergedDataFrame.drop(columns = ['Month', 'Year', 'YearMonth'], axis = 1, inplace = True)
        mergedDataFrame.set_index(['Date'], inplace= True)
        return mergedDataFrame
    
    def mergeTwoDf(self, firstDataFrame, secondDataFrame, mergerCol = 'Date', mergeMethod= 'left', fillNaMethod = 'ffill', limit = None):
        mergedDataFrame = pd.merge(firstDataFrame, secondDataFrame, on= mergerCol, how= mergeMethod)
        if fillNaMethod is not None:
            mergedDataFrame.fillna(method = fillNaMethod, inplace = True, limit = limit)
        mergedDataFrame.set_index(['Date'], inplace= True)
        return mergedDataFrame

#%%

class FleishmanPowerMethod:

    def __init__(self):
        pass

    def getFleishmanGseries(self, coffSr, normalSr):
        b,c,d = coffSr[0], coffSr[1], coffSr[2]
        a = -c
        gSeries = a*np.power(normalSr,0) + b*np.power(normalSr, 1) + c*np.power(normalSr,2) + d*np.power(normalSr,3)
        return gSeries

    def getFleishmanEq1Value(self, coffSr):
        b,c,d = coffSr[0], coffSr[1], coffSr[2]
        eqValue = b**2 + 6*b*d + 2*c**2 + 15*d**2 -1
        return eqValue

    def getFleishmanEq2Value(self, coffSr, expectedSkewness):
        b,c,d = coffSr[0], coffSr[1], coffSr[2]
        eqValue = 2*c*(b**2 + 24*b*d + 105*d**2 + 2) - expectedSkewness
        return eqValue

    def getFleishmanEq3Value(self, coffSr, expectedExKurtosis):
        b,c,d = coffSr[0], coffSr[1], coffSr[2]
        eqValue = 24*(b*d + c**2*(1 + b**2 + 28*b*d) + d**2*(12 + 48*b*d + 141*c**2 + 225*d**2)) - expectedExKurtosis
        return eqValue

    def getOptimizationFunction(self, coffSr, expectedSkewness, expectedExKurtosis):
        eq1Value = self.getFleishmanEq1Value(coffSr)
        eq2Value = self.getFleishmanEq2Value(coffSr, expectedSkewness)
        eq3Value = self.getFleishmanEq3Value(coffSr, expectedExKurtosis)

        minValue = eq1Value**2 + eq2Value**2 + eq3Value**2
        return minValue

    def getOptimizeFleishmanCoeff(self, expectedSkewness, expectedExKurtosis):
        exKurtSolBoundary = -1.2264489 + 1.6410373*expectedSkewness**2
        if expectedExKurtosis < exKurtSolBoundary:
            logger.info("-----------------------------can't find a solution------------------------")

        else:

            optimizeObj = Optimization()
            intCond = [1,0,0]
            arguments = (expectedSkewness, expectedExKurtosis)
            cons = ({'type' : 'eq', 'fun' : self.getFleishmanEq1Value},
                    {'type' : 'eq', 'fun' : self.getFleishmanEq2Value, 'args' : (expectedSkewness,)},
                    {'type' : 'eq', 'fun' : self.getFleishmanEq3Value, 'args' : (expectedExKurtosis,)})
            optimizeSolution = optimizeObj.getOptimizeAttr(self.getOptimizationFunction, intCond, arguments, None, cons)

        return optimizeSolution



# In[6]:


class Returns:

    def __init__(self, closePriceDf = None):
        self.closePriceDf = closePriceDf
        self.returnDf = None
        self.excessRetDf = None

    def getSimpleReturnDf(self, closePriceDf = None, numberOfDays = 1):

        if closePriceDf is None:
            closePriceDf = self.closePriceDf

        self.returnDf = closePriceDf.pct_change(numberOfDays, fill_method = None)
        return self.returnDf
    
    
    def getASSRratio(self, returnDf, b = 5, statsWindow = 65, normWindow= 250):
        
        if returnDf is None:
            returnDf = self.returnDf
        
        # factorsDf['NiftyRet'] = factorsDf['NiftyPrice'].pct_change()
        returnDf['Vol'] =  returnDf['Ret'].rolling(statsWindow).std()
        returnDf['AvgRet'] = returnDf['Ret'].rolling(statsWindow).mean()
        returnDf['StdRet'] = returnDf['Ret'].rolling(statsWindow).std()
        returnDf['Skew'] = returnDf['Ret'].rolling(statsWindow).skew()
        returnDf['Sharpe'] = returnDf['AvgRet'] / returnDf['StdRet']
        
        returnDf['ASSR'] = returnDf['Sharpe'] * np.sqrt(1 + (b * returnDf['Skew'] * returnDf['Sharpe']) / 3)
        
        utilsObj = UtilsQB()
        zFactorDf = utilsObj.getZ(returnDf, ['ASSR'], normWindow)
        return zFactorDf
        

#     def getFractionalReturnDf(self, closePriceDf = None):


    # nan handling
    def getTrimmedReturnDf(self, returnDf, window = 252, scaleFactor = 3):
        meanDf = returnDf.rolling(window).mean()
        stdDf = returnDf.rolling(window).std() * scaleFactor
        upperLimitDf = meanDf.add(stdDf)
        lowerLimitDf = meanDf.sub(stdDf)

        trimmedDf = returnDf.clip(lower = lowerLimitDf, upper = upperLimitDf)
        return trimmedDf


    def getExcessReturnOverMeanDf(self, returnDf = None, window = None):
        meanRetDf = returnDf.rolling(window).mean()
        self.excessRetDf = returnDf.sub(meanRetDf)
        return self.excessRetDf


    def getSemiDeviationReturnDf(self, excessRetDf = None, window = None):
        if excessRetDf == None:
            excessRetDf = self.excessRetDf

        negativeReturn = excessRetDf.where(excessRetDf <0, 0)
        squareNegativeReturn = negativeReturn.pow(2)
        rollingSqNegReturn = squareNegativeReturn.rolling(window).mean()
        return rollingSqNegReturn

    def getSemiDeviationReturnSr(self, returnDf = None):

        if returnDf is None:
            returnDf = self.returnDf

        meanRetDf = pd.DataFrame([returnDf.mean()]*returnDf.index.size, index = returnDf.index, columns= returnDf.columns)
        excessRetDf = returnDf - meanRetDf
        negativeReturn = excessRetDf.where(excessRetDf <0, 0)
        squareNegativeReturn = negativeReturn.pow(2)
        meanExSr = squareNegativeReturn.mean()
        sqrtSr = np.sqrt(meanExSr)
        return sqrtSr



    def getTwoMomentSimulatedNormalReturnDf(self, expectedReturnSr, expectedCovarianceMatrix, numberOfDays, normalNumbers = None):

        #expected return series is pandas series, expected cpvariance matrix is nd array, number of days int

        numberOfStocks = expectedReturnSr.size
        cholskeyDecompositionCov = np.linalg.cholesky(expectedCovarianceMatrix)

        if normalNumbers is None:
            normalNumbers = np.random.normal(0,1,(numberOfDays, numberOfStocks))

        #nd array (N*stocks)
        averageReturnDuplicated = np.asarray([expectedReturnSr.values]*numberOfDays)
        scaleNormal = np.dot(cholskeyDecompositionCov, normalNumbers.T)
        simulatedNormal = averageReturnDuplicated.T + scaleNormal
        simulatedReturnDf = pd.DataFrame(simulatedNormal.T, columns= expectedReturnSr.index)
        return simulatedReturnDf

    def getFourMomentSimulatedReturnDf(self, expectedReturnSr, expectedCovarianceMatrix, expectedSkewnessSr, expectedExKurtSr, numberOfDays):

        numberOfStocks = expectedReturnSr.size
        normalNumbers = np.random.normal(0,1,(numberOfDays, numberOfStocks))
        gNumbers = []

        fleishmanObj = FleishmanPowerMethod()
        for stockIndex in range(numberOfStocks):
            normalNumberSr = normalNumbers[:,stockIndex]
            skew = expectedSkewnessSr.values[stockIndex]
            exKurt = expectedExKurtSr.values[stockIndex]
            coffSr = fleishmanObj.getOptimizeFleishmanCoeff(skew, exKurt)
            logger.info(coffSr)
#            pd.Series(normalNumberSr).to_excel('normalNum_4_' + str(stockIndex)+ '.xlsx')
            gSeries = fleishmanObj.getFleishmanGseries(coffSr, normalNumberSr)

            if len(gNumbers) == 0:
                gNumbers = gSeries
            else :
                gNumbers = np.vstack((gNumbers, gSeries))
#            pd.DataFrame(gNumbers).to_excel('gNum_4_' + str(stockIndex) + '.xlsx')
#        pd.DataFrame(gNumbers.T).to_excel('gNumBers' + '.xlsx')
        fourMomentSeries = self.getTwoMomentSimulatedNormalReturnDf(expectedReturnSr, expectedCovarianceMatrix, numberOfDays, gNumbers.T)
        return fourMomentSeries


# In[7]:


class Ranker:

    def __init__(self, ascendingBool = False):
        self.ascendingBool = ascendingBool

    def rankSingleDataFrame(self, dataFrameToRank, methodForSameRank = 'average'):
        rankDataFrame = dataFrameToRank.rank(1, ascending= self.ascendingBool, method = methodForSameRank)
        return rankDataFrame

    def rankSingleSeries(self, seriesToRank, pctile=False, methodForSameRank = 'average'):
        rankSeries = seriesToRank.rank(0, ascending=self.ascendingBool,pct = pctile, method = methodForSameRank)
        return rankSeries

    def singleDataFrameRankFilter(self, dataFrameToRank, filteredDataFrame, methodForSameRank = 'average'):
        dataFrameToRankSS = pd.DataFrame(np.where(filteredDataFrame == 1, dataFrameToRank,np.nan), index=  dataFrameToRank.index, columns= dataFrameToRank.columns)
        rankDataFrame = dataFrameToRankSS.rank(1, ascending= self.ascendingBool, method = methodForSameRank)
        return rankDataFrame

    def rankSeriesFilter(self, seriesToRank, filteredSr):
        seriesToRankSS = pd.Series(np.where(filteredSr == 1, seriesToRank, np.nan), index=  seriesToRank.index, name= seriesToRank.name)
        rankDataFrame = seriesToRankSS.rank(0, ascending= self.ascendingBool)
        return rankDataFrame


# In[8]:


# methods of this will be different strategies for stock selection
# only on a date basis (dataFrameToRank can be pandas series also) ***** change the code accordingly
class StockSelector:

    def __init__(self):
        pass

    def getDfFromRank(self, rankDf, numberOfStocks = None):

        if numberOfStocks is None:
            numberOfStocks = rankDf.columns

        selectedStocksDf = pd.DataFrame(np.where(rankDf <= numberOfStocks, 1, 0), index=  rankDf.index, columns= rankDf.columns)
        return selectedStocksDf

    def getFromRankSr(self, rankSeries, numberOfStocks = None):

        if numberOfStocks is None:
            numberOfStocks = rankSeries.index

        selectedStocksSr = pd.Series(np.where(rankSeries <= numberOfStocks, 1, 0), index= rankSeries.index, name= rankSeries.name)
        return selectedStocksSr


    def getFromSignFilteringSr(self, valueSeries, numberOfStocks, method = "Pos", sortingSr = None):

        if sortingSr is None:
            sortingSr = valueSeries

        if method == "Pos":
            rankObj = Ranker()
            signSr = pd.Series(np.where(valueSeries > 0, 1, 0), index = valueSeries.index)
            selectedSr = self.getFromRankSr(rankObj.rankSeriesFilter(sortingSr, signSr), numberOfStocks)
        elif method == "Neg":
            rankObj = Ranker(True)
            signSr = pd.Series(np.where(valueSeries < 0, 1, 0), index = valueSeries.index)
            selectedSr = self.getFromRankSr(rankObj.rankSeriesFilter(sortingSr, signSr), numberOfStocks)
        return selectedSr
# In[10]:


class Rebalance:

    def __init__(self):
        pass

    def getRebalanceFromTradingDates(self, tradingDates, startDate = None, startIndex= None, gap=None):

        if startIndex is None:
            if startDate is not None:
                startIndex = tradingDates.get_loc(startDate)
            else:
                startIndex = 0


        rebalDates = tradingDates.values[startIndex::gap]
        return rebalDates

    def getFrequecyRebalDates(self, sDate, eDate, **delta):

        rebalDates = []
        tmpDate = sDate
        while tmpDate < eDate:

            rebalDates.append(tmpDate)
            tmpDate += DateOffset(**delta)


        return rebalDates









# In[40]:


class Optimization:

    def __init__(self):
        pass

    def getOptimizeAttr(self, objectiveFunction, initialCondition, arguments, bounds, cons, optimizeMethod = 'SLSQP',  options = None):

        if options == None:
            options = {'ftol':1e-12,'eps':1e-12,'maxiter':2000}


        opts = sco.minimize(objectiveFunction, initialCondition, args=arguments,
                        method=optimizeMethod, bounds=bounds, constraints=cons,options= options)
#        logger.info(opts.message)
#        display(opts.fun)
        return [opts.x, opts.message]


# In[17]:


class Volatility:

    def __init__(self, returnDf = None):
        self.returnDf = returnDf

    # have the arguments of slicing the return data frame
    def getSimpleCovarianceDf(self, returnDf):
        covarianceDf = returnDf.cov()
        return covarianceDf

    def getLedoitCovarianceDf(self, returnDf = None):
        if returnDf is None:
            returnDf = self.returnDf

        if returnDf.empty:
            covarianceMatrix = None
        else:
            covarianceMatrix = covariance.ledoit_wolf(returnDf)[0]
        return covarianceMatrix

    def getStdevSr(self, returnDf = None):
        if returnDf is None:
            returnDf = self.returnDf
        stdDevSr = returnDf.std()
        return stdDevSr


# In[18]:


class SliceDataFrame:
    def __init__(self, dfToSlice = None):
        self.dfToSlice = dfToSlice

    def getIndexSlice(self, startIndex, endIndex, method, dfToSlice= None):

        if dfToSlice is None:
            dfToSlice = self.dfToSlice.copy()
        else:
            dfToSlice = dfToSlice.copy()

        if method == "BothIncl":
            slicedDf = dfToSlice.loc[startIndex : endIndex+1]
        elif method == "EndIncl":
            slicedDf = dfToSlice.iloc[startIndex+1 : endIndex+1]
        elif method == "StartIncl":
            slicedDf = dfToSlice.iloc[startIndex : endIndex]
        else:
            slicedDf = dfToSlice.iloc[startIndex+1 : endIndex]

        return slicedDf

    def getLengthSlice(self, method, startElement= None, endElement= None,days = None, dfToSlice = None):

        if dfToSlice is None:
            dfToSlice = self.dfToSlice.copy()
        else:
            dfToSlice = dfToSlice.copy()
            

        if startElement is None:
            endIndex = dfToSlice.index.get_indexer([endElement],'ffill')[0]
            startIndex = endIndex - days
            slicedDf = self.getIndexSlice(startIndex, endIndex, method, dfToSlice)
        elif endElement is None:
            startIndex = dfToSlice.index.get_indexer([startElement])[0]
            endIndex = startIndex + days
            slicedDf = self.getIndexSlice(startIndex, endIndex, method, dfToSlice)
        else:
            startIndex = dfToSlice.index.get_indexer([startElement])[0]
            endIndex = dfToSlice.index.get_loc(endElement)
            slicedDf = self.getIndexSlice(startIndex, endIndex, method, dfToSlice)

        return slicedDf

# In[27]:


class PortolfioOptimizerFuncations:
    def __init__(self):
        pass

    def getNegSharpeRatio(self, weightSr, expectedReturnSr, covarianceMatrix):
        sharpeRatio = np.dot(weightSr.T,expectedReturnSr)/np.sqrt(np.dot(np.dot(weightSr.T,covarianceMatrix),weightSr))
        return -sharpeRatio

    def getNegDiversificationRatio(self, weightSr, covarianceMatrix, stdDevSr):
        divRatio = np.dot(weightSr.T,stdDevSr)/np.sqrt(np.dot(np.dot(weightSr.T,covarianceMatrix),weightSr))
        return -divRatio

    def getNegReturn(self, weightSr, expectedReturnSr):
        returnValue = np.dot(weightSr.T,expectedReturnSr)
        return -returnValue

    def getStdDev(self, weightSr, covarianceMatrix):
        portStdev = np.sqrt(np.dot(np.dot(weightSr.T,covarianceMatrix),weightSr))
        return portStdev

    def getVar(self, weightSr, returnDf, alpha):
        varValue = np.nanpercentile(np.dot(returnDf, weightSr), 100*(1-alpha))
        return varValue

#    def getVarNormalDistr

    def getCvar(self, weightSr, returnDf, alpha):
        varValue = self.getVar(weightSr, returnDf, alpha)
        portReturn = np.dot(returnDf, weightSr)
        cVarValue = np.nanmean(portReturn[portReturn < varValue])
        return cVarValue

    def getRiskContributionMatrix(self, weightSr, covarianceMatrix):
        marginalRiskMatrix = np.dot(covarianceMatrix, weightSr)
        riskMatrix = marginalRiskMatrix * weightSr
        return riskMatrix

    def getRiskContributionDiffSum(self, weightSr, covarianceMatrix):
        riskContriSum = 0
        riskSr = self.getRiskContributionMatrix(weightSr, covarianceMatrix)
        for indexNum in range(0, riskSr.size-1):
            for nextIndexNum in range(indexNum +1, riskSr.size):
                diffSr = riskSr[nextIndexNum] - riskSr[indexNum]
                riskContriSum = riskContriSum + diffSr
        return riskContriSum


# In[21]:


# output:  pandas series
class WeightCalculator:

    # input can be in form of selectedstocks series (stocks selector and weight are in the sameloop)
    # or dataframe( selected stocks data frame input given) to weight class
    def __init__(self, selectedStocksDf = None, selectedStocksSr = None):
        self.selectedStocksDf = selectedStocksDf
        self.selectedStocksSr = selectedStocksSr

    def setOptimizeArguments(self, **keyWordArgs):
        self.keyWordArgs = keyWordArgs

    def getEqualWeightsDf(self, selectedStocksDf):
        sumRankDataFrame = selectedStocksDf.sum(1)
        sumRankList = sumRankDataFrame.replace(to_replace = 0, value = np.nan).tolist()
        equalWeightDataFrame = selectedStocksDf.div(sumRankList, axis = 0)
        return equalWeightDataFrame

    # because for every optimize algo the keyargument keys are same and all are required
    def getOptimizeWeightsSr(self, objectiveFunction, arguments, **optimizeKeywordArgs):
        # replace all none values corresponding to keys with global variable
        for keywordItem in optimizeKeywordArgs.items():
            if keywordItem[1] is None:
                optimizeKeywordArgs.update({keywordItem[0] : self.keyWordArgs.get(keywordItem[0])})

        optimizeObj = Optimization()
        weightSr = optimizeObj.getOptimizeAttr(objectiveFunction, optimizeKeywordArgs.get('initialCondition'), arguments, optimizeKeywordArgs.get('bounds'), optimizeKeywordArgs.get('cons'), optimizeKeywordArgs.get('optMethod'),  optimizeKeywordArgs.get('options'))
        return weightSr

    def getEqualWeightsSr(self, selectedStocksSr = None):
        if selectedStocksSr is None:
            selectedStocksSr = self.selectedStocksSr
        totalStocks = selectedStocksSr.sum()
        equalWeightSr = selectedStocksSr.div(totalStocks)
        return equalWeightSr

    def getInvVolWeightsSr(self, stdSr):
        invStdSr = 1 / stdSr
        weightsInvStdSr = invStdSr.div(invStdSr.sum())
        return weightsInvStdSr

    def getPropsectWeightsSr(self, subReturnDf, valueFunctionArgArr = [0.88, 2.25], probWeighingArgArr = [0.61, 0.69], expPow = 100, method = 'Binomial', convertingPtMethod = 'Linear'):

        probObj = pt.ProbabilityOfPastReturn()
        prosObj = pt.ProspectTheory(valueFunctionArgArr, probWeighingArgArr)

        if method == 'Binomial':
            probDf = subReturnDf.apply(lambda col : probObj.getBinomialProbabilities(col))
        elif method == "EqualProb":
            probDf = subReturnDf.apply(lambda col : probObj.getEqualProbabilities(col))
        elif method == "IncreasingProb":
            probDf = subReturnDf.apply(lambda col : probObj.getIncreasingProbabilities(col))
        elif method == "IncreasingBinomial":
            probDf = subReturnDf.apply(lambda col : probObj.getIncreasingBinomialProbabilities(col))


        weights = subReturnDf.apply(lambda colRet :  prosObj.getProspectWeightValue(probDf[colRet.name], colRet))
#        logger.info(weights)

        prospectWeightSr = weights.sum()
        excessPtWeightSr = prospectWeightSr - [prospectWeightSr.mean()]*prospectWeightSr.size

#        logger.info(prospectWeightSr)

        # weight to this function
        numStocks = prospectWeightSr.size
        maxWeight = 2/ numStocks
        minWeight = 1/ (numStocks*2)
        maxMinRatio = maxWeight / minWeight

        maxPtWeight = prospectWeightSr.max()
        minPtWeight = prospectWeightSr.min()
        sumPtWeight = prospectWeightSr.sum()

        if convertingPtMethod == 'Linear':
            coffMin = (minPtWeight - maxPtWeight) / (numStocks*minPtWeight - maxMinRatio*numStocks*maxPtWeight + (maxMinRatio - 1)*sumPtWeight)
            coffMax = maxMinRatio * coffMin
            slope = (coffMax - coffMin) / (minPtWeight - maxPtWeight)
            finalWeightSr = coffMax - slope*(minPtWeight - prospectWeightSr)

        return prospectWeightSr, excessPtWeightSr, finalWeightSr
   

    def getMaxSharpeWeightSr(self, expectedRetSr, covMatrix, stocksNameArr):

        oprtFuncObj = PortolfioOptimizerFuncations()

        sharpeArg = (expectedRetSr, covMatrix)
        numStocks = stocksNameArr.size
        localArgs = {'initialCondition' : numStocks*[0.01,],'bounds': tuple( (1/(numStocks*2.),2./numStocks) for asset in range(numStocks)),
                        'cons' : None,'optMethod' : None, 'options' : None}

        if covMatrix is None:
            maxSharpeWeightSr = [pd.Series(numStocks*[0], index = stocksNameArr), 0]
        else:
            optResults = self.getOptimizeWeightsSr(oprtFuncObj.getNegSharpeRatio, sharpeArg, **localArgs)
            maxSharpeWeightSr = [pd.Series(optResults[0], index = stocksNameArr), optResults[1]]

        return maxSharpeWeightSr

    def getMaxDivWeightSr(self, covMatrix, stdevSr, stocksNameArr):

        oprtFuncObj = PortolfioOptimizerFuncations()

        divArg = (covMatrix, stdevSr)
        numStocks = stocksNameArr.size
        localArgs = {'initialCondition' : numStocks*[0.01,],'bounds': tuple( (1/(numStocks*2.),2./numStocks) for asset in range(numStocks)),
                        'cons' : None,'optMethod' : None, 'options' : None}


        if covMatrix is None:
            maxDivWeightSr = [pd.Series(numStocks*[0], index = stocksNameArr),0]
        else:
            optResults = self.getOptimizeWeightsSr(oprtFuncObj.getNegDiversificationRatio, divArg, **localArgs)
            maxDivWeightSr = [pd.Series(optResults[0], index = stocksNameArr), optResults[1]]

        return maxDivWeightSr

    def getMinVolatilityWeightSr(self, covMatrix, stocksNameArr):

        oprtFuncObj = PortolfioOptimizerFuncations()

        minVolArg = (covMatrix)
        numStocks = stocksNameArr.size

#        if localArgs is None:
        localArgs = {'initialCondition' : numStocks*[0.01,],'bounds': tuple( (1/(numStocks*2.),2./numStocks) for asset in range(numStocks)),
                        'cons' : None,'optMethod' : None, 'options' : None}

        if covMatrix is None:
            minVolWeightSr = [pd.Series(numStocks*[0], index = stocksNameArr),0]
        else:
            optResults = self.getOptimizeWeightsSr(oprtFuncObj.getStdDev, minVolArg, **localArgs)
            minVolWeightSr = [pd.Series(optResults[0], index = stocksNameArr), optResults[1]]

        return minVolWeightSr

#    def getMinVarWeightSr(self, returnDf, stocksNameArr, alpha = 0.95):
#
#        oprtFuncObj = PortolfioOptimizerFuncations()
#
#        minVarArg = (returnDf, alpha)
#        numStocks = stocksNameArr.size
#
#        localArgs = {'initialCondition' : numStocks*[0.01,],'bounds': tuple( (1/(numStocks*2.),2./numStocks) for asset in range(numStocks)),
#                        'cons' : None,'optMethod' : None, 'options' : None}
#
#        if numStocks == 0:
#            minVarWeightSr = pd.Series(numStocks*[0], index = stocksNameArr)
#        else:
#            minVarWeightSr = pd.Series(self.getOptimizeWeightsSr(oprtFuncObj.getVar, minVarArg, **localArgs), index = stocksNameArr)
#
#        return minVarWeightSr
#
#    def getMinCvarWeightSr(self, returnDf, stocksNameArr, alpha = 0.95):
#
#        oprtFuncObj = PortolfioOptimizerFuncations()
#
#        minCvarArg = (returnDf, alpha)
#        numStocks = stocksNameArr.size
#
#        localArgs = {'initialCondition' : numStocks*[0.01,],'bounds': tuple( (1/(numStocks*2.),2./numStocks) for asset in range(numStocks)),
#                        'cons' : None,'optMethod' : None, 'options' : None}
#
#        if numStocks == 0:
#            minCvarWeightSr = pd.Series(numStocks*[0], index = stocksNameArr)
#        else:
#            minCvarWeightSr = pd.Series(self.getOptimizeWeightsSr(oprtFuncObj.getCvar, minCvarArg, **localArgs), index = stocksNameArr)
#
#        return minCvarWeightSr

    def getERCweightSr(self, covMatrix, stocksNameArr):



        oprtFuncObj = PortolfioOptimizerFuncations()

        numStocks = stocksNameArr.size
        str1='{\'type\': \'eq\', \'fun\': lambda x: x['
        str2=']*np.dot(covMatrix,x)['
        str3=']-x[numberOfStocks-1]*np.dot(covMatrix,x)[numberOfStocks-1]},'
        mystr='[{\'type\': \'eq\', \'fun\': lambda x: np.sum(x) - 1},'
        for ii in range(numStocks-1):
            mystr=mystr+str1+str(ii)+str2+str(ii)+str3
        mystr=mystr+']'
         #logger.info(mystr)
        new=mystr[:len(mystr)-2]+']'
         #     logger.info(new)
        '''use below cons for ERC model'''
        ercCons = eval(new)


        ercArg = (covMatrix)
        ercLocalArgs = {'initialCondition' : numStocks*[1./numStocks,],'bounds': None,'cons' : ercCons,'optMethod' : None, 'options' : None}
        ercWeightSeries = pd.Series(self.getOptimizeWeightsSr(oprtFuncObj.getStdDev, ercArg, **ercLocalArgs), index = stocksNameArr)
        return ercWeightSeries



#    def getMinVolatilityMarkowitzWeightSr(self, covMatrix, stocksNameArr, expectedReturn = 0.2):



    def getKellyWeightSr(self, covMatrix, expectedReturnSr):

        invCovMatrix = np.linalg.inv(covMatrix)
        kellyWeights = pd.Series(np.dot(invCovMatrix, expectedReturnSr), index = expectedReturnSr.index)
        kellyWeightSr = kellyWeights.div(kellyWeights.sum())

        return kellyWeightSr

    def getMarkowitzWeightSr(self, covMatrix, expectedReturnSr, targetPortfolioReturn = None, targetPortfolioVol = None):


#        resultWeightSr = []

        invCovMatrix = np.linalg.inv(covMatrix)
        kellyWeights = pd.Series(np.dot(invCovMatrix, expectedReturnSr), index = expectedReturnSr.index)

#        maximizing return given portoflio volatility / trarget portfolio volatility
        if targetPortfolioReturn is None:
             factor = np.sqrt(targetPortfolioVol / np.dot(expectedReturnSr.T, kellyWeights))
             markowitzWeightSr = factor * kellyWeights
#             resultWeightSr.append(markowitzMaxRetWeightSr)
#        min volatility given portoflio return / trarget portfolio Return
        elif targetPortfolioVol is None:
            factor = targetPortfolioReturn / np.dot(expectedReturnSr.T, kellyWeights)
            markowitzWeightSr = factor * kellyWeights
#            resultWeightSr.append(markowitzMinVolWeightSr)
        # do both targert return , target volatility
#        else:
#            factorMaxRet = np.sqrt(targetPortfolioVol / np.dot(expectedReturnSr.T, kellyWeights))
#            markowitzMaxRetWeightSr = factorMaxRet * kellyWeights
#            resultWeightSr.append(markowitzMaxRetWeightSr)
#            factorMinVol = targetPortfolioReturn / np.dot(expectedReturnSr.T, kellyWeights)
#            markowitzMinVolWeightSr = factorMinVol * kellyWeights
#            resultWeightSr.append(markowitzMinVolWeightSr)

        return markowitzWeightSr

    def allWeights(self, weighingSchemeNames, returnDf, selectedStocksSr, bounds= None, rebal = None):

        stocks = selectedStocksSr[selectedStocksSr == 1].index
        numberOfStocks = stocks.size
        
        # print(numberOfStocks)

        returnObj = Returns()
        oprtFuncObj = PortolfioOptimizerFuncations()
        volatilityObj = Volatility()

        expectedReturnSr = returnObj.getSemiDeviationReturnSr(returnDf)
        covMatrix = volatilityObj.getLedoitCovarianceDf(returnDf)
        stdSr = volatilityObj.getStdevSr(returnDf)

        
        # print(covMatrix)
#        pd.DataFrame(covMatrix).to_excel('Index/N500_LowVol/Weight_Check_Vol/' +str(rebal.year) + "_" + str(rebal.month) + "_" + str(rebal.day) + '.xlsx')


        initialCond = numberOfStocks*[0.01,]
        bounds = tuple( (1/(numberOfStocks*2.),2./numberOfStocks) for asset in range(numberOfStocks))
        cons = ({'type': 'eq', 'fun': lambda x: np.sum(x)-1.0})

        globalArgs = {'initialCondition' : initialCond,'bounds': bounds,'cons': cons,'optMethod' :'SLSQP', 'options' : None}
        self.setOptimizeArguments(**globalArgs)


        str1='{\'type\': \'eq\', \'fun\': lambda x: x['
        str2=']*np.dot(covMatrix,x)['
        str3=']-x[numberOfStocks-1]*np.dot(covMatrix,x)[numberOfStocks-1]},'
        mystr='[{\'type\': \'eq\', \'fun\': lambda x: np.sum(x) - 1},'
        for ii in range(numberOfStocks-1):
            mystr=mystr+str1+str(ii)+str2+str(ii)+str3
        mystr=mystr+']'
         #logger.info(mystr)
        new=mystr[:len(mystr)-2]+']'
         #     logger.info(new)
        '''use below cons for ERC model'''
        ercCons = eval(new)

        stdevArg = (covMatrix)
        ercLocalArgs = {'initialCondition' : numberOfStocks*[1./numberOfStocks,],'bounds': bounds,'cons' : ercCons,'optMethod' : None, 'options' : None}

#        localAllArgs = {'initialCondition' :  numberOfStocks*[1./numberOfStocks,],'bounds': None,'cons' : None,'optMethod' : None, 'options' : None}

        allWeightDict = {}

        for weighingScheme in weighingSchemeNames:

            if weighingScheme == "MaxSharpe":
                # print('here')
                allWeightDict.update({weighingScheme : self.getMaxSharpeWeightSr(expectedReturnSr, covMatrix, stocks)})
            elif weighingScheme == "MaxDiv":
                allWeightDict.update({weighingScheme : self.getMaxDivWeightSr(covMatrix, stdSr, stocks)})
            elif weighingScheme == "MinVol":
                # print('here')
                allWeightDict.update({weighingScheme :  self.getMinVolatilityWeightSr(covMatrix, stocks)})
            elif weighingScheme == "EqualWeight":
                allWeightDict.update({weighingScheme : [self.getEqualWeightsSr(selectedStocksSr[stocks]), 1]})
            elif weighingScheme == "ERC":
                allWeightDict.update({weighingScheme : self.getOptimizeWeightsSr(oprtFuncObj.getStdDev, stdevArg, **ercLocalArgs)})

        return allWeightDict




    def calculateWeightsAllRebalance(self, rebalDates, selectedStocksDf, returnDf, weighingSchemeNames = ['MaxSharpe']):

        weightDfs = {}
        msg = []

        for weighingScheme in weighingSchemeNames:

            weightDfs.update({weighingScheme: pd.DataFrame(index = rebalDates, columns = returnDf.columns)})
#            weightDfs.append(weightDf)

        sliceObj = SliceDataFrame()

        for date in rebalDates:
            rebalMsg = []
            # selectedStocks series
            selectedStocksSr = selectedStocksDf.loc[date]
            # stocks name list
            stocks = selectedStocksSr[selectedStocksSr == 1].index
            #return data frame slicing
            subReturnDf = sliceObj.getLengthSlice('EndIncl', endElement= date, days= 65, dfToSlice= returnDf)[stocks]


#            subReturnDf.to_excel('Index/N500_LowVol/Weight_Check/' + str(date.year) + "_" + str(date.month) + "_" + str(date.day) + '.xlsx')

            allWeightsVar = self.allWeights(weighingSchemeNames, subReturnDf, selectedStocksSr, date)

            for weighingScheme in weighingSchemeNames:
                result = allWeightsVar.get(weighingScheme)
                weightDfs.get(weighingScheme).loc[date][stocks] = result[0]
                rebalMsg.append(result[1])

            msg.append(rebalMsg)


            logger.info(date)

        return weightDfs, msg



# In[80]:


class IndexCalculator:
    def __init__(self, indexDates, rebalDates, weightDf= None, priceDf=None, sipDates = None, sipWeightDf = None, **keyWordArgs):
        self.indexDates = indexDates
        self.rebalDates = rebalDates
        self.weightDf = weightDf
        self.priceDf = priceDf
        self.sipDates = sipDates
        self.sipWeightDf = sipWeightDf
        self.keyWordArgs = keyWordArgs

#    def setKeyWordArguments(self, **keyWordArgs):
#        self.keyWordArgs = keyWordArgs

    def getSimpleSharesSr(self, weightSr, priceSr, moneyInvested = 100):
        
        # logger.info(weightSr)
        
        if weightSr.sum() - 1 > 0.0001:
            logger.info('---------------------------Weight Sum not equal to 1-------------')
            logger.info('----------------------------' + str(weightSr.sum()))
        
        # sstocks = weightSr[~ weightSr.isna()].index
        sstocks = weightSr[weightSr != 0].index
        # for sstock in sstocks:
        #     # logger.info(sstock)
        #     # logger.info(priceSr.loc[sstock])
        #     price = priceSr.loc[sstock]
        #     if math.isnan(price):
        #         logger.info('---------------------Price is Null for ---------' + sstock)
        sIndex = 0
        # logger.info(sstocks)
        # logger.info(len(sstocks))
        # logger.info(priceSr.loc[sstocks])
        # for price in priceSr.loc[sstocks]:
        for price in priceSr.reindex(index = sstocks):
            sstock = sstocks[sIndex]
            if math.isnan(price):
                logger.info('---------------------Price is Null for ---------' + sstock)
            sIndex =  sIndex + 1    
        unitSharesSr = weightSr.div(priceSr)
        sharesSr = moneyInvested * unitSharesSr
        sharesSr.fillna(0, inplace = True)
        return sharesSr

    def getTransactionValue(self, oldSharesSr, newSharesSr, priceSr):

        sharesDiff = newSharesSr - oldSharesSr
        absDifferenceSharesSr = np.absolute(sharesDiff)
        absTransactionValue = (absDifferenceSharesSr * priceSr).sum()
        transactionValue = (sharesDiff * priceSr).sum()

        return absTransactionValue, transactionValue

    def getTransactionCost(self, absTransactionValue, stt = 0.1, transaction = 0.00325, gst = 18, sebi = 10/10000000):

        sttCharges = absTransactionValue * stt / 100
        transactionCharges = absTransactionValue * transaction / 100
        gstCharges = transactionCharges * gst /100
        sebiCharges = absTransactionValue * sebi

        totalTransactionCost = sttCharges + transactionCharges + gstCharges + sebiCharges
        return totalTransactionCost

    def getExpenseRatioCost(self, lastIndexValue, newIndexValue):

        expensePercentage = self.keyWordArgs.get('ExpensePercentage')
        avgIndexValue = 0.5*(lastIndexValue + newIndexValue)
        expenseRatioCost = avgIndexValue * expensePercentage * 0.01
        return expenseRatioCost

    def getExpenseRatioAvgCost(self, allIndexValues):

        expensePercentage = self.keyWordArgs.get('ExpensePercentage')
        avgIndex = allIndexValues.mean()
        expenseRatioCost = avgIndex * expensePercentage * 0.01
        return expenseRatioCost


    # below 2 functions are when there is no additional money added (whatever the last portoflio, is redistributed) [Ignore]
    def getRebalanceSharesSr(self, weightSr, priceSr, moneyInvested):

        sharesSr = self.getSimpleSharesSr(weightSr, priceSr, moneyInvested)
        return sharesSr

    def getTripleBoxSharesSr(self, moneyInvested, conditionDf, drawDownIndex, liquidBeesPrice, weightSr, priceSr):

        portfolioWeight = conditionDf.iloc[drawDownIndex]['PortfolioWeight']
        liquidBeesWeight = conditionDf.iloc[drawDownIndex]['LiquidbeesWeight']

        portMoneyInvested  = portfolioWeight * moneyInvested
        liquidbeesMoneyInvested = liquidBeesWeight * moneyInvested

        sharesSr = self.getSimpleSharesSr(weightSr, priceSr, portMoneyInvested)
        liquidBeesShare = liquidbeesMoneyInvested / liquidBeesPrice

        outputTuple = {'PortfolioShare' : sharesSr, 'LiquidbeesShare' : liquidBeesShare}

        return outputTuple
    
    
    def getSimpleNextDayRebalIndex(self, openPriceDf, highPriceDf, lowPriceDf, includeTransactionCost = False, indexName = 'SimpleIndexValue', indexStartValue = 100):

        indexDf = pd.DataFrame(index = self.indexDates, columns= [indexName])
        indexDf.index.name = 'Date'
        
        indexDf.loc[self.indexDates[0]] = indexStartValue
        
        # logger.info(self.priceDf.loc[self.rebalDates[0]])
        # logger.info(openPriceDf.loc[self.rebalDates[0]])
        # logger.info(highPriceDf.loc[self.rebalDates[0]])
        # logger.info(lowPriceDf.loc[self.rebalDates[0]])
        
        aPriceZero = (self.priceDf.loc[self.rebalDates[0]] + openPriceDf.loc[self.rebalDates[0]] +
        highPriceDf.loc[self.rebalDates[0]] + lowPriceDf.loc[self.rebalDates[0]] ) / 4
        
        #initialization of shares (assuming rebalance date [0] is equal to index date [0])
        sharesSr = self.getSimpleSharesSr(self.weightDf.loc[self.rebalDates[0]], self.priceDf.loc[self.rebalDates[0]] , indexStartValue)
#        oldSharesSr = pd.Series(0, index = sharesSr.index)

#         moneyDebitedDf = pd.DataFrame(0, index = self.indexDates, columns = ['MoneyDebited'])
#         moneyDebitedDf.index.name = 'Date'

        sharesDf = pd.DataFrame(index = self.indexDates, columns= self.weightDf.columns)
#         oldSharesDf= pd.DataFrame(index = self.indexDates, columns= self.weightDf.columns)
        transactionDf = pd.DataFrame(index = self.rebalDates, columns= ['TransactionCost'])

        includeExpenseRatio = self.keyWordArgs.get('ExpensePercentage') is not None
        expenseCostDf = pd.DataFrame()

        indexDf.loc[self.indexDates[0]] = sharesSr.mul(self.priceDf.loc[self.indexDates[0]]).sum()     

    
        if includeExpenseRatio :
            advisoryFeesDates = self.keyWordArgs.get('ExpenseRatioDates')
            expenseCostDf = pd.DataFrame(index = advisoryFeesDates, columns= ['ExpenseRatioCost', 'SumExpenseRatioCost'])
            
        logger.info(self.rebalDates[0])
            
        for indexDate in self.indexDates[1:]:

            priceSr = self.priceDf.loc[indexDate]

            
            
            if sharesSr.sum() == 0:
                dateIndxx = np.where(self.indexDates == indexDate)[0][0] -1
                if dateIndxx == -1:
                    indexDf.loc[indexDate] = indexStartValue
                else:
                    prevIndexDate  = self.indexDates[dateIndxx]
                    indexDf.loc[indexDate] = indexDf.loc[prevIndexDate]
            else:
                simpleRet = (sharesSr * priceSr).sum()
                indexDf.loc[indexDate] = simpleRet

#             if not oldSharesSr.equals(sharesSr):
#                 transactionValues = self.getTransactionValue(oldSharesSr, sharesSr, priceSr)
#                 absTransValue = transactionValues[0]
#                 transactionCost = self.getTransactionCost(absTransValue)
#                 moneyDebited = transactionValues[1] + transactionCost
#                 moneyDebitedDf.loc[indexDate] = moneyDebited

#            display(sharesSr)
            sharesDf.loc[indexDate][sharesSr.index] = sharesSr.values
#             oldSharesDf.loc[indexDate][oldSharesSr.index] = oldSharesSr.values

#             oldSharesSr = sharesSr

            if includeExpenseRatio:
#                    logger.info(moneyInvested)

                if indexDate in advisoryFeesDates:

                    lastIndexIndex = np.where(advisoryFeesDates == indexDate)[0][0] - 1

                    if lastIndexIndex == -1:
                        expenseRatioCost  = 0
                    else:
                        lastIndexDates = np.where(self.indexDates == advisoryFeesDates[lastIndexIndex])[0][0] + 1
                        # lastIndexValue = indexDf.loc[self.rebalDates[lastIndexIndex]][indexDf.columns[0]]
                        lastAllIndexValues = indexDf.loc[self.indexDates[lastIndexDates] : indexDate][indexDf.columns[0]]
                        # logger.info(lastAllIndexValues.head())
                        expenseRatioCost =  self.getExpenseRatioAvgCost(lastAllIndexValues)

                    expenseCostDf.loc[indexDate]['ExpenseRatioCost'] = expenseRatioCost
                    # moneyInvested = moneyInvested - expenseRatioCost
                    # indexDf.loc[indexDate] -=  expenseRatioCost

                    # logger.info('expense ratio reduced at--------------------' + str(indexDate))

            # check for rebalance date (date triggering)
            if indexDate in self.rebalDates:
                weightSr = self.weightDf.loc[indexDate]
                # moneyInvested = indexDf.loc[indexDate][indexDf.columns[0]]
                currentIndexValue = indexDf.loc[indexDate][indexDf.columns[0]]
                
                openSr = openPriceDf.loc[indexDate]
                highSr = highPriceDf.loc[indexDate]
                lowSr = lowPriceDf.loc[indexDate]
                
                apriceSr = (priceSr + openSr + highSr + lowSr)/4
                
                moneyInvested = (sharesSr * apriceSr).sum()
                
                if includeTransactionCost:

#                    logger.info(weightSr)
#                    logger.info(priceSr)
#                    logger.info(moneyInvested)
#
                    newShareSr = self.getRebalanceSharesSr(weightSr, priceSr, moneyInvested)

                    absoluteDifferenceSum = self.getTransactionValue(sharesSr, newShareSr, priceSr)[0]
                    transactionCostRebal = self.getTransactionCost(absoluteDifferenceSum)
                    transactionDf.loc[indexDate] = transactionCostRebal
                    moneyInvested = moneyInvested - transactionCostRebal

#                 if includeExpenseRatio:
# #                    logger.info(moneyInvested)

#                     lastIndexIndex = np.where(self.indexDates == indexDate)[0][0] - 1

#                     if lastIndexIndex == -1:
#                         expenseRatioCost  = 0
#                     else:
#                         # lastIndexValue = indexDf.loc[self.rebalDates[lastIndexIndex]][indexDf.columns[0]]
#                         lastAllIndexValues = indexDf.loc[self.indexDates[lastIndexIndex+2] : indexDate][indexDf.columns[0]]
#                         expenseRatioCost =  self.getExpenseRatioAvgCost(lastAllIndexValues)

#                     expenseCostDf.loc[indexDate] = expenseRatioCost
#                     moneyInvested = moneyInvested - expenseRatioCost

                if includeExpenseRatio:

                    lastIndexIndex = np.where(advisoryFeesDates == indexDate)[0][0] - 1
                    if lastIndexIndex == -1:
                        sumExpenseCost  = 0
                    else:

                        sumExpenseCost = expenseCostDf.loc[advisoryFeesDates[lastIndexIndex-10] : advisoryFeesDates[lastIndexIndex+1]]['ExpenseRatioCost'].sum()
                        moneyInvested = moneyInvested - sumExpenseCost

                    indexDf.loc[indexDate] -=  expenseRatioCost

                    expenseCostDf.loc[indexDate]['SumExpenseRatioCost'] = sumExpenseCost


                # apriceSr = (priceSr + openSr + highSr + lowSr)/4
                
                sharesSr = self.getRebalanceSharesSr(weightSr, apriceSr, moneyInvested)
                indexDf.loc[indexDate] = (sharesSr * priceSr).sum()
                
                if sharesSr.sum() == 0:
                    logger.info('there are zero shares for the entire reblance' + str(indexDate))

                logger.info("Rebal Date-----------------" + str(indexDate))


            if self.sipDates is not None:
#                logger.info('it is true')
                if indexDate in self.sipDates:
                    weightSr = self.sipWeightDf.loc[indexDate]
                    sharesSr = sharesSr + self.getRebalanceSharesSr(weightSr, priceSr, 100)
                    # logger.info("SIP Date-----------------" + str(indexDate))


        return indexDf, sharesDf, transactionDf, expenseCostDf
    
    
    

    def getSimpleIndex(self, includeTransactionCost = False, indexName = 'SimpleIndexValue', indexStartValue = 100):

        indexDf = pd.DataFrame(index = self.indexDates, columns= [indexName])
        indexDf.index.name = 'Date'
        #initialization of shares (assuming rebalance date [0] is equal to index date [0])
        sharesSr = self.getSimpleSharesSr(self.weightDf.loc[self.rebalDates[0]], self.priceDf.loc[self.rebalDates[0]], indexStartValue)
#        oldSharesSr = pd.Series(0, index = sharesSr.index)

#         moneyDebitedDf = pd.DataFrame(0, index = self.indexDates, columns = ['MoneyDebited'])
#         moneyDebitedDf.index.name = 'Date'

        sharesDf = pd.DataFrame(index = self.indexDates, columns= self.weightDf.columns)
#         oldSharesDf= pd.DataFrame(index = self.indexDates, columns= self.weightDf.columns)
        transactionDf = pd.DataFrame(index = self.rebalDates, columns= ['TransactionCost'])

        includeExpenseRatio = self.keyWordArgs.get('ExpensePercentage') is not None
        expenseCostDf = pd.DataFrame()


        if includeExpenseRatio :
            advisoryFeesDates = self.keyWordArgs.get('ExpenseRatioDates')
            expenseCostDf = pd.DataFrame(index = advisoryFeesDates, columns= ['ExpenseRatioCost', 'SumExpenseRatioCost'])
        
        lastRebal = self.rebalDates[0]
        
        for indexDate in self.indexDates:

            priceSr = self.priceDf.loc[indexDate]

            if sharesSr.sum() == 0:
                dateIndxx = np.where(self.indexDates == indexDate)[0][0] -1
                if dateIndxx == -1:
                    indexDf.loc[indexDate] = indexStartValue
                else:
                    prevIndexDate  = self.indexDates[dateIndxx]
                    indexDf.loc[indexDate] = indexDf.loc[prevIndexDate]
            else:
                simpleRet = (sharesSr * priceSr).sum()
                indexDf.loc[indexDate] = simpleRet

#             if not oldSharesSr.equals(sharesSr):
#                 transactionValues = self.getTransactionValue(oldSharesSr, sharesSr, priceSr)
#                 absTransValue = transactionValues[0]
#                 transactionCost = self.getTransactionCost(absTransValue)
#                 moneyDebited = transactionValues[1] + transactionCost
#                 moneyDebitedDf.loc[indexDate] = moneyDebited

#            display(sharesSr)
            sharesDf.loc[indexDate][sharesSr.index] = sharesSr.values
#             oldSharesDf.loc[indexDate][oldSharesSr.index] = oldSharesSr.values

#             oldSharesSr = sharesSr

            if includeExpenseRatio:
#                    logger.info(moneyInvested)

                if indexDate in advisoryFeesDates:
                    
                    logger.info(indexDate)

                    lastIndexIndex = np.where(advisoryFeesDates == indexDate)[0][0] - 1

                    if lastIndexIndex == -1:
                        expenseRatioCost  = 0
                        sumExpenseCost = 0
                    else:
                        lastIndexDates = np.where(self.indexDates == advisoryFeesDates[lastIndexIndex])[0][0] + 1
                        # lastIndexValue = indexDf.loc[self.rebalDates[lastIndexIndex]][indexDf.columns[0]]
                        lastAllIndexValues = indexDf.loc[self.indexDates[lastIndexDates] : indexDate][indexDf.columns[0]]
                        # logger.info(lastAllIndexValues.head())
                        
                        expenseRatioCost =  self.getExpenseRatioAvgCost(lastAllIndexValues)
                        
                        expenseCostDf.loc[indexDate]['ExpenseRatioCost'] = expenseRatioCost
                        # moneyInvested = moneyInvested - expenseRatioCost
                        # indexDf.loc[indexDate] -=  expenseRatioCost
                        # sumExpenseCost = expenseCostDf['ExpenseRatioCost'].rolling(12, min_periods=1).sum().loc[indexDate]
                        sumExpenseCost = expenseCostDf['ExpenseRatioCost'].loc[lastRebal:indexDate].sum()
                        
                        # moneyInvested = moneyInvested - expenseRatioCost
                        expenseCostDf.loc[indexDate]['SumExpenseRatioCost'] = sumExpenseCost

                indexDf.loc[indexDate] -=  sumExpenseCost
                    

                    # logger.info('expense ratio reduced at--------------------' + str(indexDate))

            # check for rebalance date (date triggering)
            if indexDate in self.rebalDates:
                weightSr = self.weightDf.loc[indexDate]
                moneyInvested = indexDf.loc[indexDate][indexDf.columns[0]]
                currentIndexValue = indexDf.loc[indexDate][indexDf.columns[0]]
                lastRebal = indexDate   
                sumExpenseCost =0 

#                 if includeTransactionCost:

# #                    logger.info(weightSr)
# #                    logger.info(priceSr)
# #                    logger.info(moneyInvested)
# #
#                     newShareSr = self.getRebalanceSharesSr(weightSr, priceSr, moneyInvested)

#                     absoluteDifferenceSum = self.getTransactionValue(sharesSr, newShareSr, priceSr)[0]
#                     transactionCostRebal = self.getTransactionCost(absoluteDifferenceSum)
#                     transactionDf.loc[indexDate] = transactionCostRebal
#                     moneyInvested = moneyInvested - transactionCostRebal

#                 if includeExpenseRatio:
# #                    logger.info(moneyInvested)

#                     lastIndexIndex = np.where(self.indexDates == indexDate)[0][0] - 1

#                     if lastIndexIndex == -1:
#                         expenseRatioCost  = 0
#                     else:
#                         # lastIndexValue = indexDf.loc[self.rebalDates[lastIndexIndex]][indexDf.columns[0]]
#                         lastAllIndexValues = indexDf.loc[self.indexDates[lastIndexIndex+2] : indexDate][indexDf.columns[0]]
#                         expenseRatioCost =  self.getExpenseRatioAvgCost(lastAllIndexValues)

#                     expenseCostDf.loc[indexDate] = expenseRatioCost
#                     moneyInvested = moneyInvested - expenseRatioCost
                
                # expense ratio     
                # if includeExpenseRatio:

                #     lastIndexIndex = np.where(advisoryFeesDates == indexDate)[0][0] - 1
                #     if lastIndexIndex == -1:
                #         sumExpenseCost  = 0
                #     else:

                #         sumExpenseCost = expenseCostDf.loc[advisoryFeesDates[lastIndexIndex-10] : advisoryFeesDates[lastIndexIndex+1]]['ExpenseRatioCost'].sum()
                #         # moneyInvested = moneyInvested - expenseRatioCost
                #         moneyInvested = moneyInvested - sumExpenseCost

                #     indexDf.loc[indexDate] -=  expenseRatioCost

                    # expenseCostDf.loc[indexDate]['SumExpenseRatioCost'] = sumExpenseCost



                indexDf.loc[indexDate] = moneyInvested
                sharesSr = self.getRebalanceSharesSr(weightSr, priceSr, moneyInvested)

                if sharesSr.sum() == 0:
                    logger.info('there are zero shares for the entire reblance' + str(indexDate))

                logger.info("Rebal Date-----------------" + str(indexDate))


            if self.sipDates is not None:
#                logger.info('it is true')
                if indexDate in self.sipDates:
                    weightSr = self.sipWeightDf.loc[indexDate]
                    sharesSr = sharesSr + self.getRebalanceSharesSr(weightSr, priceSr, 100)
                    # logger.info("SIP Date-----------------" + str(indexDate))


        return indexDf, sharesDf, transactionDf, expenseCostDf

    def getTripleBoxSimpleIndex(self, liquidBeesPriceDf, conditionDf, startMoney):

        indexDf = pd.DataFrame(index = self.indexDates, columns= ['TripleBoxSimpleIndex'])
        indexDf.index.name = 'Date'
        sharesSr = self.getSimpleSharesSr(self.weightDf.loc[self.rebalDates[0]], self.priceDf.loc[self.rebalDates[0]], startMoney)

        drawdownIndexDf = pd.DataFrame(index = self.indexDates, columns= ['DrawDown'])
        liquidbeesSharesDf = pd.DataFrame(index= self.indexDates, columns=['LiquidBeesShare'])

#        lastMoneyInvested = startMoney
        highestIndexValue = startMoney
        lastDrawDownIndex = 0
        liquidBeesShare = 0

        sharesDf = pd.DataFrame(index = self.indexDates, columns= self.weightDf.columns)

        for indexDate in self.indexDates:

            priceSr = self.priceDf.loc[indexDate]
            liquidBeesPrice = liquidBeesPriceDf.loc[indexDate]['Reliance_Liquid_Bees']

            indexContributionSr = sharesSr * priceSr
            simpleRet = indexContributionSr.sum()
            liquidBeesRet = liquidBeesShare * liquidBeesPrice

            indexDf.loc[indexDate]['TripleBoxSimpleIndex'] = simpleRet + liquidBeesRet
#            drawDown = 1- (indexDf.loc[indexDate]['TripleBoxSimpleIndex'] / lastMoneyInvested)
            drawDown = 1-(indexDf.loc[indexDate]['TripleBoxSimpleIndex'] / highestIndexValue)
            drawDownIndex = conditionDf.index.get_loc(drawDown, method = 'ffill')

            highestIndexValue = np.maximum(highestIndexValue, indexDf.loc[indexDate]['TripleBoxSimpleIndex'])

            drawdownIndexDf.loc[indexDate]['DrawDown'] = drawDownIndex
            liquidbeesSharesDf.loc[indexDate]['LiquidBeesShare'] = liquidBeesShare

            sharesDf.loc[indexDate][sharesSr.index] = sharesSr.values

            if drawDownIndex - lastDrawDownIndex > 0 :

                weightSr = indexContributionSr.div(simpleRet)
                moneyInvested = indexDf.loc[indexDate]['TripleBoxSimpleIndex']
                outputTuple = self.getTripleBoxSharesSr(moneyInvested, conditionDf, drawDownIndex, liquidBeesPrice, weightSr, priceSr)
                sharesSr = outputTuple.get('PortfolioShare')
                liquidBeesShare = outputTuple.get('LiquidbeesShare')
                lastDrawDownIndex = drawDownIndex



            if indexDate in self.rebalDates:

                weightSr = self.weightDf.loc[indexDate]
                moneyInvested = indexDf.loc[indexDate]['TripleBoxSimpleIndex']
                sharesSr = self.getRebalanceSharesSr(weightSr, priceSr, moneyInvested)
#                 sharesSr = output.get('PortfolioShare')
                liquidBeesShare = 0
                # variable initialization at each rebalance
                lastDrawDownIndex = 0
#                lastMoneyInvested = moneyInvested
                highestIndexValue = moneyInvested

        return indexDf, drawdownIndexDf, liquidbeesSharesDf, sharesDf

    def getFixedWeightRebalance(self, weightSr, indexStartValue = 100, indexName = 'SimpleIndexValue', thresholdValue = 0.05):
        indexDf = pd.DataFrame(index = self.indexDates, columns= [indexName])
        indexDf.index.name = 'Date'
        sharesSr = self.getSimpleSharesSr(weightSr, self.priceDf.loc[self.indexDates[0]], indexStartValue)
#        oldSharesSr = pd.Series(0, index = sharesSr.index)
        sharesDf = pd.DataFrame(index = self.indexDates, columns= self.priceDf.columns)

        lastPriceSr = self.priceDf.loc[self.indexDates[0]]
        allDropDates = []

        deltaPriceDf = pd.DataFrame(index = self.indexDates, columns= self.priceDf.columns)
        for indexDate in self.indexDates:

            priceSr = self.priceDf.loc[indexDate]
            minDrop = np.min(priceSr.div(lastPriceSr))
            maxDrop = np.max(priceSr.div(lastPriceSr))

            deltaSr = priceSr.div(lastPriceSr) - 1

            deltaPriceDf.loc[indexDate] = deltaSr

            simpleRet = (sharesSr * priceSr).sum()
            indexDf.loc[indexDate] = simpleRet

            sharesDf.loc[indexDate][sharesSr.index] = sharesSr.values

            if minDrop <= 1 - thresholdValue or maxDrop >= 1 +  thresholdValue:

                sharesSr = self.getSimpleSharesSr(weightSr, priceSr, indexDf.loc[indexDate][indexDf.columns[0]])
                lastPriceSr = priceSr
                logger.info("DrawDownHit Date-----------------" + str(indexDate))
                allDropDates.append(indexDate)

        priceChangesDf = deltaPriceDf.loc[allDropDates]



        return indexDf, sharesDf, deltaPriceDf, allDropDates, priceChangesDf


















    def getDivAdjustedIndex(self, dividendDf, indexName = 'SimpleIndexValue'):

        divAdjindexDf = pd.DataFrame(index = self.indexDates, columns= [indexName])
        indexDf = pd.DataFrame(index = self.indexDates, columns= ['IndexValue'])
        #initialization of shares (assuming rebalance date [0] is equal to index date [0])
        sharesSr = self.getSimpleSharesSr(self.weightDf.loc[self.rebalDates[0]], self.priceDf.loc[self.rebalDates[0]], 100)

        # put it as an argument in the function
        lastDividendValue = 0
        for indexDate in self.indexDates:

            priceSr = self.priceDf.loc[indexDate]
            divSr = dividendDf.loc[indexDate]

            simpleRet = (sharesSr * priceSr).sum()
            divRet = (sharesSr * divSr).sum()

            indexDf.loc[indexDate] = simpleRet
            divAdjindexDf.loc[indexDate] = simpleRet + divRet + lastDividendValue
            lastDividendValue = divRet + lastDividendValue


            # check for rebalance date (date triggering)
            if indexDate in self.rebalDates:
                moneyInvested = indexDf.loc[indexDate]['IndexValue']
                weightSr = self.weightDf.loc[indexDate]
                # updating three values at the time of rebalance
                sharesSr = self.getRebalanceSharesSr(weightSr, priceSr, moneyInvested)

                if sharesSr.sum() == 0:
                    logger.info('there are zero shares for the entire reblance' + str(indexDate))

        return divAdjindexDf



    def getDividendReinvestedIndex(self, dividendDf, indexName = 'SimpleIndexValue'):

        indexDf = pd.DataFrame(index = self.indexDates, columns= [indexName])
        #initialization of shares (assuming rebalance date [0] is equal to index date [0])
        sharesSr = self.getSimpleSharesSr(self.weightDf.loc[self.rebalDates[0]], self.priceDf.loc[self.rebalDates[0]], 100)

        lastDividendValue = 0
        for indexDate in self.indexDates:

            priceSr = self.priceDf.loc[indexDate]
            divSr = dividendDf.loc[indexDate]

            simpleRet = (sharesSr * priceSr).sum()
            divRet = (sharesSr * divSr).sum()
            indexRet = simpleRet + divRet + lastDividendValue
            lastDividendValue = divRet + lastDividendValue
            indexDf.loc[indexDate] = indexRet

            # check for rebalance date (date triggering)
            if indexDate in self.rebalDates:

                moneyInvested = indexDf.loc[indexDate][indexName]
                weightSr = self.weightDf.loc[indexDate]
                # updating three values at the time of rebalance
                sharesSr = self.getSimpleSharesSr(weightSr, priceSr, moneyInvested)
                lastDividendValue = 0

        return indexDf

# In[35]:

class IndexAnalytics:

    def __init__(self, indexDf = None):

        # if indexDf is not None:
        #     indexDf.reset_index(inplace= True)
        #     indexDf['Month'] = indexDf['Date'].dt.month
        #     indexDf['Year'] = indexDf['Date'].dt.year
        self.indexDf = indexDf
        
    def getSimpleCGR(self, indexDf = None):
        
        if indexDf is None:
            indexDf = self.indexDf
        
        cagr = (indexDf.iloc[-1]/indexDf.iloc[0])**(250 / indexDf.shape[0]) - 1
        
        return cagr
    
    def getSimpleSTD(self, indexDf = None):
        if indexDf is None:
            indexDf = self.indexDf
        
        std = indexDf.pct_change(1)[1:].std()*np.sqrt(250)
        
        return std
    
    def getDownsideDeviation(self, indexDf = None):
        if indexDf is None:
            indexDf = self.indexDf
        
        indexRet = indexDf.pct_change(1)
        negativeReturn = indexRet.where(indexRet <0, 0)
        squareNegativeReturn = negativeReturn.pow(2)
        meanExSr = squareNegativeReturn.mean()
        sqrtSr = np.sqrt(meanExSr)  
        return sqrtSr
    
    
    def getRollingSharpe(self, window = 250 , indexDf = None):
        if indexDf is None:
            indexDf = self.indexDf
        
        indexRet = indexDf.pct_change(1)
        rollingAvg = indexRet.rolling(window).mean()
        rollingStd = indexRet.rolling(window).std()
        
        rollingSharpe = rollingAvg.mul(250).div(rollingStd.mul(np.sqrt(250)))
        
        return rollingSharpe 
    
    def getRollingSortino(self, window = 250 , indexDf = None):
        if indexDf is None:
            indexDf = self.indexDf
        
        indexRet = indexDf.pct_change(1)
        rollingAvg = indexRet.rolling(window).mean()
        rollingTDD = self.getDownsideDeviation(indexDf)
        
        rollingSortino = rollingAvg.div(rollingTDD)
        return rollingSortino
    
    
    def rollingReturns(self, window = 250, indexDf = None):
        if indexDf is None:
            indexDf = self.indexDf
            
        indexRet = indexDf.pct_change(1)    
        rollingAvg = indexRet.rolling(window).mean()
        return rollingAvg.mul(250)
    
    
    # def rollingCgr(self, )     
    


    def xnpv(self, rate,cashflows):
        chron_order = sorted(cashflows, key = lambda x: x[0])
        t0 = chron_order[0][0]
        return sum([cf/(1+rate)**((t-t0).days/365.0) for (t,cf) in chron_order])
    
    
    def xirr(self , cashflows,guess=0.1):
        
        return sco.newton(lambda r: self.xnpv(r,cashflows),guess)
            
        
    def getCAGRBWDates(self, indexDf = None, sDate = None, eDate = None):
        
        if indexDf is None:
            indexDf = self.indexDf
            
        startValueIndex = indexDf.index.get_loc(sDate, method = 'ffill')
        eDIndex = indexDf.index.get_loc(eDate, method = 'ffill')
        
        cagrs = []
        for i in range(0, len(indexDf.columns)):
            startValue = indexDf.iloc[startValueIndex][indexDf.columns[i]]
            ybValue = indexDf.iloc[eDIndex][indexDf.columns[i]]    
            cagrValue = (ybValue/ startValue ) ** (250/(indexDf.iloc[startValueIndex :eDIndex].shape[0] + 1)) - 1   
            cagrs.append(cagrValue)
            
        return cagrs
    
    def getCAGR(self, indexDf = None, sDate = None, year = 5):
        
        if indexDf is None:
            indexDf = self.indexDf
            
        if sDate is None:
            sDate = indexDf.iloc[-1].name
            
        yearBack = sDate + pd.DateOffset(months = -1*year*12)
        startValueIndex = indexDf.index.get_loc(sDate, method = 'ffill')
        ybValueIndex = indexDf.index.get_loc(yearBack, method = 'ffill')
        
        cagrs = []
        for i in range(0, len(indexDf.columns)):
            startValue = indexDf.iloc[startValueIndex][indexDf.columns[i]]
            ybValue = indexDf.iloc[ybValueIndex][indexDf.columns[i]]    
            cagrValue = (startValue / ybValue) ** (1/year) - 1   
            cagrs.append(cagrValue)
            
        return cagrs
    
    def getStd(self, tradingDatesDf, indexDf = None, sDate = None, year = 5):
        
        if indexDf is None:
            indexDf = self.indexDf
            
        if sDate is None:
            sDate = indexDf.iloc[-1].name
            
        yearBack = sDate + pd.DateOffset(months = -1*year*12)
        
        
        # tradingDatesDf = excelReaderfObj.getTradingDatesDataFrame(excelFile= , sheetName = 'Sheet1')
        
        
        mergeObj = Merger()    
        
        tIndex = tradingDatesDf.set_index('Date').index.get_loc(yearBack, method = 'bfill')
        
        # logger.info(tIndex)
        subTradingDf = tradingDatesDf.iloc[tIndex:]
        indexMergedDf = mergeObj.getMergedBymethodDf(subTradingDf, indexDf)
        # logger.info(indexMergedDf.head())
        
        returnMDf = indexMergedDf.pct_change(1)
        startValueIndex = returnMDf.index.get_loc(sDate, method = 'bfill')
        ybValueIndex = returnMDf.index.get_loc(yearBack, method = 'bfill') 
        
        # logger.info(star)
        
        stdRetDf = returnMDf.iloc[ybValueIndex : startValueIndex +1]
        
        # logger.info(stdRetDf.head())
        # logger.info(stdRetDf.tail())
        
        stds = []
        for i in range(0, len(indexDf.columns)):
            stdValue = stdRetDf.std()[stdRetDf.columns[i]]*np.sqrt(250)
            stds.append(stdValue)
        
        return stds
        
        
        
        

    def getYearlyAverageReturn(self, indexDf = None, numberOfDays = 252):

        if indexDf is None:
            indexDf = self.indexDf

        returnDf = indexDf.pct_change()
        averageRetDf = returnDf.group_by('Year').mean()
        return averageRetDf * numberOfDays

    def getYearlyStd(self, indexDf = None, numberOfDays = 252):
        if indexDf is None:
            indexDf = self.indexDf

        returnDf = indexDf.pct_change()
        stdRetDf = returnDf.group_by('Year').std()
        return stdRetDf * np.sqrt(numberOfDays)

    def getYearlySharpe(self, indexDf = None, numberOfDays = 252):
        if indexDf is None:
            indexDf = self.indexDf

        averageRetDf = self.getYearlyAverageReturn(indexDf, numberOfDays)
        stdDf = self.getYearlyVolatility(indexDf, numberOfDays)
        sharpeDf = averageRetDf.div(stdDf)
        return sharpeDf

    # def getPyfolioSheet(self, indexDf= None):
    #     indexRet = indexDf[indexDf.columns[0]].pct_change()[1:]
    #     indexRetPlot = pf.create_returns_tear_sheet(indexRet, return_fig=True)
    #     return indexRetPlot

#    def plotStrategies(self, )

#    def plotStrategies(self, *strategiesDf)

# =============================================================================
#     def getYearlySkewness(self,indexDf = None)
#
#
#     def getYearlyKutosis(self, indexDf = None)
#
#
#     def getRollingAvergeReturn(self, indexDf = None)
#
#     def getRollingStd(self, indexDf = None)
#
#     def getTimeSeriesPlots(self):
#
#     def getHistograms(self):
#
#     def getDistribution(self):
# =============================================================================


# In[ ]:

"""
class WriteSelectedStocksWeights:

    def __init__(self, excelFile= None):
        self.excelFile = excelFile

    def writeSelectedStocksWeights(self, weightDf, selectedStocksDf, sheetName):


        transWeightDf = weightDf.T
        transSelectedDf = selectedStocksDf.T

        writeTransWeightDf = pd.DataFrame(np.where(transWeightDf != 0, transWeightDf, ""), index= transWeightDf.index, columns= transWeightDf.columns)
#         writeTransSelectedDf = pd.DataFrame(np.where(transSelectedDf ==1, transSelectedDf.columns, ""), index= transSelectedDf.index, columns= transSelectedDf.columns)

#         transSelectedDf.apply(lambda col : np.where(col ==1 , tradingDatesDf.index, "") )

        for rebalanceDate in transSelectedDf.columns:
            selectedStocksArr = np.where(transSelectedDf[rebalanceDate] == 1, transSelectedDf.index, "")
            transSelectedDf[rebalanceDate] = selectedStocksArr


        writeTransWeightDf.to_excel(self.excelFile, sheet_name = 'Weights' + sheetName)

        book = load_workbook(self.excelFile)
        writer = pd.ExcelWriter(self.excelFile, engine = 'openpyxl')
        writer.book = book

        transSelectedDf.to_excel(writer, sheet_name = 'Stocks' + sheetName)

        writer.save()
        writer.close()

    def writeSelectedStocksFromWeights(self, excelFile= None, sheetName= 'Sheet1', outputSheetName= "", weightInputDf = None, outputFile = None):

        if excelFile is None:
            weightTransDf = weightInputDf
        else:
            excelReaderObj = ExcelInputReader(excelFile)
            weightTransDf = excelReaderObj.getDataFrameWithoutDate(sheetName = sheetName)

        logger.info(weightTransDf.head())

        weightDf = weightTransDf.fillna("").T
        selectedStocksDf = weightDf.apply(lambda col : np.where(col == "", "", weightDf.index))

        book = load_workbook(outputFile)
        writer = pd.ExcelWriter(outputFile, engine = 'openpyxl')
        writer.book = book

        weightDf.to_excel(writer, sheet_name = 'Weight' + outputSheetName)
        selectedStocksDf.to_excel(writer, sheet_name = 'Stocks' + outputSheetName)


        writer.save()
        writer.close()

    def writeSelectedStocksFromWeightsV2(self, excelFile= None, sheetName= 'Sheet1', outputSheetName= "", weightInputDf = None, outputFile = None):

        if excelFile is None:
            weightTransDf = weightInputDf
        else:
            excelReaderObj = ExcelInputReader(excelFile)
            weightTransDf = excelReaderObj.getDataFrameWithoutDate(sheetName = sheetName)

        logger.info(weightTransDf.head())

        weightDf = weightTransDf.fillna("").T
        selectedStocksDf = weightDf.apply(lambda col : np.where(col == "", "", weightDf.index))

        selectedStocksDf.columns=weightDf.iloc[0,:]
        weightDf.columns=weightDf.iloc[0,:]

        selectedStocksDf=selectedStocksDf.iloc[1:,:]
        weightDf=weightDf.iloc[1:,:]


        book = load_workbook(outputFile)
        writer = pd.ExcelWriter(outputFile, engine = 'openpyxl')
        writer.book = book

        weightDf.to_excel(writer, sheet_name = 'Weight' + outputSheetName,index=False)
        selectedStocksDf.to_excel(writer, sheet_name = 'Stocks' + outputSheetName,index=False)
        weightDf.to_excel(writer, sheet_name = 'Stocks' + outputSheetName,index=False,startrow=1000,header=False)

        writer.save()
        writer.close()


"""

#%%
