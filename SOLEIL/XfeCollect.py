#!/usr/bin/env python
# -*- coding: utf-8 -*-

from HardwareRepository import HardwareRepository
from HardwareRepository import BaseHardwareObjects

import time
import pylab
import numpy
import os
import pickle
import math

from PyTango import DeviceProxy as dp

from xabs_lib import *

class XfeCollect(BaseHardwareObjects.Device):

    def init(self):

        self.hdw_control = True

        if self.mode == 'test':
            self.test = True
        else:
            self.test = False

        self.fastshut = self.getObjectByRole("fast_shutter")
        self.safshut = self.getObjectByRole("safety_shutter")
        self.fluodet = self.getObjectByRole("fluodet")

        self.ble = dp(self.ble_dev)

        self.Ps_h = dp(self.ps_h_dev)
        self.Ps_v = dp(self.ps_v_dev)
        self.Const = dp(self.const_dev)
        self.Fp = dp(self.fp_dev)

    def setup(self, integrationTime = .64, directory = '/tmp', prefix = 'test', sessionId = None, sampleId = None, optimize=False):

        self.integrationTime = integrationTime
        self.directory = directory
        self.prefix = prefix
        self.sessionId = sessionId
        self.sampleId = sampleId
        self.filename = os.path.join(self.directory, self.prefix + '_fxe.png') #filename
        
        self.optimize = optimize

        try:
            if not os.path.exists(directory):
                os.mkdir(directory)
            else:
                if not os.path.isdir(directory):
                    print directory," exists, but it not a directory"  
        except OSError, e:
            print e

    def wait(self, device):
        while device.state().name == 'MOVING':
            time.sleep(.1)
        
        while device.state().name == 'RUNNING':
            time.sleep(.1)
            
    def transmission(self, x=None):
        logging.debug("XfeCollect. transmission() This is a stub. should implemented at each beamline")
        
    def go10eVabovetheEdge(self):
        if self.test == True: return 0

        if self.hdw_control:
            self.ble.write_attribute('energy', self.thEdge + 0.01)
            self.wait(self.ble)
            
    def getEdgefromXabs(self, el, edge):
        edge = edge.upper()
        roi_center = McMaster[el]['edgeEnergies'][edge + '-alpha']
        if edge == 'L':
            edge = 'L3'
        e_edge = McMaster[el]['edgeEnergies'][edge]
        return (e_edge, roi_center)    
        
    def optimizeTransmission(self, element, edge):
        if self.test == True: return 0
        print 'Going to optimize transmission'
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

        if self.hdw_control:
            self.safshut.openShutter()
            self.insertFluoDet()

        while not .7 < self.tentativeDeadTime < .8:
            if self.transmission() > 50:
                break
            
            self.measureSpectrum()
            ICR = self.fluodet.getICR()
            OCR = self.fluodet.getOCR()
            eventTime = self.fluodet.getRealTime()
            self.inverseDeadTime = 1. - (OCR / ICR) # * eventTime
            self.tentativeDeadTime = (OCR / ICR)
            k += 1
            print 'Cycle %d, deadtime is %f' % (k, self.inverseDeadTime)
            self.adjustTransmission()

        print 'Transmission optimized at %s, the deadtime is %s' % (self.currentTransmission, self.inverseDeadTime)
        print 'Tentative real deadtime is %f' % self.tentativeDeadTime

        if self.hdw_control:
            self.safshut.openShutter()
            self.extractFluoDet()
        
    def adjustTransmission(self):
        if self.test == True: return 0
        self.currentTransmission = self.transmission()
        print 'current transmission is %f' % self.currentTransmission
        print 'the deadtime is %f' % self.inverseDeadTime
        if self.tentativeDeadTime < 0.7: #too much flux
            self.highBoundary = self.setTransmission
            self.setTransmission -= (self.highBoundary - self.lowBoundary)/2.
        else: #too little flux
            self.lowBoundary = self.setTransmission
            if self.highBoundary is None:
                self.setTransmission *= 2
            else:
                self.setTransmission += (self.highBoundary - self.lowBoundary)/2.
        self.transmission(self.setTransmission)
        
    def canSpectrum(self):
        return True
        
    def setROI(self, roi_debut = 0., roi_fin = 2048.):
        if self.test == True: return 0
        self.fluodet.set_roi(roi_debut,roi_fin)
    
    def startXfeSpectrum(self):
        self.measureSpectrum()
        return 
        
    def cancelXfeSpectrum(self):
        if self.test == True: return 0

        if self.hdw_control:
            self.closeFastShutter()
            self.fluodet.abort()
            self.safshut.closeShutter()
            self.extractFluoDet()
        
    def isConnected(self):
        return True
        
    def openFastShutter(self,timeout=0.5):

        t0 = time.time()

        while str( self.fastshut.getShutterState() ) != "opened":

            if (time.time() - t0 ) > timeout:
                logging.error("Timeout. Could not open fast shutter.") 
                return False

            while self.get_state() != 'Ready':
                time.sleep(0.1)

            try:
                self.fastshut.openShutter()
            except:
                import traceback
                traceback.print_exc()

        return True
        
    def closeFastShutter(self):
        self.fastshut.closeShutter()

    def get_state(self):
        logging.debug("XfeCollect. get_state() This is a stub. should implemented at each beamline")
        
    def set_collect_phase(self):
        logging.debug("XfeCollect. set_collect_phase() This is a stub. should implemented at each beamline")
        
    def measureSpectrum(self):
        if self.test == True: return 0

        self.fluodet.set_preset(float(self.integrationTime))

        if self.optimize != True and self.hdw_control:
            self.insertFluoDet()
            self.safshut.openShutter()

        time.sleep(1)
        if self.hdw_control:
            self.set_collect_phase()

            if not self.openFastShutter():
                logging.error("XfeCollect. Collection aborted")
                cleanup()
                return
 
        self.fluodet.start()
        self.fluodet.wait()

        cleanup()
        
    def cleanup(self):

        if not self.hdw_control:
            return

        self.closeFastShutter()
        if self.optimize != True:
            self.fluodet.extract()

    def getSpectrum(self):
        return self.fluodet.get_data()
        
    def getValue(self):
        return self.fluodet.get_spectrum()

    def getValueCalibrated(self):
        return self.fluodet.get_spectrum_calibrated()

    def getMcaConfig(self):
        retdict = {}
        retdict['energy'] = 12.65
        retdict['bsX'] = 1
        retdict['bsY'] = 2
        retdict['att'] = 7
        return retdict

    def getMcaCalib(self):
        return self.fluodet.get_calibration()

    def saveData(self):
        f = open(self.filename[:-4]  + '.pck', 'w')
        x = self.fluodet.get_xvals()
        y = self.fluodet.get_data()
        energies = self.fluodet.get_calibrated_energies()
        cal = self.fluodet.get_calibration()
        pickle.dump({'x': x, 'energies': energies, 'calibration': cal, 'y': y}, f)
        f.close()
        
    def plotSpectrum(self):
        x = self.fluodet.get_calibrated_energies() #getXvals()
        y = self.fluodet.get_data()
        self.saveData()
        
        pylab.figure()
        pylab.plot(x, y)
        pylab.xlim(x[0], x[-1])
        pylab.title('X-ray fluorescence emission spectrum')
        pylab.xlabel('Energy [keV]')
        pylab.ylabel('Intensity [Counts]')
        pylab.savefig(self.filename)
        
        pylab.show()

    def setHardwareControlMode(self, mode):
        self.hdw_control = mode
        
