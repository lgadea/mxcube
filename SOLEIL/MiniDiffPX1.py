import gevent
from gevent.event import AsyncResult
import sample_centring

import numpy
import math
import logging, time
from MiniDiff import MiniDiff, myimage
from HardwareRepository import HardwareRepository

import PyTango
from HardwareRepository.TaskUtils import *

USER_CLICKED_EVENT = AsyncResult()

def manual_centring(phi, phiz, sampx, sampy, pixelsPerMmY, pixelsPerMmZ,
                    beam_xc, beam_yc, kappa, omega):
  global USER_CLICKED_EVENT
  X, Y, PHI = [], [], []
  centredPosRel = {}

  if all([x.isReady() for x in (phi, phiz, sampx, sampy)]):
    phiSavedPosition = phi.getPosition()
    #phiSavedDialPosition = phi.getDialPosition()
    phiSavedDialPosition = 327.3
  else:
    raise RuntimeError, "motors not ready"
  
  kappa.move(0)
  omega.move(0)

  try:  
    while True:
      USER_CLICKED_EVENT = AsyncResult()
      x, y = USER_CLICKED_EVENT.get()
      X.append(x)
      Y.append(y)
      PHI.append(phi.getPosition())
      if len(X) == 3:
        break
      phi.moveRelative(60)

    # 2014-01-19-bessy-mh: variable beam position coordinates are passed as parameters
    #beam_xc = imgWidth / 2
    #beam_yc = imgHeight / 2

    (dx1,dy1,dx2,dy2,dx3,dy3)=(X[0] - beam_xc, Y[0] - beam_yc,
                               X[1] - beam_xc, Y[1] - beam_yc,
                               X[2] - beam_xc, Y[2] - beam_yc)
    PhiCamera=90

    logging.debug("MANUAL_CENTRING: X=%s, Y=%s (Calib=%s/%s) (BeamCen=%s/%s)" % (X, Y, pixelsPerMmY, pixelsPerMmZ, beam_xc, beam_yc))

    a1=math.radians(PHI[0]+PhiCamera)
    a2=math.radians(PHI[1]+PhiCamera)
    a3=math.radians(PHI[2]+PhiCamera)
    p01=(dy1*math.sin(a2)-dy2*math.sin(a1))/math.sin(a2-a1)        
    q01=(dy1*math.cos(a2)-dy2*math.cos(a1))/math.sin(a1-a2)
    p02=(dy1*math.sin(a3)-dy3*math.sin(a1))/math.sin(a3-a1)        
    q02=(dy1*math.cos(a3)-dy3*math.cos(a1))/math.sin(a1-a3)
    p03=(dy3*math.sin(a2)-dy2*math.sin(a3))/math.sin(a2-a3)        
    q03=(dy3*math.cos(a2)-dy2*math.cos(a3))/math.sin(a3-a2)

    x_echantillon=(p01+p02+p03)/3.0
    y_echantillon=(q01+q02+q03)/3.0
    z_echantillon=(-dx1-dx2-dx3)/3.0
    print "Microglide X = %d :    Y = %d :    Z = %d : " %(x_echantillon,y_echantillon,z_echantillon)
        
    x_echantillon_real=1000.*x_echantillon/pixelsPerMmY + sampx.getPosition()
    y_echantillon_real=1000.*y_echantillon/pixelsPerMmY + sampy.getPosition()
    z_echantillon_real=1000.*z_echantillon/pixelsPerMmY + phiz.getPosition()

    if (z_echantillon_real + phiz.getPosition() < phiz.getLimits()[0]) :
        logging.getLogger("HWR").error("loop too long")
        print 'loop too long '
        centredPos = {}
        phi.move(phiSavedPosition)            
    else :    
        centredPos= { sampx: x_echantillon_real,
                      sampy: y_echantillon_real,
                      phiz: z_echantillon_real}
    return centredPos
  except:
    phi.move(phiSavedPosition)    
    raise


@task
def move_to_centred_position(centred_pos):
     logging.getLogger("HWR").info("move_to_centred_position")
     pos_to_go = []
     for motor, pos in centred_pos.iteritems():
       pos_to_go.append(pos)
       if motor.name() in ["/uglidex", "/uglidey"]:
           moveXYZ = motor.getCommandObject("moveAbsoluteXYZ")
     print "POS_TO_GO: %8.2f %8.2f %8.2f" % tuple(pos_to_go)
     moveXYZ(pos_to_go)
   
     with gevent.Timeout(15):
       while not all([m.getState() == m.READY for m in centred_pos.iterkeys()]):
         time.sleep(0.1)

