from scipy import optimize
import numpy
import gevent.event
import math
import time
import logging
import os
import tempfile

try:
  import lucid2
except ImportError:
  logging.warning("lucid2 cannot load: automatic centring is disabled")


def multiPointCentre(z,phis) :
    fitfunc = lambda p,x: p[0] * numpy.sin(x+p[1]) + p[2]
    errfunc = lambda p,x,y: fitfunc(p,x) - y
    p1, success = optimize.leastsq(errfunc,[1.,0.,0.],args = (phis,z))
    return p1

USER_CLICKED_EVENT = None
CURRENT_CENTRING = None
SAVED_INITIAL_POSITIONS = {}
READY_FOR_NEXT_POINT = gevent.event.Event()
PHI_ANGLE_INCREMENT = 120

class CentringMotor:
  def __init__(self, motor, reference_position=None, direction=1):
    self.motor = motor
    self.direction = direction
    self.reference_position = reference_position
  def __getattr__(self, attr):
    # delegate to motor object
    if attr.startswith("__"):
      raise AttributeError(attr)
    else:
      return getattr(self.motor, attr)
  

def manual_centring(centring_motors_dict,
          pixelsPerMm_Hor, pixelsPerMm_Ver,
          beam_xc, beam_yc,
          chi_angle = 0,
          n_points = 3):

  global CURRENT_CENTRING

  phi, phiy, sampx, sampy = prepare(centring_motors_dict)

  CURRENT_CENTRING = gevent.spawn(px1_center,
                                  phi,
                                  phiy,
                                  sampx,
                                  sampy,
                                  pixelsPerMm_Hor, pixelsPerMm_Ver,
                                  beam_xc, beam_yc,
                                  chi_angle,
                                  n_points)

  return CURRENT_CENTRING

def px1_center(phi, phiy,
           sampx, sampy,
           pixelsPerMm_Hor, pixelsPerMm_Ver,
           beam_xc, beam_yc,
           chi_angle,
           n_points):

  global USER_CLICKED_EVENT
  X, Y, PHI = [], [], []
  centredPosRel = {}
  
  try:  
    while True:
      logging.getLogger("HWR").info("waiting for user input")
      x, y = USER_CLICKED_EVENT.get()
      logging.getLogger("HWR").info("   got user input x=%f / y=%f" % (x,y))
      USER_CLICKED_EVENT = gevent.event.AsyncResult()  

      X.append(x)
      Y.append(y)
      PHI.append(phi.getPosition())
      if len(X) == 3:
        READY_FOR_NEXT_POINT.set()
        break
      phi.syncMoveRelative(PHI_ANGLE_INCREMENT)
      READY_FOR_NEXT_POINT.set()

    (dx1,dy1,dx2,dy2,dx3,dy3)=(X[0] - beam_xc, Y[0] - beam_yc,
                               X[1] - beam_xc, Y[1] - beam_yc,
                               X[2] - beam_xc, Y[2] - beam_yc)
    PhiCamera=90

    logging.getLogger("HWR").info("MANUAL_CENTRING: X=%s, Y=%s (Calib=%s/%s) (BeamCen=%s/%s)" % (X, Y, pixelsPerMm_Hor, pixelsPerMm_Ver, beam_xc, beam_yc))

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
    
    x_echantillon_real=1000.*x_echantillon/pixelsPerMm_Hor + sampx.getPosition()
    y_echantillon_real=1000.*y_echantillon/pixelsPerMm_Hor + sampy.getPosition()
    z_echantillon_real=1000.*z_echantillon/pixelsPerMm_Hor + phiy.getPosition()

    if (z_echantillon_real + phiy.getPosition() < phiy.getLimits()[0]*2) :
        logging.getLogger("HWR").error("loop too long")
        centredPos = {}
        move_motors(SAVED_INITIAL_POSITIONS)
        raise

    centred_pos = SAVED_INITIAL_POSITIONS.copy()
    centred_pos.update({ sampx.motor: x_echantillon_real,
                         sampy.motor: y_echantillon_real,
                         phiy.motor: z_echantillon_real})
    return centred_pos

  #except Exception, e:
    #logging.getLogger("HWR").error("MiniDiffPX1: Centring error: %s" % e)
  except: 
    import traceback
    logging.getLogger("HWR").error("MiniDiffPX1: Centring error")
    logging.getLogger("HWR").info( traceback.format_exc() )

    move_motors(SAVED_INITIAL_POSITIONS)
    raise

