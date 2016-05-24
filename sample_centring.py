from scipy import optimize
import numpy
import gevent.event
import gevent
import math
import time
import logging
import os
import tempfile

try:
  import lucid2 as lucid
except ImportError:
  try:
      import lucid
  except ImportError:
      logging.warning("Could not find autocentring library, automatic centring is disabled")

def multiPointCentre(z,phis) :
    fitfunc = lambda p,x: p[0] * numpy.sin(x+p[1]) + p[2]
    errfunc = lambda p,x,y: fitfunc(p,x) - y
    p1, success = optimize.leastsq(errfunc,[1.,0.,0.],args = (phis,z))
    return p1


USER_CLICKED_EVENT = None
CURRENT_CENTRING = None
SAVED_INITIAL_POSITIONS = {}
READY_FOR_NEXT_POINT = gevent.event.Event()

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
  

def stop_centring():
    USER_CLICKED_EVENT.set("abort")

def manual_centring(centring_motors_dict,
          pixelsPerMm_Hor, pixelsPerMm_Ver,
          beam_xc, beam_yc,
          chi_angle=0,
          n_points=3, phi_incr=90.0, sample_type="LOOP", diffract=None):

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
                                  n_points, phi_incr, sample_type, diffract)

  return CURRENT_CENTRING

def px1_center(phi, phiy,
               sampx, sampy,
               pixelsPerMm_Hor, pixelsPerMm_Ver,
               beam_xc, beam_yc,
               chi_angle,
               n_points,phi_incr,sample_type,diffract):
                   

    global USER_CLICKED_EVENT
    
    PHI_ANGLE_START = phi.getPosition()
    PhiCamera=90

    X, Y, PHI = [], [], []
    P, Q, XB, YB, ANG = [], [], [], [], []

    if sample_type.upper() == "PLATE":
        # go back half of the total range 
        logging.getLogger("user_level_log").info("centerig in plate mode / n_points %s / incr %s" % (n_points, phi_incr))
        half_range = (phi_incr * (n_points - 1))/2.0
        phi.syncMoveRelative(-half_range)
    else:
        logging.getLogger("user_level_log").info("centerig in loop mode / n_points %s / incr %s " % (n_points, phi_incr))

    try:  
        # OBTAIN CLICKS
        while True:
            if diffract:
                diffract.wait_user("point %s" % str(len(X)+1))
            user_info = USER_CLICKED_EVENT.get()
            if user_info == "abort":
                if diffract:
                    diffract.wait_user_end()
                abort_centring()
                return None
            else:   
                x,y = user_info
       
            if diffract:
                diffract.wait_user_end()
    
            USER_CLICKED_EVENT = gevent.event.AsyncResult()  
    
            X.append(x)
            Y.append(y)
            PHI.append(phi.getPosition())

            if len(X) == n_points:
                #PHI_LAST_ANGLE = phi.getPosition()
                #GO_ANGLE_START = PHI_ANGLE_START - PHI_LAST_ANGLE
                READY_FOR_NEXT_POINT.set()
                #phi.syncMoveRelative(GO_ANGLE_START)
                break
  
            phi.syncMoveRelative(phi_incr)
            READY_FOR_NEXT_POINT.set()
            
        # CALCULATE
        try:
            for i in range(n_points):
                xb  = X[i] - beam_xc
                yb = Y[i] - beam_yc
                ang = math.radians(PHI[i]+PhiCamera)

                XB.append(xb); YB.append(yb); ANG.append(ang)

            for i in range(n_points):
                y0 = YB[i] ; a0 = ANG[i] 
                if i < (n_points-1):
                    y1 = YB[i+1] ; a1 = ANG[i+1]
                else:
                    y1 = YB[0] ; a1 = ANG[0]

                p = (y0*math.sin(a1)-y1*math.sin(a0))/math.sin(a1-a0)        
                q = (y0*math.cos(a1)-y1*math.cos(a0))/math.sin(a0-a1)        
            
                P.append(p);  Q.append(q)

            x_echantillon = sum(P)/n_points
            y_echantillon = sum(Q)/n_points
            z_echantillon = -sum(XB)/n_points
        except:
            import traceback
            logging.getLogger("HWR").info("error while centering: %s" % traceback.format_exc())


        if diffract:
            diffract.wait_user_finished()

        x_echantillon_real=1000.*x_echantillon/pixelsPerMm_Hor + sampx.getPosition()
        y_echantillon_real=1000.*y_echantillon/pixelsPerMm_Hor + sampy.getPosition()
        z_echantillon_real=1000.*z_echantillon/pixelsPerMm_Hor + phiy.getPosition()

        if (z_echantillon_real + phiy.getPosition() < phiy.getLimits()[0]*2) :
            logging.getLogger("HWR").info("phiy limits: %s" % str(phiy.getLimits()))
            logging.getLogger("HWR").info(" requiring: %s" % str(z_echantillon_real + phiy.getPosition()))
            logging.getLogger("HWR").error("loop too long")
            
            move_motors(SAVED_INITIAL_POSITIONS)
            raise Exception()

        centred_pos = SAVED_INITIAL_POSITIONS.copy()
        
        centred_pos.update({ phi.motor: PHI_ANGLE_START,
                             sampx.motor: x_echantillon_real,
                             sampy.motor: y_echantillon_real,
                             phiy.motor: z_echantillon_real})
                             
        
        return centred_pos

    except: 
        if diffract:
            diffract.wait_user_end()
        logging.getLogger("HWR").error("Exception. Centring aborted")
        abort_centring()
        return None

