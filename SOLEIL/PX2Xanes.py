#!/usr/bin/env python
# -*- coding: utf-8 -*-

from Xanes import Xanes

class PX2Xanes(Xanes):

    def get_state(self):
        for state in self.md2.motorstates:
            if 'Moving' in state:
                return 'Moving'
        return 'Ready'
        
    def set_collect_phase(self, phase_name='DataCollection'):
        if self.test: return

        self.md2.startSetPhase(phase_name)
        while self.md2.currentPhase != phase_name or self.get_state() != 'Ready':
            time.sleep(0.1)
            
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