class MiniDiffPX1(MiniDiff):

   def __init__(self,*args):
       MiniDiff.__init__(self, *args)
   
   def init(self,*args):
       MiniDiff.init(self, *args)

       self.permit = True
       self.phase = None

       bs_prop=self.getProperty("bstop")
       self.bstop_ho = None
       logging.getLogger().info("MiniDiffPX1.  Loading %s as beamstop " % str(bs_prop))

       if bs_prop is not None:
            try:
                self.bstop_ho=HardwareRepository.HardwareRepository().getHardwareObject(bs_prop)
            except:
                import traceback
                logging.getLogger().info("MiniDiffPX1.  Cannot load beamstop %s" % str(bs_prop))
                logging.getLogger().info("    - reason: " + traceback.format_exc())

       self.microglide = self.getDeviceByRole('microglide')
       self.guillotine = self.getDeviceByRole('guillotine')
       self.detectorDistanceMotor = self.getDeviceByRole('detdist')

       self.obx = self.getDeviceByRole('obx')

       if self.sampleChanger is not None:
            self.scAuthChan = self.sampleChanger.getChannelObject("softwareAuthorization")
            self.scAuthChan.connectSignal("update", self.SCauthorizationChanged )
            logging.getLogger().info("MiniDiffPX1. Connection to authorization signal done")
                    #self.connect(self.samplechanger, "gonioMovementAuthorized", self.SCauthorizationChanged )
       else:
            logging.getLogger().info("MiniDiffPX1. Cannot connect authorization signal. NO samplechanger")

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
       if self.beamstopIn() == -1:
           raise Exception("Minidiff cannot get to acquisition mode")
       self.guillotine.setOut()

   def SCauthorizationChanged(self, value):
       self.setAuthorizationFlag("samplechanger", value)
       logging.getLogger("HWR").debug("%s: MiniDiff. Authorization from SC changed. Now is %s.", self.name(), value )

   def setAuthorizationFlag(self, flag, value):
       if flag == "samplechanger":
            self.sc_permit = value

       # make here the logic with eventually other permits (like hardware permit)

       self.permit = self.sc_permit

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
       logging.info("XX1 getState")
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
       logging.info("XX1: getCalibration, OFFSET: %s", offset)

       if self.lightMotor is None or self.lightMotor.positionChan.device is None:
           logging.info("XX1: getCalibration, Not yet initialized")
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
                       self.light_level = float(position.lightLevel)
                       self.lightMotor.move(self.light_level)
                       print "CALIBR:", (self.calib_x, self.calib_y)
                       print "BEAMXY:", (self.beam_xc, self.beam_yc)
                       return (self.calib_x or 0, self.calib_y or 0)

       return (None, None)

   def motor_positions_to_screen(self, centred_positions_dict):

       self.pixelsPerMmY, self.pixelsPerMmZ = self.getCalibrationData(self.zoomMotor.getPosition())

       #phi_angle = math.radians(self.phiMotor.getPosition()-centred_positions_dict["phi"]) 
       phi_angle = math.radians(-self.phiMotor.getPosition()) 

       dx = (centred_positions_dict["sampx"]-self.sampleXMotor.getPosition()) 
       dy = (centred_positions_dict["sampy"]-self.sampleYMotor.getPosition()) 
       
       #dx = centred_positions_dict["sampx"]
       #dy = centred_positions_dict["sampy"]
       dz = (centred_positions_dict["phiz"]-self.phizMotor.getPosition()) 

       beam_pos_x = self.getBeamPosX()
       beam_pos_y = self.getBeamPosY()

       x = -dz * self.pixelsPerMmZ / 1000.0 + beam_pos_x
       y = (-dx * math.cos(phi_angle) + dy * math.sin(phi_angle)) * self.pixelsPerMmY / 1000.0 + beam_pos_y

       logging.info("Converting motor positions to screen positions")

       beam_pos_x = self.getBeamPosX()
       beam_pos_y = self.getBeamPosY()
       logging.info("   - phi angle = %s " %  phi_angle)
       logging.info("   - phiz saved = %s " % centred_positions_dict["phiz"])
       logging.info("   - pixels per mm X = %s " % self.pixelsPerMmY )
       logging.info("   - pixels per mm Y = %s " % self.pixelsPerMmZ )
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

       logging.getLogger("HWR").info("moveToCentredPosition")
       logging.getLogger("HWR").info("     - %s " % str(cent_pos) )

       phipos = None
       if type(cent_pos) is dict:
           sampxpos = cent_pos[self.sampleXMotor]
           sampypos = cent_pos[self.sampleYMotor]
           phizpos = cent_pos[self.phizMotor]
           if 'phi' in cent_pos.keys():
              phipos = cent_pos[self.phiMotor]
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
        except:
          logging.exception("Could not complete manual centring")
          self.emitCentringFailed()
        else:
          logging.info("Moving sample to centred position")
          self.emitProgressMessage("Moving sample to centred position...")
          self.emitCentringMoving()
          try:
            logging.debug(str(motor_pos))
            self.moveToCentredPosition(motor_pos, wait = True)
          except:
            logging.exception("Could not move to centred position")
            self.emitCentringFailed()
          else:
            self.phiMotor.syncMoveRelative(-180)
          logging.info("EMITTING CENTRING SUCCESSFUL")
          self.centredTime = time.time()
          self.emitCentringSuccessful()
          self.emitProgressMessage("")

   def zoomMotorPredefinedPositionChanged(self, positionName, offset):
       logging.info("XX1: zoomMotorPredefinedPositionChanged, OFFSET: %s", offset)       
       self.pixelsPerMmY, self.pixelsPerMmZ = self.getCalibrationData(offset)
       #self.beamPositionX, self.beamPositionY = self.getBeamPosition(offset)
       self.emit('zoomMotorPredefinedPositionChanged', (positionName, offset, ))

   def start3ClickCentring(self, sample_info=None):
       if not self.permit:
           logging.info("Trying to start centring in gonio. But no permit to operate")
           return

       self.currentCentringProcedure = gevent.spawn(manual_centring, 
                                                    self.phiMotor,
                                                    self.phizMotor,
                                                    self.sampleXMotor,
                                                    self.sampleYMotor,
                                                    self.pixelsPerMmY,
                                                    self.pixelsPerMmZ,
                                                    self.getBeamPosX(),
                                                    self.getBeamPosY(),
                                                    self.kappaMotor,
                                                    self.kappaPhiMotor)     
       self.currentCentringProcedure.link(self.manualCentringDone)

   def imageClicked(self, x, y, xi, yi):
       USER_CLICKED_EVENT.set((x,y))

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

   def takeSnapshots(self, wait=False):
        self.camera.forceUpdate = True

        # try:
        #     centring_valid=self.centringStatus["valid"]
        # except:
        #     centring_valid=False
        # if not centring_valid:
        #     logging.getLogger("HWR").error("MiniDiff: you must centre the crystal before taking the snapshots")
        # else:
        snapshotsProcedure = gevent.spawn(take_snapshots, self.lightWago, self.lightMotor ,self.phiMotor,self.zoomMotor,self._drawing)
        self.emit('centringSnapshots', (None,))
        self.emitProgressMessage("Taking snapshots")
        self.centringStatus["images"]=[]
        snapshotsProcedure.link(self.snapshotsDone)

        if wait:
          self.centringStatus["images"] = snapshotsProcedure.get()

   def setCentringPhase(self):

       if not self.permit:
           logging.info("Trying to set centring phase. But no permit to operate")
           return

       if self.kappaMotor.getPosition() > 0.01:
           self.kappaMotor.move(0.)

       if self.phiMotor.getPosition() > 0.01:
           self.phiMotor.move(0.)

       if self.zoomMotor.getCurrentPositionName() != "Zoom 1":
           self.zoomMotor.moveToPosition("Zoom 1")

       if self.lightWago.getState() == "out":
           self.lightWago.setIn()

       self.phase = "CENTRING"
       self.emit("phaseChanged", (self.phase,))

   def setLoadingPhase(self):

       if not self.permit:
           logging.info("Trying to set loading phase. But no permit to operate")
           return

       self.guillotine.setIn()
       self.microglide.home()

       if self.phiMotor.getPosition() != -17.:
           self.phiMotor.move(-17.)

       if self.kappaMotor.getPosition() != 55.:
           self.kappaMotor.move(55.)

       if self.zoomMotor.getCurrentPositionName() != "Zoom 1":
           self.zoomMotor.moveToPosition("Zoom 1")

       if self.obx.getShutterState() == "opened":
           self.obx.closeShutter() 

       if self.detectorDistanceMotor:
           if self.detectorDistanceMotor.getPosition() <= 350:
               self.detectorDistanceMotor.move(350.)

       if self.lightWago.getState() == "in":
           self.lightWago.setOut()
       else:
           logging.info("not getting out light arm as it was %s" % self.lightWago.getState())

       self.phase = "LOADING"
       self.emit("phaseChanged", (self.phase,))


