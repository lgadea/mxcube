from HardwareRepository.BaseHardwareObjects import Equipment
from HardwareRepository.TaskUtils import *
import logging

import PyChooch
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import os
import time
import types
import math
import gevent

class SOLEILEnergyScan(Equipment):

    def init(self):
        self.ready_event = gevent.event.Event()
        self.scanning = None
        self.moving = None
        self.energyMotor = None
        self.energyScanArgs = None
        self.archive_prefix = None
        self.energy2WavelengthConstant=None
        self.defaultWavelength=None
        self._element = None
        self._edge = None

        try:
            self.defaultWavelengthChannel=self.getChannelObject('default_wavelength')
        except KeyError:
            self.defaultWavelengthChannel=None
        else:
            self.defaultWavelengthChannel.connectSignal("connected", self.sConnected) 
            self.defaultWavelengthChannel.connectSignal("disconnected", self.sDisconnected)

        if self.defaultWavelengthChannel is None:
            #MAD beamline
            try:
                self.energyScanArgs=self.getChannelObject('escan_args')
            except KeyError:
                logging.getLogger("HWR").warning('EnergyScan: error initializing energy scan arguments (missing channel)')
                self.energyScanArgs=None

            try:
                self.scanStatusMessage=self.getChannelObject('scanStatusMsg')
            except KeyError:
                self.scanStatusMessage=None
                logging.getLogger("HWR").warning('EnergyScan: energy messages will not appear (missing channel)')
            else:
                self.connect(self.scanStatusMessage,'update',self.scanStatusChanged)

            self.session_ho=self.getObjectByRole("session")
            if self.session_ho is None:
                logging.getLogger("HWR").warning('EnergyScan: you should specify the session hardware object')

            self.ruche_ho=self.getObjectByRole("ruche")
            if self.ruche_ho is None:
                logging.getLogger("HWR").warning('EnergyScan: you should specify the ruche hardware object')


            self.xanes_ho=self.getObjectByRole("xanes")
            if self.xanes_ho is None:
                logging.getLogger("HWR").warning('EnergyScan: you should specify the xanes hardware object')

            self.energyMotor=self.getObjectByRole("energy")
            if self.energyMotor is None:
                logging.getLogger("HWR").warning('EnergyScan: you should specify the energy hardware object')
            self.resolutionMotor=self.getObjectByRole("resolution")
            self.previousResolution=None
            self.lastResolution=None

            self.dbConnection=self.getObjectByRole("dbserver")
            if self.dbConnection is None:
                logging.getLogger("HWR").warning('EnergyScan: you should specify the database hardware object')
            self.scanInfo=None

            self.transmissionHO=self.getObjectByRole("transmission")
            if self.transmissionHO is None:
                logging.getLogger("HWR").warning('EnergyScan: you should specify the transmission hardware object')

            self.cryostreamHO=self.getObjectByRole("cryostream")
            if self.cryostreamHO is None:
                logging.getLogger("HWR").warning('EnergyScan: you should specify the cryo stream hardware object')

            self.machcurrentHO=self.getObjectByRole("machcurrent")
            if self.machcurrentHO is None:
                logging.getLogger("HWR").warning('EnergyScan: you should specify the machine current hardware object')

            self.fluodetectorHO=self.getObjectByRole("fluodetector")
            if self.fluodetectorHO is None:
                logging.getLogger("HWR").warning('EnergyScan: you should specify the fluorescence detector hardware object')

            try:
                self.moveEnergy.connectSignal('commandReady', self.moveEnergyCmdReady)
                self.moveEnergy.connectSignal('commandNotReady', self.moveEnergyCmdNotReady)
            except AttributeError,diag:
                logging.getLogger("HWR").warning('EnergyScan: error initializing move energy (%s)' % str(diag))
                self.moveEnergy=None

            if self.energyMotor is not None:
                self.energyMotor.connect('positionChanged', self.energyPositionChanged)
                self.energyMotor.connect('stateChanged', self.energyStateChanged)
                self.energyMotor.connect('limitsChanged', self.energyLimitsChanged)
                self.energyMotor.connect('energyChanged', self.energyChanged)
            if self.resolutionMotor is None:
                logging.getLogger("HWR").warning('EnergyScan: no resolution motor (unable to restore it after moving the energy)')
            else:
                self.resolutionMotor.connect('positionChanged', self.resolutionPositionChanged)

        self.thEdgeThreshold = self.getProperty("theoritical_edge_threshold")
        if self.thEdgeThreshold is None:
           self.thEdgeThreshold = 0.01
        
    def resolutionPositionChanged(self,res):
        self.lastResolution=res

    def energyStateChanged(self, state):
        if state == self.energyMotor.READY:
            if self.resolutionMotor is not None:
               self.resolutionMotor.dist2res()
    
    def setElement(self):
        logging.getLogger("HWR").debug('EnergyScan: setElement')
        self.emit('setElement', (self._element, self._edge))
        
    def newPoint(self, x, y):
        logging.getLogger("HWR").debug('EnergyScan:newPoint')
        logging.info('EnergyScan newPoint %s, %s' % (x, y))
        self.emit('addNewPoint', (x, y))
        self.emit('newScanPoint', (x, y))

    def newScan(self,scanParameters):
        logging.getLogger("HWR").debug('EnergyScan:newScan')
        self.emit('newScan', (scanParameters,))

    # Energy scan commands
    def canScanEnergy(self):
        if not self.isConnected():
            return False
        if self.energy2WavelengthConstant is None or self.energyScanArgs is None:
            return False
        return self.doEnergyScan is not None
        
    def startEnergyScan(self,element,edge,directory,prefix,session_id=None,blsample_id=None):
        self._element = element
        self._edge = edge
        logging.getLogger("HWR").debug('EnergyScan: starting energy scan %s, %s' % (self._element, self._edge))
        self.setElement()
        self.xanes_ho.setup(self, element, edge, directory, prefix, session_id, blsample_id, plot=False)
        
        self.scanInfo={"sessionId":session_id,"blSampleId":blsample_id,"element":element,"edgeEnergy":edge}
        if self.fluodetectorHO is not None:
            self.scanInfo['fluorescenceDetector']=self.fluodetectorHO.userName()
        if not os.path.isdir(directory):
            logging.getLogger("HWR").debug("EnergyScan: creating directory %s" % directory)
            try:
                os.makedirs(directory)
            except OSError,diag:
                logging.getLogger("HWR").error("EnergyScan: error creating directory %s (%s)" % (directory,str(diag)))
                self.emit('scanStatusChanged', ("Error creating directory",))
                return False

        scanParameter = {}
        scanParameter['title'] = "Energy Scan"
        scanParameter['xlabel'] = "Energy in keV"
        scanParameter['ylabel'] = "Normalized counts"
        self.newScan(scanParameter)

        curr={}
        curr["escan_dir"]=directory
        curr["escan_prefix"]=prefix

        self.archive_prefix = prefix

        try:
            #self.energyScanArgs.setValue(curr)
            logging.getLogger("HWR").debug('EnergyScan: current energy scan parameters (%s, %s, %s, %s)' % (element, edge, directory, prefix))
        except:
            logging.getLogger("HWR").exception('EnergyScan: error setting energy scan parameters')
            self.emit('scanStatusChanged', ("Error setting energy scan parameters",))
            return False
        try:
            self.scanCommandStarted()
            self.xanes_ho.scan() #start() #scan()
            self.scanCommandFinished('success')
        except:
            import traceback
            logging.getLogger("HWR").error('EnergyScan: problem calling sequence %s' % traceback.format_exc())
            self.scanCommandFailed()
            self.emit('scanStatusChanged', ("Error problem spec macro",))
            return False
        return True
    
    def cancelEnergyScan(self, *args):
        logging.info('SOLEILEnergyScan: canceling the scan')
        if self.scanning:
            self.xanes_ho.abort()
            self.ready_event.set()
    
    def scanCommandReady(self):
        if not self.scanning:
            self.emit('energyScanReady', (True,))
    
    def scanCommandNotReady(self):
        if not self.scanning:
            self.emit('energyScanReady', (False,))
    
    def scanCommandStarted(self, *args):
        self.scanInfo['startTime']=time.strftime("%Y-%m-%d %H:%M:%S")
        self.scanning = True
        self.emit('energyScanStarted', ())
    
    def scanCommandFailed(self, *args):
        self.scanInfo['endTime']=time.strftime("%Y-%m-%d %H:%M:%S")
        self.scanning = False
        self.storeEnergyScan()
        self.emit('energyScanFailed', ())
        self.ready_event.set()
    
    def scanCommandAborted(self, *args):
        self.emit('energyScanFailed', ())
        self.ready_event.set()
    
    def scanCommandFinished(self, result, *args):
        logging.getLogger("HWR").debug("EnergyScan: energy scan result is %s" % result)
        with cleanup(self.ready_event.set):
            self.scanInfo['endTime']=time.strftime("%Y-%m-%d %H:%M:%S")
            logging.getLogger("HWR").debug("EnergyScan: energy scan result is %s" % result)
            self.scanning = False
            if result==-1:
                self.storeEnergyScan()
                self.emit('energyScanFailed', ())
                return

            try:
              t = float(result["transmissionFactor"])
            except:
              pass
            else:
              self.scanInfo["transmissionFactor"]=t
            try:
                et=float(result['exposureTime'])
            except:
                pass
            else:
                self.scanInfo["exposureTime"]=et
            try:
                se=float(result['startEnergy'])
            except:
                pass
            else:
                self.scanInfo["startEnergy"]=se
            try:
                ee=float(result['endEnergy'])
            except:
                pass
            else:
                self.scanInfo["endEnergy"]=ee

            try:
                bsX=float(result['beamSizeHorizontal'])
            except:
                pass
            else:
                self.scanInfo["beamSizeHorizontal"]=bsX

            try:
                bsY=float(result['beamSizeVertical'])
            except:
                pass
            else:
                self.scanInfo["beamSizeVertical"]=bsY

            try:
                self.thEdge=float(result['theoreticalEdge'])/1000.0
            except:
                pass

        
            logging.info('SOLEILEnergyScan finished emitting signals') 

            self.emit('energyScanFinished', (self.scanInfo,))
            time.sleep(0.1)
            self.emit('energyScanFinished2', (self.scanInfo,))

    def doChooch(self, elt, edge, scanArchiveFilePrefix, scanFilePrefix):
        rawScanFile=os.path.extsep.join((scanFilePrefix, "raw"))
        scanFile=os.path.extsep.join((scanFilePrefix, "efs"))
        logging.info('SOLEILEnergyScan doChooch rawScanFile %s, scanFile %s' % (rawScanFile, scanFile))

        scanData = self.xanes_ho.getRawData()
        logging.info('scanData %s' % scanData)
        logging.info('PyChooch file %s' % PyChooch.__file__)
        pk, fppPeak, fpPeak, ip, fppInfl, fpInfl, chooch_graph_data = PyChooch.calc(scanData, elt, edge, scanFile)
        rm=(pk+30)/1000.0
        pk=pk/1000.0
        savpk = pk
        ip=ip/1000.0
        comm = ""

        self.thEdge = self.xanes_ho.getElementEdge()
        logging.getLogger("HWR").info("th. Edge %s ; chooch results are pk=%f, ip=%f, rm=%f" % (self.thEdge, pk,ip,rm))
        logging.info('math.fabs(self.thEdge - ip) %s' % math.fabs(self.thEdge - ip))
        logging.info('self.thEdgeThreshold %s' % self.thEdgeThreshold)
        if math.fabs(self.thEdge - ip) > self.thEdgeThreshold:
          logging.info('Theoretical edge too different from the one just determined')
          pk = 0
          ip = 0
          rm = self.thEdge + 0.03
          comm = 'Calculated peak (%f) is more that 10eV away from the theoretical value (%f). Please check your scan' % (savpk, self.thEdge)
   
          logging.getLogger("HWR").warning('EnergyScan: calculated peak (%f) is more that 20eV %s the theoretical value (%f). Please check your scan and choose the energies manually' % (savpk, (self.thEdge - ip) > 0.02 and "below" or "above", self.thEdge))

        archiveEfsFile=os.path.extsep.join((scanArchiveFilePrefix, "efs"))

        logging.info('archiveEfsFile %s' % archiveEfsFile)

        # Check access to archive directory
        dirname = os.path.dirname(archiveEfsFile)
        if not os.path.exists(dirname): 
            try:
               os.makedirs( dirname )
               logging.getLogger("user_level_log").info( "Chooch. Archive path (%s) created"  % dirname)
            except OSError:
               logging.getLogger("user_level_log").error( "Chooch. Archive path is not accessible (%s)" % dirname)
               return None
            except:
               import traceback
               logging.getLogger("user_level_log").error( "Error creating archive path (%s) \n   %s" % (dirname, traceback.format_exc()))
               return None
        else:
            if not os.path.isdir(dirname):
               logging.getLogger("user_level_log").error( "Chooch. Archive path does not seem to be a valid directory (%s)" % dirname)
               return None

        try:
          fi=open(scanFile)
          fo=open(archiveEfsFile, "w")
        except:
          import traceback
          logging.getLogger("user_level_log").error( traceback.format_exc())
          self.storeEnergyScan()
          self.emit("energyScanFailed", ())
          return None
        else:
          fo.write(fi.read())
          fi.close()
          fo.close()

        logging.info('archive saved')
        self.scanInfo["peakEnergy"]=pk
        self.scanInfo["inflectionEnergy"]=ip
        self.scanInfo["remoteEnergy"]=rm
        self.scanInfo["peakFPrime"]=fpPeak
        self.scanInfo["peakFDoublePrime"]=fppPeak
        self.scanInfo["inflectionFPrime"]=fpInfl
        self.scanInfo["inflectionFDoublePrime"]=fppInfl
        self.scanInfo["comments"] = comm
        logging.info('self.scanInfo %s' % self.scanInfo)
        
        logging.info('chooch_graph_data %s' % str(chooch_graph_data))
        chooch_graph_x, chooch_graph_y1, chooch_graph_y2 = zip(*chooch_graph_data)
        chooch_graph_x = list(chooch_graph_x)
        logging.info('chooch_graph_x %s' %  str(chooch_graph_x))
        for i in range(len(chooch_graph_x)):
          chooch_graph_x[i]=chooch_graph_x[i]/1000.0

        logging.getLogger("HWR").info("<chooch> Saving png" )
        # prepare to save png files
        title="%10s  %6s  %6s\n%10s  %6.2f  %6.2f\n%10s  %6.2f  %6.2f" % ("energy", "f'", "f''", pk, fpPeak, fppPeak, ip, fpInfl, fppInfl) 
        fig=Figure(figsize=(15, 11))
        ax=fig.add_subplot(211)
        ax.set_title("%s\n%s" % (scanFile, title))
        ax.grid(True)
        ax.plot(*(zip(*scanData)), **{"color":'black'})
        ax.set_xlabel("Energy")
        ax.set_ylabel("MCA counts")
        ax2=fig.add_subplot(212)
        ax2.grid(True)
        ax2.set_xlabel("Energy")
        ax2.set_ylabel("")
        handles = []
        handles.append(ax2.plot(chooch_graph_x, chooch_graph_y1, color='blue'))
        handles.append(ax2.plot(chooch_graph_x, chooch_graph_y2, color='red'))
        canvas=FigureCanvasAgg(fig)

        escan_png = os.path.extsep.join((scanFilePrefix, "png"))
        self.escan_archivepng = os.path.extsep.join((scanArchiveFilePrefix, "png")) 
        escan_ispyb_path = self.session_ho.path_to_ispyb( self.escan_archivepng )
        self.scanInfo["jpegChoochFileFullPath"]=str(escan_ispyb_path)
        try:
          logging.getLogger("HWR").info("Rendering energy scan and Chooch graphs to PNG file : %s", escan_png)
          canvas.print_figure(escan_png, dpi=80)
        except:
          logging.getLogger("HWR").exception("could not print figure")
        try:
          logging.getLogger("HWR").info("Saving energy scan to archive directory for ISPyB : %s", self.escan_archivepng)
          canvas.print_figure(self.escan_archivepng, dpi=80)
        except:
          logging.getLogger("HWR").exception("could not save figure")

        self.storeEnergyScan()
        #self.scanInfo=None

        logging.getLogger("HWR").info("<chooch> returning %s" % [pk, fppPeak, fpPeak, ip, fppInfl, fpInfl, rm, chooch_graph_x, chooch_graph_y1, chooch_graph_y2, title])

        self.emit('chooch_finished', (pk, fppPeak, fpPeak, ip, fppInfl, fpInfl, rm, chooch_graph_x, chooch_graph_y1, chooch_graph_y2, title))
        self.choochResults = pk, fppPeak, fpPeak, ip, fppInfl, fpInfl, rm, chooch_graph_x, chooch_graph_y1, chooch_graph_y2, title
        return pk, fppPeak, fpPeak, ip, fppInfl, fpInfl, rm, chooch_graph_x, chooch_graph_y1, chooch_graph_y2, title

    def scanStatusChanged(self,status):
        self.emit('scanStatusChanged', (status,))
    
    def storeEnergyScan(self):
        self.xanes_ho.saveRaw()
        self.xanes_ho.saveResults()
        
        if self.dbConnection is None:
            return
        try:
            session_id=int(self.scanInfo['sessionId'])
        except:
            return

        self.storeScanInLIMS(wait=False)

        logging.info('SOLEILEnergyScan storeEnergyScan OK')

    @task
    def storeScanInLIMS(self):
        scanInfo = dict(self.scanInfo)

        blsampleid = scanInfo['blSampleId']
        scanInfo.pop('blSampleId')

        db_status=self.dbConnection.storeEnergyScan(scanInfo)

        if blsampleid is not None:
            try:
                energyscanid=int(db_status['energyScanId'])
            except:
                pass
            else:
                asoc={'blSampleId':blsampleid, 'energyScanId':energyscanid}
                self.dbConnection.associateBLSampleAndEnergyScan(asoc)

        self.ruche_ho.trigger_sync( self.escan_archivepng )

    def updateEnergyScan(self,scan_id,jpeg_scan_filename):
        pass

    # Move energy commands
    def canMoveEnergy(self):
        return self.canScanEnergy()
    
    def getCurrentEnergy(self):
        if self.energyMotor is not None:
            try:
                return self.energyMotor.getPosition()
            except: 
                logging.getLogger("HWR").exception("EnergyScan: couldn't read energy")
                return None
        elif self.energy2WavelengthConstant is not None and self.defaultWavelength is not None:
            return self.energy2wavelength(self.defaultWavelength)
        return None


    def get_value(self):
        return self.getCurrentEnergy()

    def getPosition(self):
        return self.getCurrentEnergy()    
    
    def getEnergyLimits(self):
        lims=None
        if self.energyMotor is not None:
            if self.energyMotor.isReady():
                lims=self.energyMotor.getLimits()
        return lims
    
    def getCurrentWavelength(self):
        if self.energyMotor is not None:
            try:
                return self.energy2wavelength(self.energyMotor.getPosition())
            except:
                logging.getLogger("HWR").exception("EnergyScan: couldn't read energy")
                return None
        else:
            logging.getLogger("HWR").exception("EnergyScan: self.energyMotor not defined !")
            return self.defaultWavelength
    
    def getWavelengthLimits(self):
        lims=None
        if self.energyMotor is not None:
            if self.energyMotor.isReady():
                energy_lims=self.energyMotor.getLimits()
                lims=(self.energy2wavelength(energy_lims[1]),self.energy2wavelength(energy_lims[0]))
                if lims[0] is None or lims[1] is None:
                    lims=None
        return lims
    
    def startMoveEnergy(self,value,wait=True):
        lims = None
        logging.getLogger("HWR").info("Moving energy to (%s)" % value)
        try:
            value=float(value)
        except (TypeError,ValueError),diag:
            logging.getLogger("HWR").error("EnergyScan: invalid energy (%s)" % value)
            return False

        try:
            curr_energy=self.energyMotor.getPosition()
        except:
            logging.getLogger("HWR").exception("EnergyScan: couldn't get current energy")
            curr_energy=None

        if value!=curr_energy:
            logging.getLogger("HWR").info("Moving energy: checking limits")
            try:
                lims=self.energyMotor.getLimits()
            except:
                logging.getLogger("HWR").exception("EnergyScan: couldn't get energy limits")
                in_limits=False
            else:
                in_limits=value>=lims[0] and value<=lims[1]
                
            if in_limits:
                logging.getLogger("HWR").info("Moving energy: limits ok")
                self.previousResolution=None
                if self.resolutionMotor is not None:
                    try:
                        self.previousResolution=self.resolutionMotor.getPosition()
                    except:
                        logging.getLogger("HWR").exception("EnergyScan: couldn't get current resolution")
                self.moveEnergyCmdStarted()
                def change_egy():
                    try:
                        self.moveEnergy(value, wait=True)
                    except:
                        self.moveEnergyCmdFailed()
                    else:
                        self.moveEnergyCmdFinished(True)
                if wait:
                    change_egy()
                else:
                    gevent.spawn(change_egy)
            else:
                logging.getLogger("HWR").error("EnergyScan: energy (%f) out of limits (%s)" % (value,lims))
                return False          
        else:
            return None

        return True
    
    def startMoveWavelength(self,value, wait=True):
        energy_val=self.energy2wavelength(value)
        if energy_val is None:
            logging.getLogger("HWR").error("EnergyScan: unable to convert wavelength to energy")
            return False
        return self.startMoveEnergy(energy_val, wait)
    
    def cancelMoveEnergy(self):
        self.moveEnergy.abort()
    
    def energy2wavelength(self,val):
        if self.energy2WavelengthConstant is None:
            return None
        try:
            other_val=self.energy2WavelengthConstant/val
        except ZeroDivisionError:
            other_val=None
        return other_val
   
    def energyChanged(self, pos, wav):
        self.emit('energyChanged', (pos,wav))
        self.emit('valueChanged', (pos, ))

    def energyPositionChanged(self,pos):
        wav=self.energy2wavelength(pos)
        if wav is not None:
            self.emit('energyChanged', (pos,wav))
            self.emit('valueChanged', (pos, ))
    
    def energyLimitsChanged(self,limits):
        self.emit('energyLimitsChanged', (limits,))
        wav_limits=(self.energy2wavelength(limits[1]),self.energy2wavelength(limits[0]))
        if wav_limits[0]!=None and wav_limits[1]!=None:
            self.emit('wavelengthLimitsChanged', (wav_limits,))
        else:
            self.emit('wavelengthLimitsChanged', (None,))
    
    def moveEnergyCmdReady(self):
        if not self.moving:
            self.emit('moveEnergyReady', (True,))
    
    def moveEnergyCmdNotReady(self):
        if not self.moving:
            self.emit('moveEnergyReady', (False,))
    
    def moveEnergyCmdStarted(self):
        self.moving = True
        self.emit('moveEnergyStarted', ())
    
    def moveEnergyCmdFailed(self):
        self.moving = False
        self.emit('moveEnergyFailed', ())
    
    def moveEnergyCmdAborted(self):
        pass
        #self.moving = False
        #self.emit('moveEnergyFailed', ())
    
    def moveEnergyCmdFinished(self,result):
        self.moving = False
        self.emit('moveEnergyFinished', ())

    def getPreviousResolution(self):
        return (self.previousResolution,self.lastResolution)

    def restoreResolution(self):
        if self.resolutionMotor is not None:
            if self.previousResolution is not None:
                try:
                    self.resolutionMotor.move(self.previousResolution)
                except:
                    return (False,"Error trying to move the detector")
                else:
                    return (True,None)
            else:
                return (False,"Unknown previous resolution")
        else:
            return (False,"Resolution motor not defined")

    # Elements commands
    def getElements(self):
        elements=[]
        try:
            for el in self["elements"]:
                elements.append({"symbol":el.symbol, "energy":el.energy})
        except IndexError:
            pass
        return elements

    # Mad energies commands
    def getDefaultMadEnergies(self):
        energies=[]
        try:
            for el in self["mad"]:
                energies.append([float(el.energy), el.directory])
        except IndexError:
            pass
        return energies

