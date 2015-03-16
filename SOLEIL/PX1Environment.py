# -*- coding: utf-8 -*-

from HardwareRepository import HardwareRepository
from HardwareRepository.BaseHardwareObjects import Device
import PyTango
import logging
import gevent

class EnvironmentPhase:

    TRANSFER = 0
    CENTRING = 1
    COLLECT = 2
    DEFAULT = 3 
    BEAMVIEW = 4
    FLUOX = 5
    MANUALTRANSFER = 6
    INPROGRESS = 7
    VISUSAMPLE = 8

    phasedesc = {
       "TRANSFER": TRANSFER,
       "CENTRING": CENTRING,
       "COLLECT": COLLECT,
       "DEFAULT": DEFAULT,
       "BEAMVIEW": BEAMVIEW,
       "FLUOX": FLUOX,
       "MANUALTRANSFER": MANUALTRANSFER,
       "INPROGRESS": INPROGRESS,
       "VISUSAMPLE": VISUSAMPLE,
    }

    @staticmethod
    def phase(phasename):
        return EnvironmentPhase.phasedesc.get(phasename, None)

class EnvironemntState:
    UNKNOWN, ON, RUNNING, ALARM, FAULT = (0, 1, 10, 13, 14)  # Like PyTango stated

    #TangoStates = { 
    #    Unknown     = 0
    #    On          = 1
    #    Loaded      = 2
    #    Loading     = 3
    #    Unloading   = 4
    #    Selecting   = 5
    #    Scanning    = 6
    #    Resetting   = 7
    #    Charging    = 8
    #    Moving      = 9
    #    Running     = 10
    #    StandBy     = 11
    #    Disabled    = 12
    #    Alarm       = 13
    #    Fault       = 14
    #    Initializing= 15
    #    Closing     = 16
    #    Off         = 17
    #}

    statedesc = {
       ON: "ON",
       RUNNING: "RUNNING",
       ALARM: "ALARM",
       FAULT: "FAULT",
    }

    @staticmethod
    def tostring(state):
        return SampleChangerState.statedesc.get(state, "Unknown")

class PX1Environment(Device):

    def __init__(self, name):
        Device.__init__(self, name)

    def init(self):
              
        self.device = PyTango.DeviceProxy( self.getProperty("tangoname"))

        if self.device is not None:
            self.stateChan = self.getChannelObject("state")
    
            self.stateChan.connectSignal("update", self.stateChanged)
            self.setIsReady(True)

            self.cmds = {
               EnvironmentPhase.TRANSFER: self.device.GoToTransfertPhase,
               EnvironmentPhase.CENTRING: self.device.GoToCentringPhase,
               EnvironmentPhase.COLLECT: self.device.GoToCollectPhase,
               EnvironmentPhase.DEFAULT: self.device.GoToDefaultPhase,
               # EnvironmentPhase.BEAMVIEW: self.device.GoToBeamViewPhase,
               EnvironmentPhase.FLUOX: self.device.GoToFluoXPhase,
               EnvironmentPhase.MANUALTRANSFER: self.device.GoToManualTransfertPhase,
               EnvironmentPhase.VISUSAMPLE: self.device.GoToVisuSamplePhase
            }

    #---- begin state handling
    #
    def stateChanged(self, value):
        logging.debug("PX1environment state changed. It is now %s / %s", (str(value), EnvironmentState.tostring(state)))
        self.emit('stateChanged', (value,))

    def readState(self):
        state = self.stateChan.getValue()
        return state 

    def isBusy(self, timeout=None):
        state = stateChan.getValue()
        return state not in [EnvironmentState.ON,]

    def waitReady(self, timeout=None):
        self._waitState([EnvironmentState.ON,], timeout)

    def _waitState(self, states, timeout=None):
        if self.device is None:
            return

        with gevent.Timeout(timeout, Exception("Timeout waiting for device ready")):
            waiting = True
            while waiting:
                state = self.readState()
                if state in states:
                    waiting = False
                gevent.sleep(0.01)

    #
    #------- end state handling

    #------- begin phase handling
    #
    def isPhaseTransfer(self):
        return self.readPhase() == EnvironmentPhase.TRANSFER

    def readyForCentring(self):
        if self.device is not None:
            return self.device.readyForCentring
        else:
            return None
         
    def readyForCollect(self):
        if self.device is not None:
            return self.device.readyForCollect
        else:
            return None
         
    def readyForDefaultPosition(self):
        if self.device is not None:
            return self.device.readyForDefaultPosition
        else:
            return None
         
    def readyForFluoScan(self):
        if self.device is not None:
            return self.device.readyForFluoScan
        else:
            return None
         
    def readyForManualTransfer(self):
        if self.device is not None:
            return self.device.readyForManualTransfert
        else:
            return None
         
    def readyForTransfer(self):
        if self.device is not None:
            return self.device.readyForTransfert
        else:
            return None
        
    def readyForVisuSample(self):
        if self.device is not None:
            return self.device.readyForVisuSample
        else:
            return None
 
    def gotoPhase(self, phase):
        logging.debug("PX1environment.gotoPhase %s" % phase)
        cmd = self.cmds.get(phase, None)
        if cmd is not None:
            logging.debug("PX1environment.gotoPhase state %s" % self.readState())
            cmd()
        else:
            return None
         
    def setPhase(self, phase):
        self.gotoPhase(phase) 
        self.waitPhase(phase, 30)

    def readPhase(self):
        if self.device is not None:
            phasename = self.device.currentPhase
            return EnvironmentPhase.phase(phasename)
        else:
            return None

    getPhase = readPhase

    def waitPhase(self, phase,timeout=None):
        if self.device is None:
            return

        with gevent.Timeout(timeout, Exception("Timeout waiting for environment phase")):
            waiting = True
            while waiting:
                _phaseread = self.readPhase()
                if phase == _phaseread:
                    waiting = False
                gevent.sleep(0.01)

    #
    #------- end phase handling

def test():
    import os
    import time
    hwr_directory = os.environ["XML_FILES_PATH"]

    t0 = time.time()
    print hwr_directory
    hwr = HardwareRepository.HardwareRepository(os.path.abspath(hwr_directory))
    hwr.connect()

    env = hwr.getHardwareObject("/px1environment")

    print "PX1 Environment ", env.isPhaseTransfer()
    print "       phase is ", env.readPhase()
    print "       state is ", env.readState()

    print time.time() - t0

    if not env.readyForTransfer():
        print "Going to transfer phase"
        env.setPhase(EnvironmentPhase.TRANSFER)
        print time.time() - t0
    print "done"
    env.waitPhase(EnvironmentPhase.TRANSFER)
    print time.time() - t0

if __name__ == '__main__':
   test()

