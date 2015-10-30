# -*- coding: utf-8 -*-
import math
import logging
import time

from PyTango import DeviceProxy

from HardwareRepository import BaseHardwareObjects
from HardwareRepository import HardwareRepository

# Changed for PILATUS 6M
DETECTOR_DIAMETER = 424.

class UserViewResolution(BaseHardwareObjects.Equipment):
        
    stateDict = {
         "UNKNOWN": 0,
         "ALARM":   1,
         "OFF":     1,
         "STANDBY": 2,
         "RUNNING": 4,
         "MOVING":  4,
         "1":       1,
         "2":       2}
   
    def init(self):
        self.currentResolution = None
        self.currentWavelength = None

        self.user_action_mode = False
        self.never_sent = True

        self.device = DeviceProxy( self.getProperty("tangoname") )
        self.blenergyHO = self.getDeviceByRole("energy")

        if self.blenergyHO is None:
            logging.getLogger("HWR").error('UserViewResolution: you must specify the energy')

        positChan = self.getChannelObject("position") # utile seulement si statechan n'est pas defini dans le code
        stateChan = self.getChannelObject("state") # utile seulement si statechan n'est pas defini dans le code

        positChan.connectSignal("update", self.positionChanged)
        stateChan.connectSignal("update", self.stateChanged)

        self.currentWavelength = self.blenergyHO.getCurrentWavelength()

        return BaseHardwareObjects.Equipment._init(self)

    def userActionStarted(self):
        logging.getLogger().info("UserViewResolution: user action mode started")
        self.user_action_mode = True

    def setNewPosition(self,res):
        self.currentResolution = res
        self.emit('positionChanged', (res,))
        self.never_sent = False

    def positionChanged(self, value):
        if self.user_action_mode or self.never_sent:
            res = self.dist2res(float(value))
            logging.getLogger().info("UserViewResolution: sending out resolution value %s" % res)
            self.setNewPosition(res)

    def getState(self):
        return TangoResolution.stateDict[str( self.device.State() )] 

    def getPosition(self):
        if self.currentResolution is None:
            self.recalculateResolution()
        return self.currentResolution

    def connectNotify(self, signal):
        if signal == 'positionChanged':
           self.positionChanged(self.device.position)

    def stateChanged(self, state):
         logging.getLogger().info("UserViewResolution: state changed %s" % state)
         if str(state) == "STANDBY" and self.user_action_mode:
            self.user_action_mode = False
            logging.getLogger().info("UserViewResolution: state changed. user action mode finished")

    def dist2res(self, distance):
        try:
            self.currentWavelength = self.blenergyHO.getCurrentWavelength()
            thetaangle2 = math.atan(DETECTOR_DIAMETER/2./distance)
            resol = round(0.5*self.currentWavelength /math.sin(thetaangle2/2.),3)
            return resol
        except:
            pass
