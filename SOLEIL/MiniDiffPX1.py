import gevent
from gevent.event import AsyncResult

import numpy
import math
import logging, time
from MiniDiff import MiniDiff, manual_centring
import PyTango
from HardwareRepository.TaskUtils import *
USER_CLICKED_EVENT = AsyncResult()


def manual_centring(phi, phiy, phiz, sampx, sampy, pixelsPerMmY, pixelsPerMmZ,
                    beam_xc, beam_yc, kappa, omega, phiy_direction=1):
  logging.info("MiniDiffPX1: Starting manual_centring")
  global USER_CLICKED_EVENT
  X, Y, PHI = [], [], []
  centredPosRel = {}

  if all([x.isReady() for x in (phi, phiy, phiz, sampx, sampy)]):
    phiSavedPosition = phi.getPosition()
    #phiSavedDialPosition = phi.getDialPosition()
    phiSavedDialPosition = 327.3
    logging.info("MiniDiff phi saved dial = %f " % phiSavedDialPosition)
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
    #resolution d equation
    #print "angle1 = %4.1f  angle2 = %4.1f   angle3 = %4.1f " % \
    #                  (self.anglePhi[0], self.anglePhi[1], self.anglePhi[2])
    PhiCamera=90

    #yc = (Y[0]+Y[2]) / 2.
    #y =  Y[0] - yc
    #x =  yc - Y[1]
    print "MANUAL_CENTRING:", X, Y, pixelsPerMmY, pixelsPerMmZ, beam_xc, beam_yc
    #b1 = -math.radians(phiSavedDialPosition)
    #b1 = -math.radians(phiSavedPosition - phiSavedDialPosition)
    #rotMatrix = numpy.matrix([math.cos(b1), -math.sin(b1), math.sin(b1), math.cos(b1)])
    #rotMatrix.shape = (2,2)
    #dx, dy = numpy.dot(numpy.array([x,y]), numpy.array(rotMatrix))/pixelsPerMmY 

    a1=math.radians(PHI[0]+PhiCamera)
    a2=math.radians(PHI[1]+PhiCamera)
    a3=math.radians(PHI[2]+PhiCamera)
    p01=(dy1*math.sin(a2)-dy2*math.sin(a1))/math.sin(a2-a1)        
    q01=(dy1*math.cos(a2)-dy2*math.cos(a1))/math.sin(a1-a2)
    p02=(dy1*math.sin(a3)-dy3*math.sin(a1))/math.sin(a3-a1)        
    q02=(dy1*math.cos(a3)-dy3*math.cos(a1))/math.sin(a1-a3)
    p03=(dy3*math.sin(a2)-dy2*math.sin(a3))/math.sin(a2-a3)        
    q03=(dy3*math.cos(a2)-dy2*math.cos(a3))/math.sin(a3-a2)
    #print "p01 = %6.3f  q01 = %6.3f  p02 = %6.3f  q02 = %6.3f  p03 = %6.3f  q03 = %6.3f  " %(p01,q01,p02,q02,p03,q03)

    x_echantillon=(p01+p02+p03)/3.0
    y_echantillon=(q01+q02+q03)/3.0
    z_echantillon=(-dx1-dx2-dx3)/3.0
    print "Microglide X = %d :    Y = %d :    Z = %d : " %(x_echantillon,y_echantillon,z_echantillon)
        
    x_echantillon_real=1000.*x_echantillon/pixelsPerMmY
    y_echantillon_real=1000.*y_echantillon/pixelsPerMmY
    z_echantillon_real=1000.*z_echantillon/pixelsPerMmY

    #beam_xc_real = beam_xc / float(pixelsPerMmY)
    #beam_yc_real = beam_yc / float(pixelsPerMmZ)
    #y = yc / float(pixelsPerMmZ)
    #x = sum(X) / 3.0 / float(pixelsPerMmY)
    #centredPos = { sampx: sampx.getPosition() + float(dx),
    #               sampy: sampy.getPosition() + float(dy),
    #               phiy: phiy.getPosition() + phiy_direction * (x - beam_xc_real),
    #               phiz: phiz.getPosition() + (y - beam_yc_real) }
    if (z_echantillon_real + phiy.getPosition() < phiy.getLimits()[0]) :
        logging.getLogger("HWR").error("loop too long")
        print 'loop too long '
        centredPos = {}
        phi.move(phiSavedPosition)            
    else :    
        print 'loop Ok '
        centredPos= { sampx: x_echantillon_real,
                      sampy: y_echantillon_real,
                      phiy: z_echantillon_real}
    print 'Fin procedure de centrage'
    print "   sampx: %.1f" % x_echantillon_real
    print "   sampy: %.1f" % y_echantillon_real
    print "   phiy:  %.1f" % z_echantillon_real
    #try:
    #    sampx.move(x_echantillon_real)
    #    sampy.move(y_echantillon_real)
    #    phiy.move(z_echantillon_real)
    #except:
    #    raise
    return centredPos
  except:
    phi.move(phiSavedPosition)    
    raise

@task
def move_to_centred_position(centred_pos):
  logging.getLogger("HWR").info("move_to_centred_position")
  pos_to_go = []
  for motor, pos in centred_pos.iteritems():
    #print "AAA motor:", motor.name(), " pos:", pos #, dir(motor)
    pos_to_go.append(pos)
    if motor.name() in ["/uglidex", "/uglidey"]:
        #print "--->",  motor.name(), motor.getCommandNamesList()
        moveXYZ = motor.getCommandObject("moveRelativeXYZ")        
  print "POS_TO_GO: %8.2f %8.2f %8.2f" % tuple(pos_to_go)
  moveXYZ(pos_to_go)

  with gevent.Timeout(15):
    while not all([m.getState() == m.READY for m in centred_pos.iterkeys()]):
      time.sleep(0.1)