def prepare(centring_motors_dict):
  global SAVED_INITIAL_POSITIONS

  if CURRENT_CENTRING and not CURRENT_CENTRING.ready():
    raise RuntimeError("Cannot start new centring while centring in progress")
  
  global USER_CLICKED_EVENT
  USER_CLICKED_EVENT = gevent.event.AsyncResult()  

  move_motors(dict([(m.motor, m.reference_position if m.reference_position is not None else m.getPosition()) for m in centring_motors_dict.itervalues()]))
  SAVED_INITIAL_POSITIONS = dict([(m.motor, m.motor.getPosition()) for m in centring_motors_dict.itervalues()])

  phi = centring_motors_dict["phi"]
  phiy = centring_motors_dict["phiy"]
  sampx = centring_motors_dict["sampx"]
  sampy = centring_motors_dict["sampy"]

  return phi, phiy, sampx, sampy
  
def start(centring_motors_dict,
          pixelsPerMm_Hor, pixelsPerMm_Ver, 
          beam_xc, beam_yc,
          chi_angle = 0,
          n_points = 3):
  global CURRENT_CENTRING

  phi, phiy, sampx, sampy = prepare(centring_motors_dict)

  CURRENT_CENTRING = gevent.spawn(center, 
                                  phi,
                                  phiy,
                                  sampx, 
                                  sampy, 
                                  pixelsPerMm_Hor, pixelsPerMm_Ver, 
                                  beam_xc, beam_yc,
                                  chi_angle,
                                  n_points)
  return CURRENT_CENTRING

def ready(*motors):
  for m in motors:
     if m.motorIsMoving(): 
        return False
     else:
        motname = m.name()
        if motname in ["/uglidex", "/uglidey", "/uglidez"]:
            logging.getLogger("HWR").info("  -- %s is not moving" % motname)
        
  return True

#def ready(*motors):
  #return not any([m.motorIsMoving() for m in motors])

def move_motors(motor_positions_dict):
  def wait_ready(timeout=None):
    with gevent.Timeout(timeout):
      while not ready(*motor_positions_dict.keys()):
        time.sleep(0.1)
      logging.getLogger("HWR").info("  -- wait ready done")

  wait_ready(timeout=3)

  if not ready(*motor_positions_dict.keys()):
    raise RuntimeError("Motors not ready")

  xyz_togo = {}
  moveXYZ = None
  for motor, position in motor_positions_dict.iteritems():
    motname = motor.name()
    logging.getLogger("HWR").info("  -- moving motor %s to position %s " % (motname,position))
    if motname in ["/uglidex", "/uglidey", "/uglidez"]:
       xyz_togo[motname] = position
       moveXYZ = motor.getCommandObject("moveAbsoluteXYZ")
    else:
       motor.move(position)

  # move microglide
  if moveXYZ:
     if '/uglidex' not in xyz_togo:
        logging.getLogger("HWR").info("no uglidex")
        raise
     elif '/uglidey' not in xyz_togo:
        logging.getLogger("HWR").info("no uglidey")
        raise
     elif '/uglidez' not in xyz_togo:
        logging.getLogger("HWR").info("no uglidez")
        raise
     else:
        glide_goto = [xyz_togo['/uglidex'], xyz_togo['/uglidey'], xyz_togo['/uglidez']]
        logging.getLogger("HWR").info("  -- moving microglide motors") 
        moveXYZ(glide_goto)
  
  wait_ready()
  
def user_click(x,y, wait=False):
  READY_FOR_NEXT_POINT.clear()
  USER_CLICKED_EVENT.set((x,y))
  if wait:
    READY_FOR_NEXT_POINT.wait()
  
