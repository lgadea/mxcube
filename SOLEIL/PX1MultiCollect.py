from HardwareRepository import HardwareRepository
from HardwareRepository.BaseHardwareObjects import HardwareObject
from AbstractMultiCollect import *
from gevent.event import AsyncResult
import logging
import time
import os
import copy
import math
import httplib
import subprocess
import socket

from PyTango import DeviceProxy
from collections import namedtuple

# PL.
def make_dir(dirname):    
    try:
        os.mkdir(dirname)
        os.chmod(dirname, 0777)
    except OSError:
        pass
    except Exception, err:
        print "Error in creating process directory %s:" % dirname, err

def make_process_dir(dirname):
    _pdir = os.path.join(dirname, "process")
    make_dir(_pdir)

def write_goimg(path):
    dirname = "/data/log/.goimg"
    db = "goimg.db"
    db_f = os.path.join(dirname,db)
    if db in os.listdir(dirname):
        os.remove(db_f)
    dbo = open(db_f, "w")
    dbo.write(path)
    dbo.close()
    os.chmod(db_f, 0777)
#/ PL.

class TunableEnergy:
    # self.bl_control is passed by PX1MultiCollect
    @task
    def set_wavelength(self, wavelength):
        energy_obj = self.bl_control.energy
        return energy_obj.startMoveWavelength(wavelength)

    @task
    def set_energy(self, energy):
        energy_obj = self.bl_control.energy
        return energy_obj.startMoveEnergy(energy)

    def getCurrentEnergy(self):
        return self.bl_control.energy.getCurrentEnergy()

    def get_wavelength(self):
        logging.info( "PX1Multicollect: bl_control.energy dir= %s" % dir(self.bl_control.energy))
        wavlen = self.bl_control.energy.getCurrentWavelength()
	if wavlen:
            logging.info( "PX1Multicollect: wavlen YES %.5f %s" % (wavlen, type(wavlen)))
	else:
            logging.info( "PX1Multicollect: wavlen NO  %s %s" % (wavlen, type(wavlen)))           
        return wavlen

