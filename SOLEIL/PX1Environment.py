# -*- coding: utf-8 -*-

import time
import logging
import PyTango
from HardwareRepository import HardwareRepository
from HardwareRepository.BaseHardwareObjects import Device
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
              
        self.device = PyTango.DeviceProxy(self.getProperty("tangoname"))
        #self.state
        try:
            self.chanStatus = self.getChannelObject('State')
            self.chanStatus.connectSignal('update', self.stateChanged)
            logging.getLogger().info('%s: Connected to State channel.', self.name())
            #state = self.chanStatus.getValue()
            #logging.getLogger().info('%s: stateChanged to %s' % (self.name(), state))
	    
        except KeyError:
            logging.getLogger().warning('%s: cannot report State', self.name())

        try:
            self.chanAuth = self.getChannelObject('beamlineMvtAuthorized')
            self.chanAuth.connectSignal('update', self.setAuthorizationFlag)
            logging.getLogger().info('%s: Connected to AuthorizationFlag channel.', self.name())
            state = self.chanStatus.getValue()
            logging.getLogger().info('%s: stateChanged to %s' % (self.name(), state))
	    
        except KeyError:
            logging.getLogger().warning('%s: cannot report State', self.name())

        if self.device is not None:
            #self.stateChan = self.getChannelObject("State")    
            #self.stateChan.connectSignal("update", self.stateChanged)
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
        logging.debug("PX1environment state changed. It is now %s", (str(value))) #, EnvironmentState.tostring(value)))
        logging.debug('%s: stateChanged to %s' % (self.name(), value))
        self.emit('StateChanged', (value,))

    def readState(self):
        state = str(self.chanStatus.getValue())
        #try:
	#    state = self.device.State()
        logging.getLogger().info('%s: readState: %s' % (self.name(), state))
        return state 

    def isBusy(self, timeout=None):
        #state = self.device.State()
        state = self.stateChan.getValue()
        return state not in [EnvironmentState.ON,]

    def waitReady(self, timeout=None):
        logging.debug("PX1environment: waitReady")
        #self._waitState([EnvironmentState.ON,], timeout)
        self._waitState(["ON",], timeout)

    def _waitState(self, states, timeout=None):
        if self.device is None:
            return
        logging.debug("PX1environment: start _waitState")
	_debut = time.time()
        with gevent.Timeout(timeout, Exception("Timeout waiting for device ready")):
            waiting = True
            while waiting:
                state = self.readState()
                if state in states:
                    waiting = False
                gevent.sleep(0.05)

    #
    #------- end state handling
        logging.debug("PX1environment: end _waitState in %.1f sec" % (time.time() - _debut))

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
        self.waitPhase(phase, 40)

    def readPhase(self):
        if self.device is not None:
            phasename = self.device.currentPhase
            return EnvironmentPhase.phase(phasename)
        else:
            return None

    def getPhase(self):
        if self.device is not None:
            phasename = self.device.currentPhase
            return phasename
        else:
            return None

    def waitPhase(self, phase,timeout=None):
        if self.device is None:
            return
        logging.debug("PX1environment: start waitPhase")
	_debut = time.time()
	n = 0
        with gevent.Timeout(timeout, Exception("Timeout waiting for environment phase")):
            waiting = True
            while waiting:
	        n += 1
                _phaseread = self.readPhase()
                if phase == _phaseread:
                    waiting = False
                gevent.sleep(0.05)
        logging.debug("PX1environment: end waitPhase in %.1f sec N= %d" % \
	                      ((time.time() - _debut), n))

    #
    #------- end phase handling
    
    def gotoCentringPhase(self):
        if not self.readyForCentring():
            self.getCommandObject("GoToCentringPhase")()
	    time.sleep(0.1)

    def gotoLoadingPhase(self):
        if not self.readyForManualTransfer():
            self.getCommandObject("GoToManualTransfertPhase")()
	    time.sleep(0.1)

    def setAuthorizationFlag(self, value):
        # make here the logic with eventually other permits (like hardware permit)
        self.emit("operationPermitted", value)

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