def center(phi, phiy,
           sampx, sampy, 
           pixelsPerMm_Hor, pixelsPerMm_Ver, 
           beam_xc, beam_yc,
           chi_angle,
           n_points):
  global USER_CLICKED_EVENT
  X, Y, phi_positions = [], [], []

  phi_angle = 180.0/(n_points-1)

  try:
    i = 0
    while i < n_points:
      x, y = USER_CLICKED_EVENT.get()
      USER_CLICKED_EVENT = gevent.event.AsyncResult()
      X.append(x / float(pixelsPerMm_Hor))
      Y.append(y / float(pixelsPerMm_Ver))
      phi_positions.append(phi.direction*math.radians(phi.getPosition()))
      phi.syncMoveRelative(phi.direction*phi_angle)
      READY_FOR_NEXT_POINT.set()
      i += 1
  except:
    move_motors(SAVED_INITIAL_POSITIONS)
    raise

  #logging.info("X=%s,Y=%s", X, Y)
  chi_angle = math.radians(chi_angle)
  chiRotMatrix = numpy.matrix([[math.cos(chi_angle), -math.sin(chi_angle)],
                               [math.sin(chi_angle), math.cos(chi_angle)]])
  Z = chiRotMatrix*numpy.matrix([X,Y])
  z = Z[1]; avg_pos = Z[0].mean()

  r, a, offset = multiPointCentre(numpy.array(z).flatten(), phi_positions)
  dy = r * numpy.sin(a)
  dx = r * numpy.cos(a)
  
  d = chiRotMatrix.transpose()*numpy.matrix([[avg_pos],
                                             [offset]])

  d_horizontal =  d[0] - (beam_xc / float(pixelsPerMm_Hor))
  d_vertical =  d[1] - (beam_yc / float(pixelsPerMm_Ver))

  phi_pos = math.radians(phi.direction*phi.getPosition())
  phiRotMatrix = numpy.matrix([[math.cos(phi_pos), -math.sin(phi_pos)],
                               [math.sin(phi_pos), math.cos(phi_pos)]])
  vertical_move = phiRotMatrix*numpy.matrix([[0],d_vertical])
  
  centred_pos = SAVED_INITIAL_POSITIONS.copy()
  centred_pos.update({ sampx.motor: float(sampx.getPosition() + sampx.direction*(dx + vertical_move[0,0])),
                       sampy.motor: float(sampy.getPosition() + sampy.direction*(dy + vertical_move[1,0])),
                       phiy.motor: float(phiy.getPosition() + phiy.direction*d_horizontal[0,0]) })
  return centred_pos

def end(centred_pos=None):
  if centred_pos is None:
      centred_pos = CURRENT_CENTRING.get()
  try:
    move_motors(centred_pos)
  except:
    import traceback
    logging.getLogger("HWR").info(traceback.format_exc())
    move_motors(SAVED_INITIAL_POSITIONS)
    raise

def start_auto(camera,  centring_motors_dict,
               pixelsPerMm_Hor, pixelsPerMm_Ver, 
               beam_xc, beam_yc,
               chi_angle = 0,
               n_points = 3,
               msg_cb=None,
               new_point_cb=None):    
    global CURRENT_CENTRING

    phi, phiy, sampx, sampy = prepare(centring_motors_dict)

    CURRENT_CENTRING = gevent.spawn(auto_center, 
                                    camera, 
                                    phi, phiy, 
                                    sampx, sampy, 
                                    pixelsPerMm_Hor, pixelsPerMm_Ver, 
                                    beam_xc, beam_yc, 
                                    chi_angle,
                                    n_points,
                                    msg_cb, new_point_cb)
    return CURRENT_CENTRING

