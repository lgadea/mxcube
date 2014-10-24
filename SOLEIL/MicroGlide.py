# -*- coding: utf-8 -*-
from HardwareRepository.BaseHardwareObjects import Device
import PyTango
import logging

class MicroGlide(Device):
    def __init__(self, name):
        Device.__init__(self, name)

    def init(self):
            
        self.setIsReady(True)

        self.device = PyTango.DeviceProxy( self.getProperty("tangoname"))

        stateChan = self.getChannelObject("state")
        stateChan.connectSignal("update", self.stateChanged)

        self.xPosition = self.getChannelObject("x")
        self.yPosition = self.getChannelObject("y")
        self.zPosition = self.getChannelObject("z")

        self.moveCmd = self.getCommandObject("move") 

    def getPosition(self):
        return (self.xPosition.getValue(), self.yPosition.getValue(), self.zPosition.getValue())

    def move(self, pos):
        """ For MicroGlide position should be a three value list with x,y,z positions"""
        self.moveCmd(pos)

    def home(self):
        self.device.Home()

    def stateChanged(self, value):
        logging.debug("MicroGlide state changed. It is now ", value)
        logging.debug("   -x: %s / y: %s / z: %s " %  self.getPosition )

        self.emit('stateChanged', (value,))

