#!/usr/bin/env python
# -*- coding: utf-8 -*-

import time
import logging
from Xanes import Xanes
from PyTango import DeviceProxy as dp

class PX1Xanes(Xanes):

    def init(self):
        Xanes.init(self)

        if not self.test:
            self.px1env = dp(self.px1environment_dev)

    def get_state(self):
        state = self.px1env.State()
        if str(state).upper() ==  'MOVING':
            return 'Moving'
        return 'Ready'

    def set_collect_phase(self, phase_name='FLUOX'):
        if self.test:
            return

        self.px1env.GoToFluoXPhase()
        debut = time.time()
        while self.px1env.readyForFluoScan != True:
            #logging.debug("PX1Xanes - set_collect: readyForFluoScan %s" % self.px1env.readyForFluoScan)
            time.sleep(0.1)
	    if (time.time() - debut) > 30:
               logging.debug("PX1Xanes - Timed out while going to FluoXPhase")
	       break

    def transmission(self, x=None):
        '''Get or set the transmission'''
        if self.test: return 0
        if x == None:
            return self.Fp.TrueTrans_FP

        truevalue = (2.0 - math.sqrt(4 - 0.04 * x)) / 0.02

        newGapFP_H = math.sqrt(
            (truevalue / 100.0) * self.Const.FP_Area_FWHM / self.Const.Ratio_FP_Gap)
        newGapFP_V = newGapFP_H * self.Const.Ratio_FP_Gap

        self.Ps_h.gap = newGapFP_H
        self.Ps_v.gap = newGapFP_V

    def safeOpenSafetyShutter(self):

        logging.info('Opening the safety shutter -- checking the hutch PSS state')

        if self.test:
	    return

        if int(self.pss.prmObt) == 1:
            self.safshut.openShutter()
            while self.safshut.getShutterState() != 'opened' and self.stt not in ['STOP', 'ABORT']:
                time.sleep(0.1)

        logging.info(self.safshut.getShutterState())

    def cleanUp(self):
        self.saveRaw()
        self.chooch()
        self.saveResults()

        if self.test: 
            return
        self.ble.write_attribute('energy', self.pk/1000.)

    def prepare(self):

        logging.debug("PX1Xanes - starting prepare") 
        self.getAbsEm()
        self.setROI()
        logging.debug("PX1Xanes - mid prepare") 
        
        self.set_collect_phase()
        self.moveBeamlineEnergy(self.e_edge)
        
        #self.optimizeTransmission()
        
        if not self.test:
            self.fluodet.set_preset( float(self.integrationTime) )
                
        self.results = {}
        self.results['timestamp'] = time.time()
        self.results['prefix'] = self.prefix
        self.results['element'] = self.element
        self.results['edge'] = self.edge
        self.results['peakingTime'] = self.peakingTime
        self.results['dynamicRange'] = self.dynamicRange
        self.results['integrationTime'] = self.integrationTime
        self.results['nbSteps'] = self.nbSteps
        logging.debug("PX1Xanes - finishing prepare") 

    def attenuation(self, x=None):
        '''Read or set the attenuation'''
        if self.test: return 0
        
        labels = ['00 None',
                  '01 Carbon 200um',
                  '02 Carbon 250um',
                  '03 Carbon 300um',
                  '04 Carbon 500um',
                  '05 Carbon 1mm',
                  '06 Carbon 2mm',
                  '07 Carbon 3mm',
                  '10 Ref Fe 5um',
                  '11 Ref Pt 5um']

        if x == None:
            status = self.Attenuator.Status()
            print 'status', status
            status = status[:status.index(':')]
            value = status
            return value

        NumToLabel = dict([(int(l.split()[0]), l) for l in labels])
        self.Attenuator.write_attribute(NumToLabel[x], True)
        self.wait(self.Attenuator)

if __name__ == "__main__":

    import sys
    import os

    from Xanes import main

    print "Running Xanes procedure standalone" 
    hwrpath = os.environ.get('XML_FILES_PATH',None)

    if hwrpath is None:
        print "  -- you should first source the file mxcube.rc to set your environment variables"
        sys.exit(0)
    else:
        main()