def find_loop(camera, pixelsPerMm_Hor, msg_cb, new_point_cb,phipos):
  snapshot_filename = os.path.join(tempfile.gettempdir(), "mxcube_sample_snapshot.png")
  camera.takeSnapshot(snapshot_filename, bw=True)
   
  #  Comment out to save individual centring snapshots
  #
  #num = 0
  #while True:
  #   snapshot_savename =  os.path.join( tempfile.gettempdir(), "mxcube_center_phi%03f_%d.png" %(phipos,num))
  #   if not os.path.exists(snapshot_savename):
  #       break
  #   num+=1
  #   
  #logging.getLogger("HWR").info("Saving centring snapshot with name %s" % snapshot_savename)
  #logging.getLogger("HWR").info("  pixel per mm used are:  %s " % pixelsPerMm_Hor)
  #os.system("cp %s %s" % (snapshot_filename, snapshot_savename))

  try:
      info, x, y = lucid2.find_loop(snapshot_filename, pixels_per_mm_horizontal=pixelsPerMm_Hor)
  except:
      import traceback
      logging.info("lucid2 found an exception while executing:  %s" % traceback.format_exc())
      info, x, y = ("",-1,-1)
      
  
  if callable(msg_cb):
    msg_cb("Loop found: %s (%d, %d)" % (info, x, y))
  if callable(new_point_cb):
    new_point_cb((x,y))
        
  return x, y

def auto_center(camera, 
                phi, phiy, 
                sampx, sampy, 
                pixelsPerMm_Hor, pixelsPerMm_Ver, 
                beam_xc, beam_yc, 
                chi_angle, 
                n_points,
                msg_cb, new_point_cb):
    imgWidth = camera.getWidth()
    imgHeight = camera.getHeight()
 
    #check if loop is there at the beginning
    i = 0
    phipos=phi.getPosition()
    while -1 in find_loop(camera, pixelsPerMm_Hor, msg_cb, new_point_cb, phipos):
        phi.syncMoveRelative(90)
        i+=1
        if i>4:
            if callable(msg_cb):
                msg_cb("No loop detected, aborting")
            return
        phipos=phi.getPosition()
    
    logging.info("in autocentre loop found (at start time) ")

    for k in range(2):
      if callable(msg_cb):
            msg_cb("Doing automatic centring")
            
      centring_greenlet = gevent.spawn(px1_center,
                                       phi, phiy, 
                                       sampx, sampy, 
                                       pixelsPerMm_Hor, pixelsPerMm_Ver, 
                                       beam_xc, beam_yc, 
                                       chi_angle, 
                                       n_points)

      for a in range(n_points):
            phiPosition=phi.getPosition()
            x, y = find_loop(camera, pixelsPerMm_Hor, msg_cb, new_point_cb, phiPosition) 
            logging.info("in autocentre (point=%d/%d), x=%f, y=%f",a,n_points,x,y)
            if x < 0 or y < 0:
              for i in range(1,5):
                logging.debug("loop not found - moving back")
                phi.syncMoveRelative(-20)
                xold, yold = x, y
                phiPosition=phi.getPosition()
                x, y = find_loop(camera, pixelsPerMm_Hor, msg_cb, new_point_cb, phiPosition)
                if x >=0:
                  if y < imgHeight/2:
                    y = 0
                    if callable(new_point_cb):
                        new_point_cb((x,y))
                    user_click(x,y,wait=True)
                    break
                  else:
                    y = imgHeight
                    if callable(new_point_cb):
                        new_point_cb((x,y))
                    user_click(x,y,wait=True)
                    break
                if i == 4:
                  logging.debug("loop not found - trying with last coordinates")
                  if callable(new_point_cb):
                      new_point_cb((xold,yold))
                  user_click(xold, yold, wait=True)
              phi.syncMoveRelative(i*20)
            else:
               logging.getLogger("HWR").info("clicking automatically")
               user_click(x,y,wait=True)
               logging.getLogger("HWR").info("clicking automatically done")

      centred_pos = centring_greenlet.get()
      logging.getLogger("HWR").info("finished.  returning centred_pos %s "% str(centred_pos))
      end(centred_pos)
                 
      logging.getLogger("HWR").info("finished autocentring.  returning centred_pos %s "% str(centred_pos))
    return centred_pos
    