def take_snapshots(light, light_motor, phi, zoom, drawing):

  centredImages = []

  logging.getLogger("HWR").info("PX1 take snapshots")

  if light is not None:

    logging.getLogger("HWR").info("take snapshots:  putting the light in")
    light.wagoIn()

    zoom_level  = zoom.getPosition()
    light_level = light_motor.getPosition()
    logging.getLogger("HWR").info("take snapshots:  zoom level is %s / light level is %s" % (str(zoom_level), str(light_level)))

    # No light level, choose default
    if light_motor.getPosition() == 0:

       light_level = None

       logging.getLogger().info("take snapshots: looking for default light level for this zoom ")
       for position in zoom['positions']:
          try:
              offset = position.offset
              logging.getLogger().info("take snapshots: zoom-level is: %s / comparing with table position: %s " % (str(zoom_level), str(offset)))
              if int(offset) == int(zoom_level):
                 light_level = position['ligthLevel']
                 logging.getLogger().info("take snapshots - light level for zoom position %s is %s" % (str(zoom_level),str(light_level)))
          except IndexError:
              pass

       if light_level:
          light_motor.move(light_level)

    t0 = time.time(); timeout = 5

    while light.getWagoState() != "in":
      time.sleep(0.5)
      if (time.time() - t0) > timeout:
          raise Exception("SnapshotException","Timeout while inserting light")

  for i in range(4):
     logging.getLogger("HWR").info("MiniDiff: taking snapshot #%d", i+1)
     centredImages.append((phi.getPosition(),str(myimage(drawing))))
     if i < 3:
        phi.syncMoveRelative(-90)
     time.sleep(2)
  #phi.syncMoveRelative(270)

  centredImages.reverse() # snapshot order must be according to positive rotation direction

  return centredImages

