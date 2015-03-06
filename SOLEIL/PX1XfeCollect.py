#!/usr/bin/env python
# -*- coding: utf-8 -*-

from XfeCollect import XfeCollect

class PX1XfeCollect(XfeCollect):

    def init(self):

        XfeCollect.init(self)

        if not self.test:
            self.px1env = dp(self.px1environment_dev)

    def get_state(self):
        state = self.px1env.State()
        if str(state).upper() ==  'MOVING':
            return 'Moving'
        return 'Ready'
        
    def set_collect_phase(self, phase_name='COLLECT'):
        if self.test: return

        self.px1env.GoToCollectPhase()

        while self.px1env.currentPhase != phase_name or self.get_state() != 'Ready':
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
            
if __name__ == "__main__":

    import sys
    import os

    from XfeCollect import main

    print "Running Xanes procedure standalone" 
    hwrpath = os.environ.get('XML_FILES_PATH',None)

    if hwrpath is None:
        print "  -- you should first source the file mxcube.rc to set your environment variables"
        sys.exit(0)
    else:
        main()
