# -*- coding: utf-8 -*-
"""
Created on Fri Jun 28 13:43:44 2019

@author: manur
"""

#%%

from scipy.stats import binom
import pandas as pd
import numpy as np

#%%
class ProspectTheory:
    
    def __init__(self, valueFunctionArgArr = None, probWeighingArgArr = None, pastReturnSr = None):
        self.valueFunctionArgArr = valueFunctionArgArr
        self.probWeighingArgArr = probWeighingArgArr
        self.pastReturnSr = pastReturnSr
    
    def getValueFunctionExp(self, returnValue , valueFunctionArgArr= None):
        
        # first argument is power value second is multiplier in case of negative return
        # power value :(0,1) multiplier > 1 
        if valueFunctionArgArr is None:
            valueFunctionArgArr = self.valueFunctionArgArr
            
        
        alpha = valueFunctionArgArr[0]
        lambdaValue = valueFunctionArgArr[1]
        
#        display(returnValue)
        
        if returnValue < 0 :
            valueFunc = (-lambdaValue) * (-returnValue)**alpha
        
        else:
            valueFunc = returnValue**alpha
            
        return valueFunc
            
    def getProbabilityWeighing(self, probabilityValue, returnValueSign, probWeighingArgArr = None):
        
        #first argument is for positive return value and second is for negative return
        # both should be (0,1)
        if probWeighingArgArr is None:
            probWeighingArgArr = self.probWeighingArgArr
        
        posArg = probWeighingArgArr[0]
        negArg = probWeighingArgArr[1]
        
        if returnValueSign >= 0:
            power = posArg
        else:
            power = negArg
            
        
#        print(probabilityValue)
        
        firstTerm = probabilityValue**power
        secondTerm = (1-probabilityValue)**power
        
        probabilityWeight = firstTerm / ((firstTerm +  secondTerm) ** (1/power))
        return probabilityWeight
    
     
    def getProspectWeightValue(self, probPastRetSr, pastReturnSr = None, probWeighingArgArr = None , valueFunctionArgArr= None):
        
        if pastReturnSr is None:
            pastReturnSr = self.pastReturnSr
        
#        display(probPastRetSr)
#        display(pastReturnSr)
        
        pastRetSortedSr = pastReturnSr.sort_values(ascending=True)
        # probability of past Return series should have index in the same order as past return series sorted
        
        if pastRetSortedSr.size != probPastRetSr.size:
            print('----------------error in size--------------')
        
        probPastRetSortedSr = probPastRetSr.reindex(pastRetSortedSr.index)
        
        for boolVal in pastRetSortedSr.index == probPastRetSortedSr.index:
            
            if not boolVal:
                print('----------------error in index sort the arr----------')
                
        
        prospectWeights = []
        
        for dateIndex in range(pastRetSortedSr.size):
            
            returnValue = pastRetSortedSr.iloc[dateIndex]
            try:
                returnSign = np.sign(returnValue)
            except:
                print(returnSign)
            
            if returnSign < 0:
                oneLessCumSum = probPastRetSortedSr.iloc[:dateIndex].sum()
                cumSum =  probPastRetSortedSr.iloc[:dateIndex+1].sum()
            
            else:
                cumSum = probPastRetSortedSr.iloc[dateIndex:].sum()
                oneLessCumSum = probPastRetSortedSr.iloc[dateIndex+1:].sum() 
            
            probWeightCumSum = self.getProbabilityWeighing(cumSum, returnSign, probWeighingArgArr)
            probWeightLessCumSum = self.getProbabilityWeighing(oneLessCumSum, returnSign, probWeighingArgArr)
            
            prospectWeight = probWeightCumSum - probWeightLessCumSum
            propspectValueFunction = self.getValueFunctionExp(returnValue, valueFunctionArgArr)
            prospectWeightValue = prospectWeight * propspectValueFunction
            prospectWeights.append(prospectWeightValue)
        
        prospectWeightSr = pd.Series(prospectWeights, index = pastRetSortedSr.index)
        
        return prospectWeightSr 

#%%

class ProbabilityOfPastReturn:
    # output is a series with equal length as input and sum must be 1 
    
    def __init__(self, pastReturnSr = None):
        self.pastReturnSr = pastReturnSr
    
    def getEqualProbabilities(self, pastReturnSr = None):
        
        if pastReturnSr is None:
            pastReturnSr = self.pastReturnSr
            
        nonNanDays = pastReturnSr.count()
                
        equalWeight = []
        for ret in pastReturnSr:
            if np.isnan(ret):
                equalWeight.append(0)
            else:
                equalWeight.append(1/ nonNanDays)
            
        equalWeightSr = pd.Series(equalWeight, index= pastReturnSr.index)
        return equalWeightSr
    
    def getIncreasingProbabilities(self, pastReturnSr = None):
        
        if pastReturnSr is None:
            pastReturnSr = self.pastReturnSr
            
        increaseWeight = []
        index = 1
        for ret in pastReturnSr:
            if np.isnan(ret):
                increaseWeight.append(0)
            else:
                increaseWeight.append(index)
            index = index +1 
        
        increaseWeightArr = np.divide(increaseWeight, np.sum(increaseWeight))
        increaseWeightSr = pd.Series(increaseWeightArr, index= pastReturnSr.index)
        return increaseWeightSr
    
    def getIncreasingBinomialProbabilities(self, pastReturnSr = None):
        
        binomialProb = self.getBinomialProbabilities(pastReturnSr)
        increaseProb = self.getIncreasingProbabilities(pastReturnSr)
        
        increaseBinomial = increaseProb.mul(binomialProb)
        
        increaseBinomialWeightSr = increaseBinomial.div(increaseBinomial.sum())
        return increaseBinomialWeightSr
        
        
      
    def getBinomialProbabilities(self, pastReturnSr = None):
        
        if pastReturnSr is None:
            pastReturnSr = self.pastReturnSr
        
        numberOfDays = pastReturnSr.size
        nonNanDays = pastReturnSr.count()
        binomialObj = binom(nonNanDays-1, 0.5)
        
        pastRetSortedSr = pastReturnSr.sort_values(ascending=True)
        
        binomWeight = []
        
        for dayIndex in range(nonNanDays):
            
            binomWeight.append(binomialObj.pmf(dayIndex))
        
        for nanIndex in range(numberOfDays - nonNanDays):
            binomWeight.append(0)
        
        binomWeightSr = pd.Series(binomWeight, index = pastRetSortedSr.index)
        return binomWeightSr

#%%    
    
    
    
    