class MiniDiffPX1(MiniDiff):

   def _init(self,*args):
       MiniDiff._init(self, *args)

       self.md2_ready = True

       #try:
       #   self.md2 = PyTango.DeviceProxy( self.tangoname )
       #except:
       #   logging.error("MiniDiffPX2 / Cannot connect to tango device: %s ", self.tangoname )
       #else:
       #   self.md2_ready = True

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

   def getState(self):
       logging.info("XX1 getState")
       print "phi_position", self.phiMotor.getPosition()
       #return str( self.md2.state() )
       return "STANDBY"

   def setScanStartAngle(self, sangle):
       logging.info("XX1 / setting start angle to %s ", sangle )
       if self.md2_ready:
           self.md2.write_attribute("ScanStartAngle", sangle )

   def startScan(self,wait=True):
       logging.info("XX1 / starting scan " )

       if self.md2_ready:
           diffstate = self.getState()
           logging.info("SOLEILCollect - diffractometer scan started  (state: %s)" % diffstate)
           self.md2.StartScan()

       # self.getCommandObject("start_scan")() - if we define start_scan command in *xml

#   def goniometerReady(self, oscrange, npass, exptime):
#       logging.info("MiniDiffPX2 / programming gonio oscrange=%s npass=%s exptime=%s" % (oscrange,npass, exptime) )
#
#       if self.md2_ready:
#
#          diffstate = self.getState()
#          logging.info("SOLEILCollect - setting gonio ready (state: %s)" % diffstate)
#
#          self.md2.write_attribute('ScanAnticipation', self.anticipation)
#          self.md2.write_attribute('ScanNumberOfPasses', npass)
#          self.md2.write_attribute('ScanRange', oscrange)
#          self.md2.write_attribute('ScanExposureTime', exptime)
#          self.md2.write_attribute('PhasePosition', self.collect_phaseposition)

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

   def getCalibrationData(self, offset):
       #logging.info("XX1: getCalibration, OFFSET: %s", offset)
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
       #logging.error("!!! ERROR in zoom calibration")
       return (None, None)

   def motor_positions_to_screen(self, centred_positions_dict):
       logging.info("XX1: setting start angle to %s ", sangle )
       self.pixelsPerMmY, self.pixelsPerMmZ = self.getCalibrationData(self.zoomMotor.getPosition())
       phi_angle = math.radians(-self.phiMotor.getPosition()) #centred_positions_dict["phi"])
       #logging.info("CENTRED POS DICT = %r", centred_positions_dict)
       sampx = centred_positions_dict["sampx"]-self.sampleXMotor.getPosition()
       sampy = centred_positions_dict["sampy"]-self.sampleYMotor.getPosition()
       phiy = self.phiy_direction * (centred_positions_dict["phiy"]-self.phiyMotor.getPosition())
       logging.info("phiy move = %f", centred_positions_dict["phiy"]-self.phiyMotor.getPosition())
       phiz = centred_positions_dict["phiz"]-self.phizMotor.getPosition()
       #logging.info("sampx=%f, sampy=%f, phiy=%f, phiz=%f, phi=%f", sampx, sampy, phiy, phiz, phi_angle)
       rotMatrix = numpy.matrix([math.cos(phi_angle), -math.sin(phi_angle), math.sin(phi_angle), math.cos(phi_angle)])
       rotMatrix.shape = (2, 2)
       invRotMatrix = numpy.array(rotMatrix.I)
       dx, dy = numpy.dot(numpy.array([sampx, sampy]), invRotMatrix)*self.pixelsPerMmY
       beam_pos_x = self.getBeamPosX()
       beam_pos_y = self.getBeamPosY()

       x = (phiy * self.pixelsPerMmY) + beam_pos_x
       y = dy + (phiz * self.pixelsPerMmZ) + beam_pos_y

       return x, y

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
            move_to_centred_position(motor_pos, wait = True)
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
       self.currentCentringProcedure = gevent.spawn(manual_centring, 
                                                    self.phiMotor,
                                                    self.phiyMotor,
                                                    self.phizMotor,
                                                    self.sampleXMotor,
                                                    self.sampleYMotor,
                                                    self.pixelsPerMmY,
                                                    self.pixelsPerMmZ,
                                                    self.getBeamPosX(),
                                                    self.getBeamPosY(),
                                                    self.kappaMotor,
                                                    self.kappaPhiMotor,
                                                    self.phiy_direction)     
       self.currentCentringProcedure.link(self.manualCentringDone)

   def imageClicked(self, x, y, xi, yi):
       USER_CLICKED_EVENT.set((x,y))

   def getPositions(self):
      return { "phi": self.phiMotor.getPosition(),
               "phiy": self.phiyMotor.getPosition(),
               "phiz": self.phizMotor.getPosition(),
               "sampx": self.sampleXMotor.getPosition(),
               "sampy": self.sampleYMotor.getPosition(),
               "kappa": self.kappaMotor.getPosition(),
               "zoom": self.zoomMotor.getPosition()}
               #"focus": self.focusMotor.getPosition(),         
               #"kappa_phi": self.kappaPhiMotor.getPosition(),