def abort_centring():
    logging.getLogger("HWR").error("aborted")
    logging.getLogger("HWR").error("Restoring motor positions")
    move_motors(SAVED_INITIAL_POSITIONS)
    logging.getLogger("HWR").error("Motors moved back to original position")
    return None

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

  logging.getLogger("HWR").info("  -- preparing motors for centring")

  phi, phiy, sampx, sampy = prepare(centring_motors_dict)

  logging.getLogger("HWR").info("  -- preparing motors for centring done")

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
  logging.getLogger("HWR").info("  starting move motors")

  def wait_ready(timeout=None):
    with gevent.Timeout(timeout):
      while not ready(*motor_positions_dict.keys()):
        gevent.sleep(0.1)
      logging.getLogger("HWR").info("  -- wait ready done")

  wait_ready(timeout=3)

  logging.getLogger("HWR").info("  motors are ready now")

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
       logging.getLogger("HWR").info("  moving motor %s done" % (motor))

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
        logging.getLogger("HWR").info("  -- moving microglide done") 
  
  logging.getLogger("HWR").info("  -- waiting for all motors to stop")
  wait_ready()
  logging.getLogger("HWR").info("  -- waiting for all motors to stop done")
  
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
               phi_incr = 90,
               sample_type = "LOOP",
               msg_cb=None,
               new_point_cb=None,diffract=None):    
    global CURRENT_CENTRING

    phi, phiy, sampx, sampy = prepare(centring_motors_dict)

    CURRENT_CENTRING = gevent.spawn(auto_center, 
                                    camera, 
                                    phi, phiy, 
                                    sampx, sampy, 
                                    pixelsPerMm_Hor, pixelsPerMm_Ver, 
                                    beam_xc, beam_yc, 
                                    chi_angle,
                                    n_points, phi_incr, sample_type,
                                    msg_cb, new_point_cb,diffract)
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
      info, x, y = lucid.find_loop(snapshot_filename)
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
                n_points, phi_incr, sample_type, 
                msg_cb, new_point_cb,diffract=None):

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

    for k in range(1):
      if callable(msg_cb):
            msg_cb("Doing automatic centring")
            
      centring_greenlet = gevent.spawn(px1_center,
                                       phi, phiy, 
                                       sampx, sampy, 
                                       pixelsPerMm_Hor, pixelsPerMm_Ver, 
                                       beam_xc, beam_yc, 
                                       chi_angle, 
                                       n_points, phi_incr, sample_type,diffract)

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
    