class PixelDetector:
    def __init__(self):
        self.shutterless = True
        self.new_acquisition = True
        self.first_frame = True
        self.jpeg_allframes = False
        self.shutterless_exptime = None
        self.shutterless_range = None

    @task
    def prepare_acquisition(self, take_dark, start, osc_range, exptime, npass, number_of_images, comment=""):
        self.new_acquisition = True
        self.cimg = self.collectServer.currentImageSpi
        if  osc_range < 0.0001:
            self.shutterless = False
        take_dark = 0
        if self.shutterless:
            self.shutterless_range = osc_range*number_of_images
            self.shutterless_exptime = (exptime + 0.003)*number_of_images
        logging.info("<PX1 MultiCollect> TODO - prepare acquisition")


        self.prepare_detector_header(take_dark, start, osc_range, exptime, npass, number_of_images, comment)

        #self.execute_command("prepare_acquisition", take_dark, start, osc_range, exptime, npass, comment)
        #self.getCommandObject("build_collect_seq").executeCommand("write_dp_inputs(COLLECT_SEQ,MXBCM_PARS)",wait=True)
        
    def prepare_detector_header(self,take_dark, start, osc_range, exptime, npass, number_of_images, comment):

        # Setting MXSETTINGS for the cbf image headers
        ax, bx = self.bl_config.beam_ax, self.bl_config.beam_bx
        ay, by = self.bl_config.beam_ay, self.bl_config.beam_by

        dist   = self.bl_control.detector_distance.getPosition()
        wavlen = self.bl_control.energy.getCurrentWavelength()
        logging.info( "PX1Multicollect: bl_control.energy dir= %s" % dir(self.bl_control.energy))
	if wavlen:
            logging.info( "PX1Multicollect: wavlen %.5f %s" % (wavlen, type(wavlen)))
	else:
            logging.info( "PX1Multicollect: wavlen %s %s" % (wavlen, type(wavlen)))           
        kappa_angle = self.kappa_hwo.getPosition()

        _settings = [
                  ["Wavelength %.5f", wavlen],
                  ["Detector_distance %.4f", dist/1000.],
                  ["Beam_x %.2f", ax*dist + bx],
                  ["Beam_y %.2f", ay*dist + by],
                  ["Alpha %.2f", 49.64],
                  ["Start_angle %.4f", start],
                  ["Angle_increment %.4f", osc_range],
                  ["Oscillation_axis %s", self.oscaxis],
                  ["Detector_2theta %.4f", 0.0],
                  ["Polarization %.3f", 0.990],
                  ["Kappa %.4f", kappa_angle]]
                  
        if self.oscaxis == "Phi":
            _settings.append(["Chi %.4f", self.omega_hwo.getPosition()])
            _settings.append(["Phi %.4f", start])
        elif self.oscaxis == "Omega":
            _settings.append(["Phi %.4f", self.phi_hwo.getPosition()])
            _settings.append(["Chi %.4f", start])

        for _setting in _settings:
            try:
                _str_set = (_setting[0] % _setting[1])
            except:
                _str_set = _setting[0]

            logging.getLogger().info( "MxSettings: " + _str_set )
            self.pilatusServer.SetMxSettings(_str_set)

    @task
    def set_detector_filenames(self, frame_number, start, filename, jpeg_full_path, jpeg_thumbnail_full_path):

      self.current_jpeg_path = jpeg_full_path
      self.current_thumb_path = jpeg_thumbnail_full_path
      self.current_filename = filename

      if self.shutterless and not self.new_acquisition:
          return

      basefile = os.path.basename(filename)
      dirname  = os.path.dirname(filename)
      dirname  = dirname.replace("/data1-1","/ramdisk")

      logging.info("<PX1 MultiCollect> Setting detector filenames")
      logging.info("     - frame_number: %s", frame_number)
      logging.info("     - start: %s", start)
      logging.info("     - filename: %s", basefile)
      logging.info("     - dirname: %s", dirname)
      logging.info("     - jpeg path: %s", jpeg_full_path)
      logging.info("     - thumb path: %s", jpeg_thumbnail_full_path)

      self.collectServer.imageName = basefile
      self.collectServer.imagePath = dirname
      self.collectServer.jpegpath = jpeg_full_path
      self.collectServer.jpegthumb = jpeg_thumbnail_full_path
      self.collectServer.PrepareCollect()

      #self.collectServer.imageName = "%s_%d_%04d.%s" % ( \
                        #_fileinfo['prefix'], _fileinfo['run_number'],
                        #_osc_seq['start_image_number'], _fileinfo['suffix'])

      #self.collectServer.imagePath = "/ramdisk/" + \
      #                           "/".join(_fileinfo['directory'].split("/")[2:])

      logging.info("<PX1 MultiCollect> TODO - set detector filenames")
      return
      #self.getCommandObject("prepare_acquisition").executeCommand('setMxCollectPars("current_phi", %f)' % start)
      #self.getCommandObject("prepare_acquisition").executeCommand('setMxCurrentFilename("%s")' % filename)
      #self.getCommandObject("prepare_acquisition").executeCommand("ccdfile(COLLECT_SEQ, %d)" % frame_number, wait=True)

    @task
    def prepare_oscillation(self, start, osc_range, exptime, npass):
        if self.shutterless:
            if self.new_acquisition:
                logging.info("<PX1 MultiCollect> TODO - prepare oscillation new")
                #self.execute_command("prepare_oscillation", start, start+self.shutterless_range, self.shutterless_exptime, npass)
        else:
            if osc_range < 1E-4:
                # still image
                pass
            else:
                logging.info("<PX1 MultiCollect> TODO - prepare oscillation not new")
                #self.execute_command("prepare_oscillation", start, start+osc_range, exptime, npass)
        return (start, start+osc_range)

    @task
    def start_acquisition(self, exptime, npass, first_frame):
      if not first_frame and self.shutterless:
        pass 
      else:
        logging.info("<PX1 MultiCollect> TODO - start acquisition ")
        #self.execute_command("start_acquisition")

    @task
    def do_oscillation(self, start, end, exptime, npass):
      if self.shutterless:
          if self.new_acquisition:
              # only do this once per collect
              npass = 1
              exptime = self.shutterless_exptime
              end = start + self.shutterless_range
          
              # make oscillation an asynchronous task => do not wait here
              logging.info("<PX1 MultiCollect> TODO - do oscillation new")
              self.first_frame = True
              self.collectServer.Start()
              self.new_acquisition = False
              logging.getLogger("user_level_log").info("<PX1 MultiCollect> Collect server started waiting for first image")

              # wait for image number to change. normally to 0, first
              self.wait_nextimage()
  
          # wait for image number to change
          logging.info("<PX1 MultiCollect> TODO - do oscillation not new")
          self.wait_nextimage()

      else:
          logging.info("<PX1 MultiCollect> TODO - not shutterless mode. Nothing done here")
    
    def wait_nextimage(self):
        cimg = self.cimg
        while ( cimg == self.cimg ):
           if str( self.collectServer.State()) != "RUNNING":
               break
           time.sleep(0.02)
           cimg = self.collectServer.currentImageSpi
        self.cimg = cimg
        if self.cimg != 0:
            logging.getLogger("user_level_log").info("<PX1 MultiCollect> end waiting for image number %s" % str(self.cimg))

    @task
    def write_image(self, last_frame):
        if self.jpeg_allframes or self.first_frame or last_frame:
            logging.info("<PX1 MultiCollect> TODO - write image ")
            logging.info("Generating jpeg and thumbnail for:")
            logging.info("   - Fullpath :  " + self.current_filename)
            logging.info("   - jpegpath :  " + self.current_jpeg_path )
            logging.info("   - thumpath :  " + self.current_thumb_path )
      
            subprocess.Popen([ self.imgtojpeg, self.current_filename, self.current_jpeg_path, '0.4' ])
            subprocess.Popen([ self.imgtojpeg, self.current_filename, self.current_thumb_path, '0.1' ])

            self.first_frame = False

        self.adxv_sync(self.current_filename)

    def adxv_sync(self, imgname):
        # connect to adxv to show the image
        adxv_send_fmt = "\nload_image %s  " + "\n"+ chr(32)
        logging.info(" ADXV_send_fmt")
        logging.info(adxv_send_fmt % imgname)
        
        try:
            if not self.adxv_socket:
                try:
                    self.connectVisualisation()
                except:
                    self.adxv_socket = None
                    logging.info("ADXV: Warning: Can't connect to adxv socket to follow collect.")
            else:
                print "dxv_send_fmt % self.current_filename"
                self.adxv_socket.send(adxv_send_fmt % self.current_filename)
        except:
            try:
               del self.adxv_socket
               self.connectVisualisation()
            except:
               self.adxv_socket = None
      
    def stop_acquisition(self):
        logging.info("<PX1 MultiCollect>  stopping acquisition ")
        self.new_acquisition = False
      
    @task
    def reset_detector(self):
      if self.shutterless:
          self.stopCollect("mxCuBE")
      logging.info("<PX1 MultiCollect> TODO - reset detector ")
      #self.getCommandObject("reset_detector").abort()    
      #self.execute_command("reset_detector")

    #TODO: rename to stop_collect

    def stopCollect(self, owner):
        logging.info("<PX1 MultiCollect>  stopping ")
        if str( self.collectServer.State()) == "RUNNING":
           logging.info("<PX1 MultiCollect>  stopping collect server ")
           self.collectServer.Stop()


