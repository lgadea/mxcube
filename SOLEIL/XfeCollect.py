#!/usr/bin/env python
# -*- coding: utf-8 -*-


import optparse
import time
import PyTango
import pylab
import numpy
import os
import pickle
import math
from xabs_lib import *
    
#sys.exit()

#md2             = PyTango.DeviceProxy('i11-ma-cx1/ex/md2')
#ketek           = PyTango.DeviceProxy('i11-ma-cx1/dt/dtc-mca_xmap.1')
#counter         = PyTango.DeviceProxy('i11-ma-c00/ca/cpt.2')


class XfeCollect(object):
    def __init__(self, integrationTime = 1., directory = '/tmp', prefix = 'test', sessionId = None, sampleId = None):
        self.integrationTime = integrationTime
        self.directory = directory
        self.prefix = prefix
        self.sessionId = sessionId
        self.sampleId = sampleId
        self.filename = os.path.join(self.directory, self.prefix + '_fxe.png') #filename
        
        self.md2     = PyTango.DeviceProxy('i11-ma-cx1/ex/md2')
        self.ketek   = PyTango.DeviceProxy('i11-ma-cx1/dt/dtc-mca_xmap.1')
        #self.counter = PyTango.DeviceProxy('i11-ma-c00/ca/cpt.2')
        self.obx     = PyTango.DeviceProxy('i11-ma-c04/ex/obx.1')
        self.ble     = PyTango.DeviceProxy('i11-ma-c00/ex/beamlineenergy')
        self.monodevice = PyTango.DeviceProxy('i11-ma-c03/op/mono1')
        self.optimize = None
        self.test = False
        self.ketek.presettype = 1
        self.ketek.peakingtime = 2.5
        self.channelToeV = 10. #self.ketek.dynamicRange / len(self.ketek.channel00)
        
        try:
            os.mkdir(directory)
        except OSError, e:
            print e
    
    def wait(self, device):
        while device.state().name == 'MOVING':
            time.sleep(.1)
        
        while device.state().name == 'RUNNING':
            time.sleep(.1)
            
    def transmission(self, x=None):
        '''Get or set the transmission'''
        #if self.test: return 0
        Fp = PyTango.DeviceProxy('i11-ma-c00/ex/fp_parser')
        if x == None:
            return Fp.TrueTrans_FP

        Ps_h = PyTango.DeviceProxy('i11-ma-c02/ex/fent_h.1')
        Ps_v = PyTango.DeviceProxy('i11-ma-c02/ex/fent_v.1')
        Const = PyTango.DeviceProxy('i11-ma-c00/ex/fpconstparser')

        truevalue = (2.0 - math.sqrt(4 - 0.04 * x)) / 0.02

        newGapFP_H = math.sqrt(
            (truevalue / 100.0) * Const.FP_Area_FWHM / Const.Ratio_FP_Gap)
        newGapFP_V = newGapFP_H * Const.Ratio_FP_Gap

        Ps_h.gap = newGapFP_H
        Ps_v.gap = newGapFP_V
        
    def secondaryTransmission(self, x=None):
        '''Get or set the transmission by secondary slits'''
        #if self.test: return 0
        Fp = PyTango.DeviceProxy('i11-ma-c00/ex/fp_parser')
        if x == None:
            return Fp.TrueTrans_FP

        Ss_h = PyTango.DeviceProxy('i11-ma-c04/ex/fent_h.2')
        Ps_v = PyTango.DeviceProxy('i11-ma-c04/ex/fent_v.2')
        Const = PyTango.DeviceProxy('i11-ma-c00/ex/fpconstparser')

        truevalue = (2.0 - math.sqrt(4 - 0.04 * x)) / 0.02

        newGapFP_H = math.sqrt(
            (truevalue / 100.0) * Const.FP_Area_FWHM / Const.Ratio_FP_Gap)
        newGapFP_V = newGapFP_H * Const.Ratio_FP_Gap

        Ps_h.gap = newGapFP_H
        Ps_v.gap = newGapFP_V
        
        
    def go10eVabovetheEdge(self):
        self.ble.write_attribute('energy', self.thEdge + 0.01)
        self.wait(self.ble)
        #self.monodevice.write_attribute('energy', self.thEdge + 0.01)
        #self.wait(self.monodevice)
            
    def getEdgefromXabs(self, el, edge):
        edge = edge.upper()
        roi_center = McMaster[el]['edgeEnergies'][edge + '-alpha']
        if edge == 'L':
            edge = 'L3'
        e_edge = McMaster[el]['edgeEnergies'][edge]
        return (e_edge, roi_center)    
        
    def optimizeTransmission(self, element, edge):
        self.optimize = True
        e_edge, roi_center = self.getEdgefromXabs(element, edge)
        self.thEdge = e_edge
        self.element = element
        self.edge = edge
        
        self.go10eVabovetheEdge()
        self.setTransmission = 0.5
        self.transmission(self.setTransmission)
        self.inverseDeadTime = 0.
        self.tentativeDeadTime = 1.
        self.lowBoundary = 0
        self.highBoundary = None
        k = 0
        self.obx.Open()
        self.insertDetector()
        #while not .75 < self.inverseDeadTime < .85:
        while not .6 < self.tentativeDeadTime < .65:
            if self.transmission() > 4:
                break
            
            self.measureSpectrum()
            ICR = self.ketek.inputCountRate00
            OCR = self.ketek.outputCountRate00
            eventTime = self.ketek.realTime00
            self.inverseDeadTime = 1. - (OCR / ICR) # * eventTime
            self.tentativeDeadTime = (OCR / ICR)
            k+=1
            print 'Cycle %d, deadtime is %f' % (k, self.inverseDeadTime)
            self.adjustTransmission()
        print 'Transmission optimized at %s, the deadtime is %s' % (self.currentTransmission, self.inverseDeadTime)
        print 'Tentative real deadtime is %f' % self.tentativeDeadTime
        self.obx.Open()
        self.extractDetector()
        
    def adjustTransmission(self):
        self.currentTransmission = self.transmission()
        self.previousTransmission = 0
        print 'current transmission is %f' % self.currentTransmission
        print 'the deadtime is %f' % self.inverseDeadTime
        if self.tentativeDeadTime < 0.6:
            self.highBoundary = self.setTransmission
            self.setTransmission -= (self.highBoundary - self.lowBoundary)/2.
        else:
            self.lowBoundary = self.setTransmission
            if self.highBoundary is None:
                self.setTransmission *= 2
            else:
                self.setTransmission += (self.highBoundary - self.lowBoundary)/2.
        self.transmission(self.setTransmission)
        self.previousTransmission = self.currentTransmission
        
        
    def canSpectrum(self):
        return True
        
    def setIntegrationTime(self, integrationTime = 1.):
        #self.counter.integrationTime = integrationTime
        self.ketek.presetvalue = int(integrationTime)
        
    def setROI(self, roi_debut = 0., roi_fin = 2048.):
        self.ketek.SetROIs(numpy.array((roi_debut, roi_fin)))
        #pass
    
    def insertDetector(self):
        self.md2.write_attribute('FluoDetectorBack', 0)
        time.sleep(5)
    
    def extractDetector(self):
        self.md2.write_attribute('FluoDetectorBack', 1)
        time.sleep(5)
    
    def startXfeSpectrum(self):
        self.measureSpectrum()
        return 
        
    def cancelXfeSpectrum(self):
        self.md2.CloseFastShutter()
        self.ketek.Abort()
        self.obx.Close()
        self.extractDetector()
        
    def isConnected(self):
        return True
        
    def measureSpectrum(self):
        self.setIntegrationTime(self.integrationTime)
        if self.optimize != True:
            self.insertDetector()
            self.obx.Open()
        self.md2.PhasePosition = 4
        self.wait(self.md2)
        self.md2.OpenFastShutter()
        self.ketek.Start()
        #self.counter.Start()
        time.sleep(int(self.integrationTime))
        #while self.counter.State().name != 'STANDBY':
            #pass
        #self.ketek.Abort()
        self.wait(self.md2)
        self.md2.CloseFastShutter()
        if self.optimize != True:
            self.obx.Close()
            self.extractDetector()
        
    def getSpectrum(self):
        return self.ketek.channel00
        
    def getMcaConfig(self):
        return {'att': '7', 'energy': 12.65, 'bsX': 1, 'bsY': 2 }
        
    def getXvals(self):
        start, end   = 0, 2048 #self.ketek.roisStartsEnds
        #energy_start = start * self.channelToeV
        #energy_end   = end   * self.channelToeV
        #step = (energy_end - energy_start) / len(ketek.channel00)
        step = 1 #(end - start) / len(self.ketek.channel00)
        return numpy.arange(start, end, step)
        
    def saveData(self):
        f = open(self.filename[:-4]  + '.pck', 'w')
        x = self.getXvals()
        y = self.getSpectrum()
        pickle.dump({'x': x, 'y': y}, f)
        f.close()
        
    def plotSpectrum(self):
        x = self.getXvals()
        y = self.getSpectrum()
        self.saveData(x, y)
        
        pylab.figure()
        pylab.plot(x, y)
        pylab.xlim(x[0], x[-1])
        pylab.title('X-ray fluorescence emission spectrum')
        pylab.xlabel('Channels')
        pylab.ylabel('Intensity [Counts]')
        pylab.savefig(self.filename)
        
        pylab.show()
        
if __name__ == '__main__':
    usage = 'Program to perform collect on PX2 beamline.\n\n%prog -n <number_of_images>\n\nNumber of images to be collected has to be specified, others are optional.'
    parser = optparse.OptionParser(usage = usage)

    parser.add_option('-e', '--exposure', default = 2.0, type = float, help = 'integration time (default: %default)')
    parser.add_option('-x', '--prefix', default = 'test', type = str, help = 'prefix (default = %default)')
    parser.add_option('-d', '--directory', default = '/tmp/fxetests2', type = str, help = 'where to store spectrum collected (default: %default)')

    (options, args) = parser.parse_args()
    print options
    print args
    
    doCollect = XfeCollect(options.exposure, options.directory, options.prefix)
    doCollect.setROI(1, 2048)
    time.sleep(0.5)
    #doCollect.setIntegrationTime()
    doCollect.measureSpectrum()
    doCollect.plotSpectrum()
    