def main():
    import optparse

    usage = 'Program to perform collect on PX2 beamline.\n\n%prog -n <number_of_images>\n\nNumber of images to be collected has to be specified, others are optional.'
    parser = optparse.OptionParser(usage = usage)

    parser.add_option('-e', '--exposure', default = 2.0, type = float, help = 'integration time (default: %default)')
    parser.add_option('-x', '--prefix', default = 'test', type = str, help = 'prefix (default = %default)')
    parser.add_option('-d', '--directory', default = '/tmp/fxetests2', type = str, help = 'where to store spectrum collected (default: %default)')

    (options, args) = parser.parse_args()
    print options
    print args

    # create the xanes object
    hwr_directory = os.environ["XML_FILES_PATH"]

    hwr = HardwareRepository.HardwareRepository(os.path.abspath(hwr_directory))
    hwr.connect()

    xfecollect = hwr.getHardwareObject("/xfecollect")
    xfecollect.setHardwareControlMode(False)  # only control detector hardware, no shutter or other

    xfecollect.setup(options.exposure, options.directory, options.prefix)
    
    xfecollect.setROI(1, 2048)
    time.sleep(0.5)
    xfecollect.measureSpectrum()
    xfecollect.plotSpectrum()

if __name__ == '__main__':
    import sys
    import os


    print "Running XfeCollect procedure standalone"
    hwrpath = os.environ.get('XML_FILES_PATH',None)

    if hwrpath is None:
        print "  -- you should first source the file mxcube.rc to set your environment variables"
        sys.exit(0)
    else:
        main()