class PilatusDetector(PixelDetector):
    pass

PX1BeamlineConfig = namedtuple('PX1BeamlineConfig', BeamlineConfig._fields+('detector_radius', 'synchrotron_name',))

class PX1MultiCollect(AbstractMultiCollect, HardwareObject):
    def __init__(self, name):

        AbstractMultiCollect.__init__(self)
        HardwareObject.__init__(self, name)

        self._detector = PilatusDetector()
        self._tunable_bl = TunableEnergy()

        self._centring_status = None

    def execute_command(self, command_name, *args, **kwargs): 
      wait = kwargs.get("wait", True)
      cmd_obj = self.getCommandObject(command_name)
      return cmd_obj(*args, wait=wait)
          
    def setBeamlineConfiguration(self, **configuration_parameters):
        self.bl_config = PX1BeamlineConfig(**configuration_parameters)

    def set_rotation_axis(self, axis):
        logging.debug("PX1 multicollect. rotation axis set to : %s" % axis)
        self.collectServer.collectAxis = axis

    def init(self):

        self.collectServer = DeviceProxy( self.getProperty("collectname"))
        self.pilatusServer = DeviceProxy( self.getProperty("pilatusname"))
        self.fluoMotor =     DeviceProxy( self.getProperty("fluomotor"))
        self.close_safty_shutter = self.getProperty("close_safty_shutter") 
        
        self.collectServer.collectAxis = "Phi"

        self.imgtojpeg = self.getProperty("imgtojpeg")
        self._detector.imgtojpeg = self.imgtojpeg
        self.jpegoption = self.getProperty("jpegoption")
        if self.jpegoption == 'allframes':
            self._detector.jpeg_allframes = True
        self.ruche_sync_dir = self.getProperty("ruche_sync_dir")
    
        self.setControlObjects(diffractometer = self.getObjectByRole("diffractometer"),
                               sample_changer = self.getObjectByRole("sample_changer"),
                               lims = self.getObjectByRole("dbserver"),
                               fast_shutter = self.getObjectByRole("fast_shutter"),
                               safety_shutter = self.getObjectByRole("safety_shutter"),
                               machine_current = self.getObjectByRole("machine_current"),
                               cryo_stream = self.getObjectByRole("cryo_stream"),
                               energy = self.getObjectByRole("energy"),
                               resolution = self.getObjectByRole("resolution"),
                               detector_distance = self.getObjectByRole("detector_distance"),
                               transmission = self.getObjectByRole("transmission"),
                               undulators = self.getObjectByRole("undulators"),
                               flux = self.getObjectByRole("flux"))

        kappa_hwo = self.getObjectByRole("kappa")
        phi_hwo = self.getObjectByRole("phi")
        omega_hwo = self.getObjectByRole("omega")
        mxlocalHO = self.getObjectByRole("beamline_configuration")

        bcm_pars = mxlocalHO["BCM_PARS"]
        spec_pars = mxlocalHO["SPEC_PARS"]
        bl_pars = mxlocalHO["BEAMLINE_PARS"]

        self.session_hwo = self.getObjectByRole("session")

        try:
          undulators = bcm_pars["undulator"]
        except IndexError:
          undulators = []
    
        # PL 2015_01_23 For ADXV visualisation.
        self.connectVisualisation()
        
        self.setBeamlineConfiguration(directory_prefix = self.getProperty("directory_prefix"),
                                      default_exposure_time = bcm_pars.getProperty("default_exposure_time"),
                                      default_number_of_passes = bcm_pars.getProperty("default_number_of_passes"),
                                      maximum_radiation_exposure = bcm_pars.getProperty("maximum_radiation_exposure"),
                                      nominal_beam_intensity = bcm_pars.getProperty("nominal_beam_intensity"),
                                      minimum_exposure_time = bcm_pars.getProperty("minimum_exposure_time"),
                                      minimum_phi_speed = bcm_pars.getProperty("minimum_phi_speed"),
                                      minimum_phi_oscillation = bcm_pars.getProperty("minimum_phi_oscillation"),
                                      maximum_phi_speed = bcm_pars.getProperty("maximum_phi_speed"),
                                      detector_fileext = bcm_pars.getProperty("FileSuffix"),
                                      detector_type = bcm_pars["detector"].getProperty("type"),
                                      detector_mode = spec_pars["detector"].getProperty("binning"),
                                      detector_manufacturer = bcm_pars.getProperty("detector_manufacturer"),
                                      detector_model = bcm_pars.getProperty("detector_model"),
                                      detector_px = bcm_pars.getProperty("detector_px"),
                                      detector_py = bcm_pars.getProperty("detector_py"),
                                      detector_radius = bcm_pars.getProperty('detector_radius'),
                                      beam_ax = spec_pars["beam"].getProperty("ax"),
                                      beam_ay = spec_pars["beam"].getProperty("ay"),
                                      beam_bx = spec_pars["beam"].getProperty("bx"),
                                      beam_by = spec_pars["beam"].getProperty("by"),
                                      undulators = undulators,
                                      focusing_optic = bcm_pars.getProperty('focusing_optic'),
                                      monochromator_type = bcm_pars.getProperty('monochromator'),
                                      beam_divergence_vertical = bcm_pars.getProperty('beam_divergence_vertical'),
                                      beam_divergence_horizontal = bcm_pars.getProperty('beam_divergence_horizontal'),     
                                      polarisation = bcm_pars.getProperty('polarisation'),
                                      auto_processing_server = None,
                                      synchrotron_name = bl_pars.getProperty('synchrotron_name'),
                                      input_files_server = None)
  
        self.oscaxis = self.getProperty("oscaxis")

        self._detector.collectServer = self.collectServer
        self._detector.pilatusServer = self.pilatusServer
        self._detector.bl_control   = self.bl_control
        self._detector.bl_config    = self.bl_config
        self._detector.kappa_hwo    = kappa_hwo
        self._detector.phi_hwo      = phi_hwo
        self._detector.omega_hwo    = omega_hwo
        self._detector.oscaxis      = self.oscaxis


        #self._detector.getCommandObject = self.getCommandObject
        #self._detector.getChannelObject = self.getChannelObject
        #self._detector.execute_command = self.execute_command

        self._tunable_bl.bl_control = self.bl_control

        self.emit("collectConnected", (True,))
        self.emit("collectReady", (True, ))

    @task
    def take_crystal_snapshots(self, image_count=2):
        self.bl_control.diffractometer.takeSnapshots(image_count, wait=True)

    @task
    def data_collection_hook(self, data_collect_parameters):
        self.dcpars = copy.copy(data_collect_parameters)
        return
 
    @task
    def set_transmission(self, transmission_percent):
        self.bl_control.transmission.setTransmission(transmission_percent)

    def set_wavelength(self, wavelength):
        return self._tunable_bl.set_wavelength(wavelength)

    def set_energy(self, energy):
        return self._tunable_bl.set_energy(energy)

    @task
    def set_resolution(self, new_resolution):
        logging.info("<PX1 MultiCollect> TEST - set_resolution")
        return self.bl_control.resolution.move(new_resolution)
        
    @task
    def move_detector(self, detector_distance):
        logging.info("<PX1 MultiCollect> TEST - move detector")
        self.bl_control.detector_distance = detector_distance
        return

    @task
    def data_collection_cleanup(self):
        self.close_fast_shutter()
        self.trigger_data_sync()

    @task
    def close_fast_shutter(self):
        logging.info("<PX1 MultiCollect> close fast shutter ")
        self.bl_control.fast_shutter.closeShutter()
        t0 = time.time()
        while self.bl_control.fast_shutter.getShutterState() != 'closed':
            time.sleep(0.1)
            if (time.time() - t0) > 4:
                logging.getLogger("HWR").error("Timeout on closing fast shutter")
                break

    def set_helical(self, onmode, positions=None):
        logging.info("<PX1 MultiCollect> set helical")
        self.helical = onmode
        if onmode:
            logging.info("<PX1 MultiCollect> set helical pos1 %s pos2 %s" % (positions['1'], positions['2']))
            self.helicalStart = positions['1']
            self.helicalFinal = positions['2']

    def set_collect_position(self, position):
        logging.info("<PX2 MultiCollect> set collect position %s" % position)
        logging.info("<PX2 MultiCollect> set collect position type %s" % type(position))
        self.standard_collect = True
        #pos = dict(position)
        #collect_position = {} 
        #for motor in self.motors:
            #collect_position[motor] = pos[motor]

        self.collect_position = self.bl_control.diffractometer.getPositions()

    @task
    def open_fast_shutter(self):
        logging.info("<PX1 MultiCollect> open fast shutter ")
        self.bl_control.fast_shutter.openShutter()
        t0 = time.time()
        while self.bl_control.fast_shutter.getShutterState() == 'closed':
            time.sleep(0.1)
            if (time.time() - t0) > 4:
                logging.getLogger("HWR").error("Timeout on opening fast shutter")
                break

    @task
    def move_motors(self, motor_position_dict):
        for motor in motor_position_dict.keys(): #iteritems():
            position = motor_position_dict[motor]
            logging.getLogger().info("PX1 MultiCollect / move_motors: %s to %s " % (motor, position))
            if isinstance(motor, str) or isinstance(motor, unicode):
                # find right motor object from motor role in diffractometer obj.
                motor_role = motor
                motor = self.bl_control.diffractometer.getDeviceByRole(motor_role)
                del motor_position_dict[motor_role]
                if motor is None:
                  continue
                motor_position_dict[motor]=position

            logging.getLogger("HWR").info("Moving motor '%s' to %f", motor.getMotorMnemonic(), position)
            motor.move(position)

        while any([motor.motorIsMoving() for motor in motor_position_dict.iterkeys()]):
            logging.getLogger("HWR").info("Waiting for end of motors motion")
            time.sleep(0.5)  

    @task
    def open_safety_shutter(self):
        self.bl_control.safety_shutter.openShutter()
        t0 = time.time()
        while self.bl_control.safety_shutter.getShutterState() != 'opened':
            time.sleep(0.1)
            if (time.time() - t0) > 4:
                logging.getLogger("HWR").error("Timeout on opening safety shutter")
                break

    def safety_shutter_opened(self):
        return self.bl_control.safety_shutter.getShutterState() == "opened"

    @task
    def close_safety_shutter(self):
        logging.info("<PX1 MultiCollect> close_safety_shutter config: %s %s" % (self.close_safty_shutter, type(self.close_safty_shutter)))
        if self.close_safty_shutter: 
            logging.info("<PX1 MultiCollect> closing safetyshutter")
	    self.bl_control.safety_shutter.closeShutter()
            t0 = time.time()
            while self.bl_control.safety_shutter.getShutterState() == 'opened':
                time.sleep(0.1)
                if (time.time() - t0) > 4:
                    logging.getLogger("HWR").error("Timeout on closing safety shutter")
                    break

    @task
    def prepare_intensity_monitors(self):
        logging.info("<PX1 MultiCollect> TODO - prepare intensity monitors")

    def prepare_acquisition(self, take_dark, start, osc_range, exptime, npass, number_of_images, comment=""):

        try:
            if str(self.fluoMotor.State()) == "INSERT":
                self.fluoMotor.Extract()
        except:
            logging.error("<PX1 MultiCollect> Can't extract fluorescence arm")

        self.collectServer.exposurePeriod = exptime
        self.collectServer.numberOfImages = number_of_images
        self.collectServer.imageWidth = osc_range
        self.collectServer.collectAxis = self.oscaxis
        self.collectServer.startAngle = start
        self.collectServer.triggerMode = 2

        self.bl_control.diffractometer.prepareForAcquisition()

        return self._detector.prepare_acquisition(take_dark, start, osc_range, exptime, npass, number_of_images, comment)

    def set_detector_filenames(self, frame_number, start, filename, jpeg_full_path, jpeg_thumbnail_full_path):
        self.current_jpeg_full_path = jpeg_full_path
        return self._detector.set_detector_filenames(frame_number, start, filename, jpeg_full_path, jpeg_thumbnail_full_path)

    def prepare_oscillation(self, start, osc_range, exptime, npass):
        return self._detector.prepare_oscillation(start, osc_range, exptime, npass)

    def do_oscillation(self, start, end, exptime, npass):
        return self._detector.do_oscillation(start, end, exptime, npass)
    
    def start_acquisition(self, exptime, npass, first_frame):
        return self._detector.start_acquisition(exptime, npass, first_frame)
      
    def write_image(self, last_frame):
        return self._detector.write_image(last_frame)

    def stop_acquisition(self):
        return self._detector.stop_acquisition()
        
    @task
    def finalize_acquisition(self):
        logging.info("<PX1 MultiCollect> TODO - finalize acquisition")
        return

    def reset_detector(self):
        AbstractMultiCollect.stopCollect(self,owner=None)
        return self._detector.reset_detector()

    def prepare_input_files(self, files_directory, prefix, run_number, process_directory):
        return ("/tmp", "/tmp", "/tmp")

    @task
    def write_input_files(self, collection_id):
        pass

    def get_wavelength(self):
        return self._tunable_bl.get_wavelength()
      
    def get_detector_distance(self):
        logging.info("<PX1 MultiCollect> TODO - get detector distance")
        return self.bl_control.detector_distance.getPosition()
       
    def get_resolution(self):
        return self.bl_control.resolution.getPosition()

    def get_transmission(self):
        return self.bl_control.transmission.getAttFactor()

    def get_undulators_gaps(self):
        logging.info("<PX1 MultiCollect> TODO - get undulators gaps" )
        return ['9999','9999']

        all_gaps = {'Unknown': None}
        try:
            _gaps = self.bl_control.undulators.getUndulatorGaps()
        except:
            logging.getLogger("HWR").exception("Could not get undulator gaps")
        all_gaps.clear()

        for key in _gaps:
            if  '_Position' in key:
                nkey = key[:-9]
                all_gaps[nkey] = _gaps[key]
            else:
                all_gaps = _gaps
        return all_gaps

    def get_resolution_at_corner(self):

        logging.info("<PX1 MultiCollect> get resolution at corner" )

        radius = self.bl_config.detector_radius  / 1000.0 # meters
        detdist =  self.get_detector_distance() / 1000.0 # meters
        wavelength = self.get_wavelength() # angtroms
        logging.info("<PX1 MultiCollect> get resolution at corner: w: %s detdist: %s radius: %s"% (wavelength, detdist, radius))
        angle = math.atan( math.sqrt(2)*radius/detdist) 
        resatcorner = wavelength / (2*math.sin(0.5*angle))
        return resatcorner

    def get_beam_size(self):
        logging.info("<PX1 MultiCollect> TODO - get beam size" )
        return (-1,-1)

    def get_slit_gaps(self):
        logging.info("<PX1 MultiCollect> TODO - get slit gaps" )
        return (-1,-1)

    def get_beam_shape(self):
        logging.info("<PX1 MultiCollect> TODO - get beam shape" )
        return "rectangular"
    
    def get_measured_intensity(self):
        logging.info("<PX1 MultiCollect> TODO - get measured intensity" )
        try:
           val = self.getChannelObject("image_intensity").getValue()
           return float(val)
        except:
           return -1

    def get_machine_current(self):
        if self.bl_control.machine_current is not None:
            return self.bl_control.machine_current.getCurrent()
        else:
            return -1

    def get_machine_message(self):
        logging.info("<PX1 MultiCollect> getting machine message" )
        if  self.bl_control.machine_current is not None:
            return self.bl_control.machine_current.getMessage()
        else:
            return 'Not implemented yet'

    def get_machine_fill_mode(self):
        logging.info("<PX1 MultiCollect> getting machine fill mode" )
        logging.info( self.bl_control.machine_current.getFillMode() )

        if self.bl_control.machine_current is not None:
            return self.bl_control.machine_current.getFillMode()
        else:
            'Not implemented yet'

    def get_cryo_temperature(self):
        logging.info("<PX1 MultiCollect> TODO - get cryo temperature" )
        return -1 
        #return self.bl_control.cryo_stream.getTemperature()

    def getCurrentEnergy(self):
        return self._tunable_bl.getCurrentEnergy()

    def get_beam_centre(self):
        logging.info("<PX1 MultiCollect> TODO - get beam centre" )
        return (999,999)

        #return (self.execute_command("get_beam_centre_x"), self.execute_command("get_beam_centre_y"))
    
    def getBeamlineConfiguration(self, *args):
      # TODO: change this to stop using a dictionary at the other end
      return self.bl_config._asdict()

    def isConnected(self):
        return True

    def isReady(self):
        return True
 
    def sampleChangerHO(self):
        return self.bl_control.sample_changer

    def diffractometer(self):
        return self.bl_control.diffractometer

    def dbServerHO(self):
        return self.bl_control.lims

    def sanityCheck(self, collect_params):
        return
    
    def setBrick(self, brick):
        return

    def directoryPrefix(self):
        return self.bl_config.directory_prefix

    def store_image_in_lims(self, frame, first_frame, last_frame):
        #if isinstance(self._detector, CcdDetector):
            #return True

        if isinstance(self._detector, PixelDetector):
            if first_frame or last_frame:
                return True

    def get_flux(self):
        logging.info("<PX1 MultiCollect> TODO - get flux")
        return self.bl_control.flux.getCurrentFlux()

    """
    getOscillation
        Description: Returns the parameters (and results) of an oscillation.
        Type       : method
        Arguments  : oscillation_id (int; the oscillation id, the last parameters of the collectOscillationStarted
                                     signal)
        Returns    : tuple; (blsampleid,barcode,location,parameters)
    """
    def getOscillation(self, oscillation_id):
      return self.oscillations_history[oscillation_id - 1]
       
    def sampleAcceptCentring(self, accepted, centring_status):
      self.sample_centring_done(accepted, centring_status)

    def setCentringStatus(self, centring_status):
      self._centring_status = centring_status

    """
    getOscillations
        Description: Returns the history of oscillations for a session
        Type       : method
        Arguments  : session_id (int; the session id, stored in the "sessionId" key in each element
                                 of the parameters list in the collect method)
        Returns    : list; list of all oscillation_id for the specified session
    """
    def getOscillations(self,session_id):
      #TODO
      return []

    def setHelical(self,onoff):
        logging.getLogger().info("<PX1 MultiCollect> TODO - setHelical (%s)" % str(onoff))
        return 


    def get_archive_directory(self, directory):
       
        archive_dir = self.session_hwo.get_archive_directory(directory)
        logging.getLogger().info("<PX1 MultiCollect> - get archive directory (using %s)" % archive_dir)

        return archive_dir 

    def trigger_data_sync(self):
        logging.getLogger().info("<PX1 MultiCollect> - triggering data sync ")
        ruche_info = self.session_hwo.get_ruche_info( self.current_jpeg_full_path ) 

        sync_file = time.strftime("%Y_%m_%d-%H_%M_%S", time.localtime(time.time()))
        sync_file_path = os.path.join( self.ruche_sync_dir, sync_file )
        open(sync_file_path,"w").write( ruche_info )

    def connectVisualisation(self):
        # For ADXV visu (PL 2015_01_23).
        #os.system("killall adxv_follow")
        #_cl = "gnome-terminal --title ADXV_TERM "
        #_cl += " --geometry=132x30+1680+5 -e adxv_follow &"
        #os.system(_cl)
        #time.sleep(1.)
        adxv_host = '127.0.0.1'
        adxv_port = 8100

        try:
            res = socket.getaddrinfo(adxv_host, adxv_port, 0, socket.SOCK_STREAM)
            af, socktype, proto, canonname, sa = res[0]
            self.adxv_socket = socket.socket(af, socktype, proto)
            self.adxv_socket.connect((adxv_host, adxv_port))
            logging.getLogger().info("ADXV OK.") 
        except:
            self.adxv_socket = None
            logging.getLogger().info("WARNING: Can't connect to ADXV.")

def test():
    import os
    hwr_directory = os.environ["XML_FILES_PATH"]

    hwr = HardwareRepository.HardwareRepository(os.path.abspath(hwr_directory))
    hwr.connect()

    coll = hwr.getHardwareObject("/mxcollect")

    #print "Machine current is ", coll.get_machine_current()
    print "Synchrotron name is ", coll.bl_config.synchrotron_name
    #res_corner = coll.get_resolution_at_corner()
    #print "Resolution corner is ", res_corner
    #print coll._detector.jpeg_allframes 
 
    #coll.current_jpeg_full_path = "/data1-1/test/visitor/mx2014/px1/20150122/ARCHIVE/genthumb5_1_0001.jpg"
    #coll.trigger_data_sync()

    time.sleep(2)
    coll._detector.adxv_sync("/data1-1/test/visitor/mx2014/px1/20150123/RAW_DATA/ruchetest_3_0003.cbf")
    time.sleep(2)
    coll._detector.adxv_sync("/data1-1/test/visitor/mx2014/px1/20150123/RAW_DATA/ruchetest_3_0002.cbf")

if __name__ == '__main__':
   test()

