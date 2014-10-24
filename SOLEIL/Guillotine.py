# -*- coding: utf-8 -*-
from HardwareRepository.BaseHardwareObjects import Device
import PyTango
import logging

class Guillotine(Device):
    def __init__(self, name):
        Device.__init__(self, name)

    def init(self):
            
        self.setIsReady(True)

        self.device = PyTango.DeviceProxy( self.getProperty("tangoname"))

        stateChan = self.getChannelObject("state")
        stateChan.connectSignal("update", self.stateChanged)

    def setIn(self):
        self.device.Insert()

    def setOut(self):
        self.device.Extract()

    def stateChanged(self, value):
        logging.debug("Guillotine state changed. It is now ", value)

        self.emit('stateChanged', (value,))

