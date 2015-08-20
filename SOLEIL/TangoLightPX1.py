import logging, time
from PyTango import DeviceProxy as dp
from HardwareRepository.BaseHardwareObjects import Device
#from PX1Environment import EnvironmentPhase

class TangoLightPX1(Device):

    def __init__(self, name):
        Device.__init__(self, name)
        self.currentState = "unknown"

    def init(self):
        #self.tangoname = self.
        self.attrchan = self.getChannelObject("attributeName")
        self.attrchan.connectSignal("update", self.valueChanged)

        self.attrchan.connectSignal("connected", self._setReady)
        self.attrchan.connectSignal("disconnected", self._setReady)
        self.set_in = self.getCommandObject("set_in")
        self.set_in.connectSignal("connected", self._setReady)
        self.set_in.connectSignal("disconnected", self._setReady)
        self.set_out = self.getCommandObject("set_out")
        
        # Avoiding Beamstop + Light Arm collision.
        #self.beamstop_out = self.getCommandObject("beamstop_out")
        #self.beamstopState = self.getChannelObject("beamstopState")
        
        # Avoiding Colision with the Detector
        #self.detdistchan = self.getChannelObject("detDistance")
        #logging.getLogger("HWR").info(('TangoLightPX1. minimum Detector '
        #                + 'distance for light_Arm insertion: %.1f mm') % \
        #                                   self.min_detector_distance)
        self.environment = self.getObjectByRole("environment")
        self.px1env = dp(self.px1environment_dev)
        self.light = dp(self.light_dev)

        self._setReady()
        try:
	   self.inversed = self.getProperty("inversed")
        except:
	   self.inversed = False

        if self.inversed:
           self.states = ["in", "out"]
        else:
           self.states = ["out", "in"]

    def _setReady(self):
        self.setIsReady(self.attrchan.isConnected())

    def connectNotify(self, signal):
        if self.isReady():
           self.valueChanged(self.attrchan.getValue())


    def valueChanged(self, value):
        self.currentState = value

        if value:
            self.currentState = self.states[1]
        else:
            self.currentState = self.states[0]
        
        self.emit('wagoStateChanged', (self.currentState, ))
        
    def getWagoState(self):
        logging.getLogger("HWR").info('TangoLightPX1. getWagoState: %s' % self.currentState)
        return self.currentState 

    def getState(self):
        return self.currentState 

    def wagoIn(self):
        logging.getLogger("HWR").info('TangoLightPX1. GoToVisuSamplePhase.')
        if not self.px1env.readyForVisuSample:
            logging.getLogger("HWR").info('TangoLightPX1. Inserting Light.')       
            self.px1env.GoToVisuSamplePhase()
            debut = time.time()
            while self.px1env.readyForVisuSample != True:
                time.sleep(0.1)
	        if (time.time() - debut) > 20:
                   logging.debug("PX1Xanes - Timed out while going to FluoXPhase")
	           break
        #if str(self.beamstopState.getValue()) == 'INSERT':
	    #self.beamstop_out()
            #t0 = time.time()
            #while str(self.beamstopState.getValue()) != "EXTRACT":
            #    time.sleep(0.02)
            #    qApp.processEvents()
            #    if (time.time() - t0) > 5:
            #        logging.getLogger("HWR").info('TangoLightPX1. Time out while trying to extract the beamstop.')
            #        return
            #logging.getLogger("HWR").info('TangoLightPX1. Time to extract the beamstop: %.2f sec.' % (time.time()-t0))
        #detposition = self.detdistchan.getValue()
        #logging.getLogger("HWR").info('TangoLightPX1. DetDist= %.2f mm. OK.' % detposition)
        #if detposition < self.min_detector_distance:
        #    m1 = "Can't insert Light-arm, detector distance too close: %.1f mm. " % detposition
        #    m2 = "You need to set the distance to > %.1f mm." % self.min_detector_distance
        #    logging.getLogger("user_level_log").error("%s: " + m1+m2, self.name())
        #else:
        #    logging.getLogger("HWR").info('TangoLightPX1. Inserting Light.')       
        #    self.setIn()

    def setIn(self):
        self._setReady()
        if self.isReady():
          if self.inversed:
	      self.light.intensity = 0.
              self.set_out()
          else:
              self.set_in()
 
    def wagoOut(self):
        logging.getLogger("HWR").info('TangoLightPX1:  in WagoOut ')
        self.setOut()

    def setOut(self):
        self._setReady()
        if self.isReady():
          if self.inversed:
              self.set_in()
          else:
 	      self.light.intensity = 0.
              self.set_out()
           