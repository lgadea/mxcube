import gevent
from gevent.event import AsyncResult
import sample_centring 

import numpy
import math
import logging, time
from MiniDiff import MiniDiff, myimage
from HardwareRepository import HardwareRepository

#import PyTango
from HardwareRepository.TaskUtils import *
from PX1Environment import EnvironmentPhase


@task
def move_to_centred_position(centred_pos):
     logging.getLogger("HWR").info("move_to_centred_position")
     pos_to_go = []
     for motor, pos in centred_pos.iteritems():
       pos_to_go.append(pos)
       if motor.name() in ["/uglidex", "/uglidey"]:
           moveXYZ = motor.getCommandObject("moveAbsoluteXYZ")
     #print "POS_TO_GO: %8.2f %8.2f %8.2f" % tuple(pos_to_go)
     moveXYZ(pos_to_go)
   
     with gevent.Timeout(15):
       while not all([m.getState() == m.READY for m in centred_pos.iterkeys()]):
         time.sleep(0.1)

class MiniDiffPX1(MiniDiff):

   def __init__(self,*args):
       MiniDiff.__init__(self, *args)
       self.calib_x = None
       self.calib_y = None

   def init(self,*args):
       MiniDiff.init(self, *args)

       self.centringMethods={MiniDiff.MANUAL3CLICK_MODE: self.start3ClickCentring_nonblocking, \
            MiniDiff.C3D_MODE: self.startAutoCentring_nonblocking }

       self.centringKappa = sample_centring.CentringMotor(self.kappaMotor, reference_position=0)
       self.centringKappaPhi = sample_centring.CentringMotor(self.kappaPhiMotor, reference_position=0)
   
       self.permit = True
       self.phase = None
       self.light_level = None

       bs_prop=self.getProperty("bstop")
       self.bstop_ho = None

       if bs_prop is not None:
            try:
                self.bstop_ho=HardwareRepository.HardwareRepository().getHardwareObject(bs_prop)
            except:
                import traceback
                logging.getLogger().info("MiniDiffPX1. Cannot load beamstop %s" % str(bs_prop))
                logging.getLogger().info("    - reason: " + traceback.format_exc())

       px1env_prop=self.getProperty("px1env")
       self.px1env_ho = None

       if px1env_prop is not None:
            try:
                self.px1env_ho=HardwareRepository.HardwareRepository().getHardwareObject(px1env_prop)
            except:
                import traceback
                logging.getLogger().info("MiniDiffPX1.  Cannot load PX1Env %s" % str(px1env_prop))
                logging.getLogger().info("    - reason: " + traceback.format_exc())

       px1conf_prop=self.getProperty("px1configuration")
       self.px1conf_ho = None

       if px1conf_prop is not None:
            try:
                self.px1conf_ho=HardwareRepository.HardwareRepository().getHardwareObject(px1conf_prop)
            except:
                import traceback
                logging.getLogger().info("MiniDiffPX1.  Cannot load PX1Configuration %s" % str(px1conf_prop))
                logging.getLogger().info("    - reason: " + traceback.format_exc())

       self.phase = self.px1env_ho.readPhase()

       self.microglide = self.getDeviceByRole('microglide')
       self.guillotine = self.getDeviceByRole('guillotine')
       self.detectorDistanceMotor = self.getDeviceByRole('detdist')

       self.obx = self.getDeviceByRole('obx')

       if self.sampleChanger is not None:
            self.scAuthChan = self.sampleChanger.getChannelObject("_chnSoftAuth")
            self.scAuthChan.connectSignal("update", self.SCauthorizationChanged )
            #logging.getLogger().info(" >>>>>>>>>>>  MiniDiffPX1. Connection to authorization signal done")
                    #self.connect(self.samplechanger, "gonioMovementAuthorized", self.SCauthorizationChanged )
       else:
            logging.getLogger().info("ERROR >>>>>> MiniDiffPX1. Cannot connect authorization signal. NO samplechanger")

       # some defaults
       self.anticipation  = 1
       self.collect_phaseposition = 4
       self.beamPositionX = 0
       self.beamPositionY = 0
       self.beamSizeX = 0
       self.beamSizeY = 0
       self.beam_xc = 0
       self.beam_yc = 0
       self.beamShape = "rectangular"
       
       #print "phi_is_moving", self.phiMotor.motorIsMoving()
       #print "phi_position", self.phiMotor.getPosition()

   def prepareForAcquisition(self):
       
       _ready = self.px1env_ho.readyForCollect()
       logging.info("MiniDiffPX1: readyForCollect = %s" % _ready)
       if not _ready:
           with gevent.Timeout(100):
               while not self.px1env_ho.readState() == "ON":
                   time.sleep(0.05)
           self.px1env_ho.setPhase(EnvironmentPhase.COLLECT)
       else:
           logging.info("Trying to set COLLECT phase. But already in that phase.")

       self.phase = self.px1env_ho.readPhase() #"COLLECT"
       self.emit("phaseChanged", (self.phase,))
       #if self.beamstopIn() == -1:
       #    raise Exception("Minidiff cannot get to acquisition mode")
       #self.guillotine.setOut()

   def SCauthorizationChanged(self, value):
       #logging.getLogger("HWR").info(">>>>>>>> SCauthorizationChanged >>>>>>>>>>>>>>>>>>>>>>>>>>>>.%s: MiniDiff. Authorization from SC changed. Now is %s.", self.name(), value )              
       self.setAuthorizationFlag("samplechanger", value)
       #from SampleChanger
   def setAuthorizationFlag(self, flag, value):
       #logging.getLogger("HWR").info("<<<<<<<< setAuthorizationFlag <<<<<<<<<<<<<<<<<<<<,  flag ; %s - value :.%s", flag, value)
       
       if flag == "samplechanger":
            self.sc_permit = value

       # make here the logic with eventually other permits (like hardware permit)
       self.permit = self.sc_permit
       #self.permit = True
       self.emit("operationPermitted", self.permit)

   def getAuthorizationState(self):
       return self.permit

   def beamstopIn(self):
       if self.bstop_ho is not None:
          self.bstop_ho.moveIn()
          return 0
       else:
          return -1

   def beamstopOut(self):
       if self.bstop_ho is not None:
          self.bstop_ho.moveOut()
          return 0
       else:
          return -1

   def guillotineIn(self):
       pass

   def guillotineOut(self):
       pass

   def getState(self):
       #logging.info("XX1 getState")
       print "phi_position", self.phiMotor.getPosition()
       return "STANDBY"

   def getBeamInfo(self, callback=None, error_callback=None):
      logging.info("AA1: getBeamInfo in MiniDiffPX1.py ")
      #print "ZOOM_MOTOR2", self.zoomMotor["positions"][0].offset
      d = {}
      d["size_x"] = 0.100
      d["size_y"] = 0.100
      d["shape"] = "rectangular"
      self.beamSizeX = 0.100
      self.beamSizeY = 0.100
      self.beamShape = "rectangular"
      return d
      #callback( d )

   def getBeamPosX(self):
        return self.beam_xc

   def getBeamPosY(self):
        return self.beam_yc

   def get_pixels_per_mm(self):
       return (self.calib_x or 0, self.calib_y or 0)

   def getCalibrationData(self, offset):       
       if self.lightMotor is None or self.lightMotor.positionChan.device is None:
           return (None,None)

       if self.zoomMotor is not None:
           if self.zoomMotor.hasObject('positions'):
               for position in self.zoomMotor['positions']:
                   if position.offset == offset:
                       calibrationData = position['calibrationData']
                       self.calib_x = float(calibrationData.pixelsPerMmY)
                       self.calib_y = float(calibrationData.pixelsPerMmZ)
                       self.beam_xc = float(calibrationData.beamPositionX)
                       self.beam_yc = float(calibrationData.beamPositionY)
                       #check light positionself.
                       #if self.lightWago is not None :
                       if self.lightWago.currentState == "in":
                           self.light_level = float(position.lightLevel)
                           self.lightMotor.move(self.light_level)
                       #print "CALIBR:", (self.calib_x, self.calib_y)
                       #print "BEAMXY:", (self.beam_xc, self.beam_yc)
                       return (self.calib_x or 0, self.calib_y or 0)

       return (None, None)

   def motor_positions_to_screen(self, centred_positions_dict):

       _calibration = self.getCalibrationData(self.zoomMotor.getPosition()) 

       if _calibration[0] and _calibration[1]:
           self.pixelsPerMmY, self.pixelsPerMmZ = _calibration 

       
       logging.info("Converting motor positions to screen positions")
       logging.info("--------------------------------------------------------------")
       logging.info("  Centred Positions are: ")
       logging.info("       %s" % str(centred_positions_dict.items()))

       logging.info("--------------------------------------------------------------")
       logging.info("  Current Positions are: ")
       logging.info("     phi: %s" % self.phiMotor.getPosition())
       logging.info("   sampx: %s" % self.sampleXMotor.getPosition())
       logging.info("   sampy: %s" % self.sampleYMotor.getPosition())
       logging.info("    phiz: %s" % self.phizMotor.getPosition())
       logging.info("   kappa: %s" % self.kappaMotor.getPosition())
       logging.info("kappaphi: %s" % self.kappaPhiMotor.getPosition())
       logging.info("--------------------------------------------------------------")

       phi_angle = math.radians(-self.phiMotor.getPosition()) 

       dx = (centred_positions_dict["sampx"]-self.sampleXMotor.getPosition()) 
       dy = (centred_positions_dict["sampy"]-self.sampleYMotor.getPosition()) 
       dz = (centred_positions_dict["phiz"]-self.phizMotor.getPosition()) 

       beam_pos_x = self.getBeamPosX()
       beam_pos_y = self.getBeamPosY()

       x = -dz * self.pixelsPerMmZ / 1000.0 + beam_pos_x
       y = (dx * math.sin(phi_angle) + dy * math.cos(phi_angle)) * self.pixelsPerMmY / 1000.0 + beam_pos_y

       beam_pos_x = self.getBeamPosX()
       beam_pos_y = self.getBeamPosY()
       logging.info("   - phi angle = %s " %  phi_angle)
       logging.info("   - phiz saved = %s " % centred_positions_dict["phiz"])
       logging.info("   - dx = %s ( %s - %s )" % (dx , centred_positions_dict["sampx"],self.sampleXMotor.getPosition()) )
       logging.info("   - dy = %s ( %s - %s )" % ( dy , centred_positions_dict["sampy"],self.sampleYMotor.getPosition())  )
       logging.info("   - dz = %s " % dz )
       logging.info("  Screen x = %s " % x )
       logging.info("  Screen y = %s " % y )

       return x, y

   def isValid(self):
       return self.sampleXMotor is not None and \
            self.sampleYMotor is not None and \
            self.zoomMotor is not None and \
            self.phiMotor is not None and \
            self.phizMotor is not None and \
            self.camera is not None

   def isReady(self):
       return self.isValid() and not any([m.motorIsMoving() for m in (self.sampleXMotor, self.sampleYMotor, self.zoomMotor, self.phiMotor, self.phizMotor)])

   def moveToBeam(self, x, y):
       """ To be modified. There is no phiy in this system"""
       if not self.permit:
           logging.info("Trying to move gonio motors to beam. But no permit to operate")
           return

       try:
            beam_xc = self.getBeamPosX()
            beam_yc = self.getBeamPosY()
            self.phizMotor.moveRelative((y-beam_yc)/float(self.pixelsPerMmZ))
            self.phiyMotor.moveRelative((x-beam_xc)/float(self.pixelsPerMmY))
       except:
            logging.getLogger("HWR").exception("MiniDiff: could not center to beam, aborting")

   @task
   def moveToCentredPosition(self, cent_pos):
       if not self.permit:
           logging.info("Trying to move gonio motors to a centred position. But no permit to operate")
           return
       phipos = None
       if type(cent_pos) is dict:
           try:
               sampxpos = cent_pos[self.sampleXMotor]
               sampypos = cent_pos[self.sampleYMotor]
               phizpos = cent_pos[self.phizMotor]
               phipos = cent_pos[self.phiMotor]
               #if 'phi' in cent_pos.keys():
               #   logging.info("################################# moveToCentredPosition ########################")
               #   phipos = cent_pos[self.phiMotor]
           except Exception, err:
               logging.error("MiniDiffPX1.moveToCentredPosition: %s" % err)
	       raise Exception     
       else:
           sampxpos = cent_pos.sampx
           sampypos = cent_pos.sampy
           phizpos = cent_pos.phiz
           phipos = cent_pos.phi

       def wait_ready(timeout=None):
           ready = False
           with gevent.Timeout(timeout):
               while not ready:
                   if not self.phiMotor.motorIsMoving():
                       if not self.phizMotor.motorIsMoving():
                           """ no need to verify sampx, sampy as they are together with phiz in uglide """
                           ready = True 
                   time.sleep(0.1)

       wait_ready(timeout=3)
     
       if self.phiMotor.motorIsMoving():
           raise RuntimeError("Motors not ready")

       if self.phizMotor.motorIsMoving():
           """ no need to verify sampx, sampy as they are together with phiz in uglide """
           raise RuntimeError("Motors not ready")
       if phipos is not None:
           logging.info("WW1: phiMotor_move_to %s" % phipos)
           self.phiMotor.move( phipos )

       uglide_pos = [ sampxpos, sampypos, phizpos ]
       self.microglide.move( uglide_pos )
     
       wait_ready()

   def manualCentringDone(self, manual_centring_procedure):
        logging.info("manual centring DONE")
        try:
          motor_pos = manual_centring_procedure.get()

          if isinstance(motor_pos, gevent.GreenletExit):
             raise motor_pos

          if motor_pos is None:
             self.emitProgressMessage("Centring position aborted. Motor positions are restored")
             logging.info("Centring position aborted. Motor positions are restored")
             self.wait_user_finished()
             self.emitCentringFailed()
             return
        except:
          logging.exception("Could not complete manual centring")
          self.emitCentringFailed()
        else:
          logging.info("Moving sample to centred position")
          self.emitProgressMessage("Moving sample to centred position...")
          self.emitCentringMoving()
          try:
            self.moveToCentredPosition(motor_pos, wait = True)
          except:
            logging.exception("Could not move to centred position")
            self.emitCentringFailed()
          
          logging.info("EMITTING CENTRING SUCCESSFUL")
          self.centredTime = time.time()
          self.emitCentringSuccessful()
          self.emitProgressMessage("")

   def zoomMotorPredefinedPositionChanged(self, positionName, offset):
       logging.getLogger("HWR").info("MiniDiffPX1 zoomMotorPredefinedPositionChanged ")
       _calibration = self.getCalibrationData(self.zoomMotor.getPosition())
       if _calibration[0] and _calibration[1]:
           #logging.info("ZZ1: got calibration positions")
           self.pixelsPerMmY, self.pixelsPerMmZ = _calibration

       #self.beamPositionX, self.beamPositionY = self.getBeamPosition(offset)
       self.emit('zoomMotorPredefinedPositionChanged', (positionName, offset, ))

   def start3ClickCentring_nonblocking(self, sample_info=None):
       logging.info("Three click centering starting")
       self.start3ClickCentring(sample_info=None,wait=False)
       logging.info("Three click centering started. Returning control")

   @task
   def start3ClickCentring(self, sample_info=None):
       
       self.setCentringPhase()
       self.pixelsPerMmY, self.pixelsPerMmZ = self.getCalibrationData(self.zoomMotor.getPosition())
       
       if not self.permit:
           logging.info("Trying to start centring in gonio. But no permit to operate")
           return
       
       centring_points = self.px1conf_ho.getCentringPoints()       
       centring_phi_incr = self.px1conf_ho.getCentringPhiIncrement()       
       centring_sample_type = self.px1conf_ho.getCentringSampleType()       

       #self.currentCentringProcedure = gevent.spawn(sample_centring.manual_centring,
       self.emitProgressMessage("Starting manual centring procedure...")
       self.currentCentringProcedure = sample_centring.manual_centring( {"phi":self.centringPhi,
                                                     "phiy":self.centringPhiz,
                                                     "sampx": self.centringSamplex,
                                                     "sampy": self.centringSampley,
                                                     "kappa": self.centringKappa,
                                                     "kappaPhiMotor": self.centringKappaPhi },
                                                     self.pixelsPerMmY,
                                                     self.pixelsPerMmZ,
                                                     self.getBeamPosX(),
                                                     self.getBeamPosY(),
                                                     n_points=centring_points, phi_incr=centring_phi_incr, sample_type=centring_sample_type,
                                                     diffract=self)

       self.currentCentringProcedure.link(self.manualCentringDone)

   def startAutoCentring_nonblocking(self, sample_info=None, loop_only=False):
       logging.info("Start auto centring in gonio. Non/blocking")
       self.startAutoCentring(sample_info=None, loop_only=False, wait=False)
       logging.info("Start auto centring in gonio. Started")

   @task
   def startAutoCentring(self, sample_info=None, loop_only=False):
        
        self.setCentringPhase()

        self.pixelsPerMmY, self.pixelsPerMmZ = self.getCalibrationData(self.zoomMotor.getPosition())
        
        if not self.permit:
           logging.info("Trying to start centring in gonio. But no permit to operate")
           return
        
        centring_points = self.px1conf_ho.getCentringPoints()       
        centring_phi_incr = self.px1conf_ho.getCentringPhiIncrement()       
        centring_sample_type = self.px1conf_ho.getCentringSampleType()       

        self.emitProgressMessage("Starting automatic centring procedure...")
        self.currentCentringProcedure = sample_centring.start_auto(self.camera,
                                                                   {"phi":self.centringPhi,
                                                                    "phiy":self.centringPhiz,
                                                                    "sampx": self.centringSamplex,
                                                                    "sampy": self.centringSampley,
                                                                    "phiz": self.centringPhiz,
                                                                    "kappa": self.centringKappa,
                                                                    "kappaPhiMotor": self.centringKappaPhi },
                                                                   self.pixelsPerMmY, self.pixelsPerMmZ,
                                                                   self.getBeamPosX(), self.getBeamPosY(),
                                                                   n_points=centring_points, phi_incr=centring_phi_incr, sample_type=centring_sample_type,
                                                                   msg_cb=self.emitProgressMessage,
                                                                   new_point_cb=lambda point: self.emit("newAutomaticCentringPoint", point),diffract=self)

        self.currentCentringProcedure.link(self.autoCentringDone)


   #def imageClicked(self, x, y, xi, yi):
   #    USER_CLICKED_EVENT.set((x,y))

   def wait_user(self, extra_msg=None):
       self.emit("centringState", "waiting")
       msg = "Click on sample to centre. "
       if extra_msg:
           msg += extra_msg
       self.emitProgressMessage(msg)

   def wait_user_end(self):
       self.emit("centringState", "busy")
       self.emitProgressMessage("Please wait...")

   def wait_user_finished(self):
       self.emit("centringState", "finished")

   def getPositions(self):
      logging.debug("getPositions. saving values sampx, sampy, phiz= (%s, %s, %s)" % (self.sampleXMotor.getPosition(), self.sampleYMotor.getPosition(), self.phizMotor.getPosition()))
      return { "phi": self.phiMotor.getPosition(),
               "phiz": self.phizMotor.getPosition(),
               "sampx": self.sampleXMotor.getPosition(),
               "sampy": self.sampleYMotor.getPosition(),
               "kappa": self.kappaMotor.getPosition(),
               "zoom": self.zoomMotor.getPosition()}
               #"focus": self.focusMotor.getPosition(),         
               #"kappa_phi": self.kappaPhiMotor.getPosition(),

   def moveMotors(self, roles_positions_dict):

       if not self.permit:
           logging.info("Trying to move gonio motors . But no permit to operate")
           return

       motor = { "phi": self.phiMotor,
                 "focus": self.focusMotor,
                 "phiz": self.phizMotor,
                 "sampx": self.sampleXMotor,
                 "sampy": self.sampleYMotor,
                 "kappa": self.kappaMotor,
                 "kappa_phi": self.kappaPhiMotor,
                 "zoom": self.zoomMotor }

       for role, pos in roles_positions_dict.iteritems():
           motor[role].move(pos)

       # TODO: remove this sleep, the motors states should
       # be MOVING since the beginning (or READY if move is
       # already finished) 
       time.sleep(1)

       while not all([m.getState() == m.READY for m in motor.itervalues()]):
           time.sleep(0.1)

   def takeSnapshots(self, image_count, wait=False):
        self.camera.forceUpdate = True

        # try:
        #     centring_valid=self.centringStatus["valid"]
        # except:
        #     centring_valid=False
        # if not centring_valid:
        #     logging.getLogger("HWR").error("MiniDiff: you must centre the crystal before taking the snapshots")
        # else:
        snapshotsProcedure = gevent.spawn(take_snapshots, image_count, self.px1env_ho, self.phiMotor, self._drawing)
        self.emit('centringSnapshots', (None,))
        self.emitProgressMessage("Taking snapshots")
        self.centringStatus["images"]=[]
        snapshotsProcedure.link(self.snapshotsDone)

        if wait:
          self.centringStatus["images"] = snapshotsProcedure.get()

   def setCentringPhase(self):

       # allow for some time to get sc permit (it may be necessary after loading)

       t0 = time.time() 
       elapsed = time.time() - t0
       while elapsed < 5.0:
           if self.permit:
               break
           gevent.sleep(0.1)
           elapsed = time.time() - t0

       if not self.permit:
           logging.info("Trying to set centring phase. But no permit to operate")
           return
       
       _ready = self.px1env_ho.readyForCentring()

       logging.info("MiniDiffPX1: readyForCentring = %s" % _ready)

       if not _ready:
           self.px1env_ho.setPhase(EnvironmentPhase.CENTRING)
       else:
           logging.info("Trying to set centring phase. But already in CENTRING phase.")
           return

       #if self.zoomMotor.getCurrentPositionName() != "Zoom 1":
       #    self.zoomMotor.moveToPosition("Zoom 1")

       self.phase = self.px1env_ho.readPhase() #"CENTRING"
       self.emit("phaseChanged", (self.phase,))

   def setLoadingPhase(self):

       if not self.permit:
           logging.info("Trying to set loading phase. But no permit to operate")
           return
       
       _ready = self.px1env_ho.readyForManualTransfer()
       logging.info("MiniDiffPX1: readyForManualTransfer = %s" % _ready)
       if not _ready:
           self.px1env_ho.setPhase(EnvironmentPhase.MANUALTRANSFER)
       else:
           logging.info("Trying to set loading phase. But already in that phase.")
           return

       #self.guillotine.setIn()
       #self.microglide.home()

       if self.obx.getShutterState() == "opened":
           self.obx.closeShutter() 

       self.phase = self.px1env_ho.readPhase() #"LOADING"
       self.emit("phaseChanged", (self.phase,))
        

