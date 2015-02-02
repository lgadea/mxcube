# -*- coding: utf-8 -*-
import logging
from HardwareRepository.BaseHardwareObjects import Device
from PyTango import DeviceProxy

class TangoPssPX1(Device):
    states = {
      0:   "not ready",
      1:   "ready",
    }

    READ_CMD, READ_OUT = (0, 1)
    
    def __init__(self, name):
        Device.__init__(self, name)

        #self.wagoidin  = None
        #self.wagoidout = None
        self.wagokyin  = None
        self.wagokyout = None
        self.wagoState = "unknown"
        self.__oldValue = None
        self.device = None
        self.detector_dist = None
        self.beamstop = None
        self.hutch = None
        self.lastState = None

    def init(self):
        #logging.getLogger("HWR").info("%s: TangoPss.init", self.name())
        try:
            self.device = DeviceProxy(self.getProperty("tangoname"))
        except:
            logging.getLogger("HWR").error("%s: unknown pss device name",
                                            self.getProperty("tangoname"))
#        stateChan = self.getChannelObject("state") # utile seulement si statechan n'est pas defini dans le code
#        stateChan.connectSignal("update", self.stateChanged) 
        if self.getProperty("hutch") not in ("optical", "experimental"):
            logging.getLogger("HWR").error("TangoPss.init Hutch property %s is not correct",self.getProperty("hutch"))
        else :
            self.hutch  = self.getProperty("hutch")
            if self.hutch == "optical" :
                stateChan = self.addChannel({ 'type': 'tango', 'name': 'memInt', 'polling':1000 }, "memInt")
            else :
                stateChan = self.addChannel({ 'type': 'tango', 'name': 'memInt', 'polling':1000 }, "memInt")
            stateChan.connectSignal("update", self.valueChanged)
        if self.device:
            self.setIsReady(True)
    
    def valueChanged(self, value):
        logging.getLogger("HWR").info("%s: TangoPss.valueChanged, %s", self.name(), value)
        state = self.getWagoState()
        self.emit('wagoStateChanged', (state, ))
    
    def getWagoState(self):
        if self.hutch == "optical" :
            value = int(self.device.memInt)
        elif self.hutch == "experimental" :
            value = int(self.device.memInt)
        else :
            self.wagoState = "unknown"
            return self.wagoState
        print "value PSS :" , value
        if value != self.__oldValue:
            self.__oldValue = value
        if value in TangoPssPX1.states:
            self.wagoState = TangoPssPX1.states[value]
        else:
            self.wagoState = "unknown"
        return self.wagoState 


    def wagoIn(self):
        logging.getLogger("HWR").info("%s: TangoPss.wagoIn", self.name())
        if self.isReady():
            #self.device.DevWriteDigi([ self.wagokyin, 0, 1 ]) #executeCommand('DevWriteDigi(%s)' % str(self.argin))
            pass

            
    def wagoOut(self):
        logging.getLogger("HWR").info("%s: TangoPss.wagoOut", self.name())
        if self.isReady():
            #self.device.DevWriteDigi([ self.wagokyin, 0, 0 ]) #executeCommand('DevWriteDigi(%s)' % str(self.argin))
            pass