def take_snapshots(number_of_snapshots, px1env, phi, drawing):

  centredImages = []

  logging.getLogger("HWR").info("PX1 take snapshots")

  if px1env is not None:

    logging.getLogger("HWR").info("take snapshots:  putting the light in")
    _ready = px1env.readyForVisuSample()
    
    logging.info("MiniDiffPX1: readyForManualTransfer = %s" % _ready)
    if not _ready:
        with gevent.Timeout(25):
            px1env.setPhase(EnvironmentPhase.VISUSAMPLE)
            while not px1env.readState() == "ON":
                time.sleep(0.05)
    else:
        logging.info("Trying to set visusample phase. But already in that phase.")

  #for i in range(4):
  #   logging.getLogger("HWR").info("MiniDiff: taking snapshot #%d", i+1)
  #   centredImages.append((phi.getPosition(),str(myimage(drawing))))
  #   if i < 3:
  #      phi.syncMoveRelative(-90)
  #   time.sleep(2)

  for i, angle in enumerate([-90]*number_of_snapshots):
     logging.getLogger("HWR").info("MiniDiff: taking snapshot #%d", i+1)
     centredImages.append((phi.getPosition(),str(myimage(drawing))))
     if i < (number_of_snapshots-1):
        phi.syncMoveRelative(angle)
  
  centredImages.reverse() # snapshot order must be according to positive rotation direction

  return centredImages
