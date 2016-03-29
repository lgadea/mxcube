"""

PX1Cats sample changer hardware object.

Support for the CATS sample changer at SOLEIL PX1.  Using the 
device server CryoTong by Patrick Gourhant

Implements the abstract interface of the GenericSampleChanger for the CATS
sample changer model.

This object includes both the SampleChanger interface and the Maintenance features 
as initially developed by Michael Hellmig for BESSY beamlines

"""

import logging
from GenericSampleChanger import *
from PX1Environment import EnvironmentPhase
import time
import gevent

from HardwareRepository.TaskUtils import *

from HardwareRepository import HardwareRepository
from HardwareRepository.BaseHardwareObjects import Equipment

__author__ = "Bixente Rey Bakaikoa"
__credits__ = ["The MxCuBE collaboration"]

class Pin(Sample):        
    STD_HOLDERLENGTH = 22.0

    def __init__(self,basket,basket_no,sample_no):
        super(Pin, self).__init__(basket, Pin.getSampleAddress(basket_no,sample_no), True)
        self._setHolderLength(Pin.STD_HOLDERLENGTH)

    def getBasketNo(self):
        return self.getContainer().getIndex()+1

    def getVialNo(self):
        return self.getIndex()+1

    @staticmethod
    def getSampleAddress(basket_number, sample_number):
        return str(basket_number) + ":" + "%02d" % (sample_number)


class Basket(Container):
    __TYPE__ = "Puck"    
    NO_OF_SAMPLES_PER_PUCK = 16

    def __init__(self,container,number):
        super(Basket, self).__init__(self.__TYPE__,container,Basket.getBasketAddress(number),True)
        for i in range(Basket.NO_OF_SAMPLES_PER_PUCK):
            slot = Pin(self,number,i+1)
            self._addComponent(slot)
                            
    @staticmethod
    def getBasketAddress(basket_number):
        return str(basket_number)

    def clearInfo(self):
	self.getContainer()._reset_basket_info(self.getIndex()+1)
        self.getContainer()._triggerInfoChangedEvent()


class PX1Cats(SampleChanger):
    """
    Actual implementation of the CATS Sample Changer,
    BESSY BL14.1 installation with 3 lids and 90 samples
    """    
    __TYPE__ = "CATS"    
    NO_OF_LIDS    = 1
    NO_OF_BASKETS = 3
    TOOL = "1"   # CryoTong

    def __init__(self, *args, **kwargs):
        super(PX1Cats, self).__init__(self.__TYPE__,False, *args, **kwargs)
            
    def init(self):      
        self._selected_sample = None
        self._selected_basket = None

        self.task_started = 0
        self.task_name = None
        self.last_state_emit = 0

        self._lidState = None
        self._poweredState = None
        self._toolState = None
        self._safeNeeded = None
        self._ln2regul = None
        self._last_status = None
        self._sc_state = None
        self._global_state = None

        self.currentBasketDataMatrix = "this-is-not-a-matrix"
        self.currentSample = -1
        self.currentBasket = -1

        # initialize the sample changer components, moved here from __init__ after allowing
        # variable number of lids
        for i in range(PX1Cats.NO_OF_BASKETS):
            basket = Basket(self,i+1)
            self._addComponent(basket)

        self.environment = self.getObjectByRole("environment")

        if self.environment is None:
            logging.error("PX1Cats. environment object not available. Sample changer cannot operate. Info.mode only")
            self.infomode = True
        else:
            self.infomode = False

        for channel_name in ("_chnState", "_chnStatus", \
                             "_chnLidState", "_chnPathRunning", \
                             "_chnPowered", "_chnSafeNeeded", \
                             "_chnLN2Regulation", \
                             "_chnSoftAuth","_chnhomeOpened", \
                             "_chnPathRunning", "_chnMessage", \
                             "_chnNumLoadedSample", "_chnLidLoadedSample", \
                             "_chnSampleBarcode", "_chnSampleIsDetected",
			     "_chnDryAndSoakNeeded", "_chnIncoherentGonioSampleState"):
            setattr(self, channel_name, self.getChannelObject(channel_name))
#                             "_chnToolOpen", "_chnLN2Regulation", \
           
        self._chnLidState.connectSignal("update", self._updateLidState)
        self._chnPowered.connectSignal("update", self._updatePoweredState)
        self._chnSafeNeeded.connectSignal("update", self._updateSafeNeeded)
        self._chnLN2Regulation.connectSignal("update", self._updateRegulationState)
        #self._chnToolOpen.connectSignal("update", self._updateToolOpen) 
        self._chnSoftAuth.connectSignal("update", self._softwareAuthorization) 
        self._chnPathRunning.connectSignal("update", self._updateRunningState)
        self._chnMessage.connectSignal("update", self._updateMessage)
        self._chnIncoherentGonioSampleState.connectSignal("update", self._updateAckSampleMemory)
        self._chnDryAndSoakNeeded.connectSignal("update",self._dryAndSoakNeeded)
        for basket_index in range(PX1Cats.NO_OF_BASKETS):            
            channel_name = "_chnBasket%dState" % (basket_index + 1)
            setattr(self, channel_name, self.getChannelObject(channel_name))

        for command_name in ("_cmdAbort", "_cmdLoad", "_cmdUnload", "_cmdChainedLoad", \
                             "_cmdReset", "_cmdSafe", "_cmdClearMemory", "_cmdAckSampleMemory", "_cmdPowerOn", "_cmdPowerOff", \
                             "_cmdOpenLid", "_cmdCloseLid", "_cmdDrySoak", "_cmdSoak", "_cmdRegulOn", "_cmdRegulOff"):
            setattr(self, command_name, self.getCommandObject(command_name))

        self._initSCContents()

        # SampleChanger.init must be called _after_ initialization of the Cats because it starts the update methods which access
        # the device server's status attributes
        SampleChanger.init(self)   

    def getSampleProperties(self):
        """
        Get the sample's holder length

        :returns: sample length [mm]
        :rtype: double
        """
        return (Pin.__HOLDER_LENGTH_PROPERTY__,)
        
    def is_mounted_sample(self, sample_location):        
        try:
            if sample_location == tuple(map(str,self.getLoadedSample().getCoords())):
                return True
            else:
                return False
        except AttributeError:
            logging.warning("PX1Cats. is_mounted_sample error.")
            return False 

    #########################           TASKS           #########################

    def getLoadedSampleDataMatrix(self):
        return "-not-a-matrix-"

    def _doUpdateInfo(self):       
        """
        Updates the sample changers status: mounted pucks, state, currently loaded sample

        :returns: None
        :rtype: None
        """
        self._updateSCContents()
        # periodically updating the selection is not needed anymore, because each call to _doSelect
        # updates the selected component directly:
        # self._updateSelection()

        self._updateState()               
        self._updateStatus()
        self._updateLidState()
        self._updatePoweredState()
        self._updateSafeNeeded()
        self._updateToolOpen()
        self._updateLoadedSample()
        self._updateRegulationState()

        self._updateGlobalState()
                    
    def _doChangeMode(self,mode):
        """
        Changes the SC operation mode, not implemented for the CATS system

        :returns: None
        :rtype: None
        """
        pass

    def _directlyUpdateSelectedComponent(self, basket_no, sample_no):    
        basket = None
        sample = None
        try:
          if basket_no is not None and basket_no>0 and basket_no <=PX1Cats.NO_OF_BASKETS:
            basket = self.getComponentByAddress(Basket.getBasketAddress(basket_no))
            if sample_no is not None and sample_no>0 and sample_no <=Basket.NO_OF_SAMPLES_PER_PUCK:
                sample = self.getComponentByAddress(Pin.getSampleAddress(basket_no, sample_no))            
        except:
          pass
        self.currentBasket = basket_no
        self.currentSample = sample_no
        self._setSelectedComponent(basket)
        self._setSelectedSample(sample)

    def _doSelect(self,component):
        """
        Selects a new component (basket or sample).
	Uses method >_directlyUpdateSelectedComponent< to actually search and select the corrected positions.

        :returns: None
        :rtype: None
        """
        if isinstance(component, Sample):
            selected_basket_no = component.getBasketNo()
            selected_sample_no = component.getIndex()+1
        elif isinstance(component, Container) and ( component.getType() == Basket.__TYPE__):
            selected_basket_no = component.getIndex()+1
            selected_sample_no = None
        self._directlyUpdateSelectedComponent(selected_basket_no, selected_sample_no)
            
    def _doScan(self,component,recursive):
        """
        Scans the barcode of a single sample, puck or recursively even the complete sample changer.

        :returns: None
        :rtype: None
        """

        selected_basket = self.getSelectedComponent()
        if isinstance(component, Sample):            
            # scan a single sample
            if (selected_basket is None) or (selected_basket != component.getContainer()):
                self._doSelect(component)            
            selected=self.getSelectedSample()            

            lid, sample = self._getLidSampleFromSelected(selected) 
            argin = [PX1Cats.TOOL, str(lid), str(sample), "0", "0"]

            self._executeServerTask(self._cmdScanSample, "ScanSample", argin=argin)
            self._updateSampleBarcode(component)
        elif isinstance(component, Container) and ( component.getType() == Basket.__TYPE__):
            # component is a basket
            if recursive:
                pass
            else:
                if (selected_basket is None) or (selected_basket != component):
                    self._doSelect(component)            
                # self._executeServerTask(self._scan_samples, (0,))                
                selected=self.getSelectedSample()            
                for sample_index in range(Basket.NO_OF_SAMPLES_PER_PUCK):
                    lid, sample = self._getLidSampleFromSelected( selected, sample_index )
                    argin = [PX1Cats.TOOL, str(lid), str(sample), "0", "0"]
                    self._executeServerTask(self._cmdScanSample, "ScanSample", argin=argin)
        elif isinstance(component, Container) and ( component.getType() == SC3.__TYPE__):
            for basket in self.getComponents():
                self._doScan(basket, True)
    
    def _getLidSampleFromSelected(self,selected,sample_index=None):
        lid = 1
        if sample_index is None:
            sample_index = selected.getVialNo()-1

        sample = ((selected.getBasketNo() - 1)  * Basket.NO_OF_SAMPLES_PER_PUCK) + (sample_index+1)
        return lid, sample

    def _doLoad(self,sample=None):
        """
        Loads a sample on the diffractometer. Performs a simple put operation if the diffractometer is empty, and 
        a sample exchange (unmount of old + mount of new sample) if a sample is already mounted on the diffractometer.

        :returns: None
        :rtype: None
        """
        #logging.info("XXXXXXXXXXXXXXXXXXXXXXXXXxxxxxxxxxxxxxxxxxxx PX1Cats _doLoad" )
        selected=self.getSelectedSample()            
        if sample is not None:
            if sample != selected:
                self._doSelect(sample)
                selected=self.getSelectedSample()            
        else:
            if selected is not None:
                 sample = selected
            else:
               raise Exception("No sample selected")

        if selected==self.getLoadedSample():
            logging.info("PX1Cats. trying to load an already loaded sample. nothing to do" )
            self._waitDeviceState( [SampleChangerState.Ready, SampleChangerState.StandBy],  )
            return True

        # calculate CATS specific lid/sample number
        lid, sample = self._getLidSampleFromSelected(selected)
        argin = [PX1Cats.TOOL, str(lid), str(sample), "1", "0", "0", "0", "0"]
            
        self._setState( SampleChangerState.Loading )
        self.current_state = SampleChangerState.Loading

        if not self.environment.readyForTransfer():
             self.environment.setPhase(EnvironmentPhase.TRANSFER)
        if self.hasLoadedSample():
            if selected==self.getLoadedSample():
                raise Exception("The sample " + str(self.getLoadedSample().getAddress()) + " is already loaded")
            else:
                self._executeServerTask(self._cmdChainedLoad, "Exchange", states=[SampleChangerState.Ready,], argin=argin)
        else:
                self._executeServerTask(self._cmdLoad, "Load", states=[SampleChangerState.Ready,], argin=argin)
                
	
	# Check the value of the CATSCRYOTONG attribute dryAndSoakNeeded to warn user if it is True
	dryAndSoak = self._chnDryAndSoakNeeded.getValue()
	if dryAndSoak:
	    logging.getLogger('user_level_log').warning("CATS: It is recommended to Dry_and_Soak the gripper.")

	incoherentSample = self._chnIncoherentGonioSampleState.getValue()
	if incoherentSample:
            logging.getLogger("user_level_log").info("CATS: Load/Unload Error. Please try again.")
            self.emit('loadError', incoherentSample)
          
            
    def _doUnload(self,sample_slot=None):
        """
        Unloads a sample from the diffractometer.

        :returns: None
        :rtype: None
        """
        if (sample_slot is not None):
            self._doSelect(sample_slot)

        if not self.environment.readyForTransfer():
             self.environment.setPhase(EnvironmentPhase.TRANSFER)
        
        self._setState( SampleChangerState.Loading )
        self.current_state = SampleChangerState.Loading

        argin = [PX1Cats.TOOL, "0", "0", "0", "0"]
        self._executeServerTask(self._cmdUnload, "Unload", states=[SampleChangerState.Ready,], argin=argin)

    def clearBasketInfo(self, basket):
        pass

    ################################################################################

    def _doAbort(self):
        """
        Aborts a running trajectory on the sample changer.

        :returns: None
        :rtype: None
        """
        self._cmdAbort()            

    #########################           PRIVATE           #########################        

    def _softwareAuthorization(self, value):
        self.emit("softwareAuthorizationChanged", (value,))
        
    def _executeServerTask(self, method, taskname, states=None, argin=None, *args):
        """
        Executes a task on the CATS Tango device server

        :returns: None
        :rtype: None
        """
        if self.infomode:
            logging.warning("PX1Cats. It is in info mode only. Command %s ignored" % taskname)
            return 
        self._waitDeviceReady(3.0)
        #if states == None:
        #    states = [SampleChangerState.Ready, SampleChangerState.StandBy]

        #self._waitDeviceState( states, 3.0 )

        if argin == None:
           task_id = method()
        else:
           task_id = method(argin)

        self.task_started = time.time()
        self.task_name = taskname

        ret=None
        if task_id is None: #Reset
            while self._isDeviceBusy():
                gevent.sleep(0.1)
            #state = self._readState()
        else:
            self._pathRunning(10.0)
            
            while str(self._chnPathRunning.getValue()).lower() == 'true':
                gevent.sleep(0.1) 
            ret = True
        return ret
        
    def _pathRunning(self,timeout=None):
        """
        Waits until the path running is true

        :returns: None
        :rtype: None
        """
        with gevent.Timeout(timeout, Exception("Timeout waiting for device ready")):
            while not self._chnPathRunning.getValue():
                gevent.sleep(0.01)

    def _updateState(self):
        """
        Updates the state of the hardware object

        :returns: None
        :rtype: None
        """

        try:
          state = self._readState()
        except:
          import traceback
          traceback.print_exc()
          state = SampleChangerState.Unknown

        if state == SampleChangerState.Moving and self._isDeviceBusy(self.getState()):
            return          

        if self._chnPathRunning.getValue(): 
            state = SampleChangerState.Moving

        self._setState(state)

    def _readState(self):
        """
        Read the state of the Tango DS and translate the state to the SampleChangerState Enum

        :returns: Sample changer state
        :rtype: GenericSampleChanger.SampleChangerState
        """

        state = self._chnState.getValue()
       
        if state is not None:
            stateStr = str(state).upper()
        else:
            stateStr = ""
       
        state_converter = { "ALARM": SampleChangerState.Alarm,
                            "ON": SampleChangerState.Ready,
                            "OFF": SampleChangerState.Off,
                            "DISABLE": SampleChangerState.Unknown,
                            "STANDBY": SampleChangerState.StandBy,
                            "FAULT": SampleChangerState.Fault,
                            "RUNNING": SampleChangerState.Moving }

        sc_state = state_converter.get(stateStr, SampleChangerState.Unknown)
        if sc_state in [SampleChangerState.Ready, SampleChangerState.StandBy]:
            if ( time.time() - self.task_started ) < 3.0:
                sc_state = SampleChangerState.Moving

        self._sc_state = sc_state
        return sc_state
                        
    def _updateStatus(self):
        try:
            status = self._chnStatus.getValue()
            self._last_status = status
        except:
            pass
       
    def _isDeviceBusy(self, state=None):
        """
        Checks whether Sample changer HO is busy.

        :returns: True if the sample changer is busy
        :rtype: Bool
        """
        if state is None:
            state = self._readState()

        return state not in (SampleChangerState.Ready, SampleChangerState.Alarm, SampleChangerState.Off,
                             SampleChangerState.StandBy, SampleChangerState.Fault )

    def _isDeviceReady(self):
        """
        Checks whether Sample changer HO is ready.

        :returns: True if the sample changer is ready
        :rtype: Bool
        """
        state = self._readState()
        return state in (SampleChangerState.Ready, SampleChangerState.StandBy )              

    def _waitDeviceState(self,states,timeout=None):
        """
        Waits until the samle changer HO is ready.

        :states: List of states to authorize start of task
        :timeout: Maximum waiting time. If no timeout is given, wait forever
        :returns: None
        :rtype: None
        """

        with gevent.Timeout(timeout, Exception("Timeout waiting for device ready")):
            waiting = True
            while not waiting:
                state = self._readState()
                if state in states:
                    waiting = False
                gevent.sleep(0.01)

    def _waitDeviceReady(self,timeout=None):
        """
        Waits until the samle changer HO is ready.

        :returns: None
        :rtype: None
        """
        with gevent.Timeout(timeout, Exception("Timeout waiting for device ready")):
            while not self._isDeviceReady():
                gevent.sleep(0.01)
            
    def _updateSelection(self):    
        """
        Updates the selected basket and sample. NOT USED ANYMORE FOR THE CATS.
        Legacy method left from the implementation of the SC3 where the currently selected sample
        is always read directly from the SC3 Tango DS

        :returns: None
        :rtype: None
        """
        #import pdb; pdb.set_trace()
        basket=None
        sample=None
        # print "_updateSelection: saved selection: ", self._selected_basket, self._selected_sample
        try:
          basket_no = self._selected_basket
          if basket_no is not None and basket_no>0 and basket_no <=PX1Cats.NO_OF_BASKETS:
            basket = self.getComponentByAddress(Basket.getBasketAddress(basket_no))
            sample_no = self._selected_sample
            if sample_no is not None and sample_no>0 and sample_no <=Basket.NO_OF_SAMPLES_PER_PUCK:
                sample = self.getComponentByAddress(Pin.getSampleAddress(basket_no, sample_no))            
        except:
          pass
        #if basket is not None and sample is not None:
        #    print "_updateSelection: basket: ", basket, basket.getIndex()
        #    print "_updateSelection: sample: ", sample, sample.getIndex()
        self._setSelectedComponent(basket)
        self._setSelectedSample(sample)

    def _updateLoadedSample(self):
        """
        Reads the currently mounted sample basket and pin indices from the CATS Tango DS,
        translates the lid/sample notation into the basket/sample notation and marks the 
        respective sample as loaded.

        :returns: None
        :rtype: None
        """
        loadedSampleLid = self._chnLidLoadedSample.getValue()
        loadedSampleNum = self._chnNumLoadedSample.getValue()
        if loadedSampleLid != -1 or loadedSampleNum != -1:
            lidOffset = ((loadedSampleNum - 1) / Basket.NO_OF_SAMPLES_PER_PUCK) + 1
            samplePos = ((loadedSampleNum - 1) % Basket.NO_OF_SAMPLES_PER_PUCK) + 1
            basket = lidOffset
        else:
            basket = None
            samplePos = None
 
        if basket is not None and samplePos is not None:
            new_sample = self.getComponentByAddress(Pin.getSampleAddress(basket, samplePos))
        else:
            new_sample = None

        if self.getLoadedSample() != new_sample:
            # import pdb; pdb.set_trace()
            # remove 'loaded' flag from old sample but keep all other information
            old_sample = self.getLoadedSample()
            if old_sample is not None:
                # there was a sample on the gonio
                loaded = False
                has_been_loaded = True
                old_sample._setLoaded(loaded, has_been_loaded)
            if new_sample is not None:
                self._updateSampleBarcode(new_sample)
                loaded = True
                has_been_loaded = True
                new_sample._setLoaded(loaded, has_been_loaded)

    def _updateSampleBarcode(self, sample):
        """
        Updates the barcode of >sample< in the local database after scanning with
        the barcode reader.

        :returns: None
        :rtype: None
        """
        # update information of recently scanned sample
        datamatrix = str(self._chnSampleBarcode.getValue())
        scanned = (len(datamatrix) != 0)
        if not scanned:    
           datamatrix = '----------'   
        sample._setInfo(sample.isPresent(), datamatrix, scanned)

    def _initSCContents(self):
        """
        Initializes the sample changer content with default values.

        :returns: None
        :rtype: None
        """
        # create temporary list with default basket information
        basket_list= [('', 4)] * PX1Cats.NO_OF_BASKETS
        # write the default basket information into permanent Basket objects 
        for basket_index in range(PX1Cats.NO_OF_BASKETS):            
            basket=self.getComponents()[basket_index]
            datamatrix = None
            present = scanned = False
            basket._setInfo(present, datamatrix, scanned)

        # create temporary list with default sample information and indices
        sample_list=[]
        for basket_index in range(PX1Cats.NO_OF_BASKETS):            
            for sample_index in range(Basket.NO_OF_SAMPLES_PER_PUCK):
                sample_list.append(("", basket_index+1, sample_index+1, 1, Pin.STD_HOLDERLENGTH)) 
        # write the default sample information into permanent Pin objects 
        for spl in sample_list:
            sample = self.getComponentByAddress(Pin.getSampleAddress(spl[1], spl[2]))
            datamatrix = None
            present = scanned = loaded = has_been_loaded = False
            sample._setInfo(present, datamatrix, scanned)
            sample._setLoaded(loaded, has_been_loaded)
            sample._setHolderLength(spl[4])    

    def _updateSCContents(self):
        """
        Updates the sample changer content. The state of the puck positions are
        read from the respective channels in the CATS Tango DS.
        The CATS sample sample does not have an detection of each individual sample, so all
        samples are flagged as 'Present' if the respective puck is mounted.

        :returns: None
        :rtype: None
        """
        for basket_index in range(PX1Cats.NO_OF_BASKETS):            
            # get presence information from the device server
            newBasketPresence = getattr(self, "_chnBasket%dState" % (basket_index + 1)).getValue()
            # get saved presence information from object's internal bookkeeping
            basket=self.getComponents()[basket_index]
           
            # check if the basket was newly mounted or removed from the dewar
            if newBasketPresence ^ basket.isPresent():
                # import pdb; pdb.set_trace()
                # a mounting action was detected ...
                if newBasketPresence:
                    # basket was mounted
                    present = True
                    scanned = False
                    datamatrix = None
                    basket._setInfo(present, datamatrix, scanned)
                else:
                    # basket was removed
                    present = False
                    scanned = False
                    datamatrix = None
                    basket._setInfo(present, datamatrix, scanned)
                # set the information for all dependent samples
                for sample_index in range(Basket.NO_OF_SAMPLES_PER_PUCK):
                    sample = self.getComponentByAddress(Pin.getSampleAddress((basket_index + 1), (sample_index + 1)))
                    present = sample.getContainer().isPresent()
                    if present:
                        datamatrix = '          '   
                    else:
                        datamatrix = None
                    scanned = False
                    sample._setInfo(present, datamatrix, scanned)
                    # forget about any loaded state in newly mounted or removed basket)
                    loaded = has_been_loaded = False
                    sample._setLoaded(loaded, has_been_loaded)
    
    #----------------------------------------------------------------------------------------------------
    #
    # MAINTENANCE PART 
    #
    #----------------------------------------------------------------------------------------------------

    ################################################################################

    def safeTraj(self):    
        """
        Safely Moves the robot arm and the gripper to the home position
        """    
        return self._doSafe()     


    def _doReset(self):
        """
        Launch the "reset" command on the CATS Tango DS

        :returns: None
        :rtype: None
        """
        self._cmdReset()

    def _doClearMemory(self):
        """
        Launch the "ClearMemory" command on the CATS Tango DS

        :returns: None
        :rtype: None
        """
        self._cmdClearMemory()

    def _doAckSampleMemory(self):
        """
        Launch the "AckIncoherentGonioSampleState" command on the CATS Tango DS

        :returns: None
        :rtype: None
        """
        self._cmdAckSampleMemory()

    def _doDrySoak(self):
        """
        Launch the "DrySoak" command on the CATS Tango DS

        :returns: None
        :rtype: None
        """
        if self.infomode:
            logging.warning("PX1Cats. It is in info mode only. DrySoak command ignored")
            return 

        self._cmdDrySoak()

    def _doSafe(self):
        """
        Launch the "safe" trajectory on the CATS Tango DS

        :returns: None
        :rtype: None
        """
        #if not self.environment.readyForTransfer():
        #     self.environment.setPhase(EnvironmentPhase.TRANSFER)
        
        if self.environment.readyForTransfer():
            self._executeServerTask(self._cmdSafe, "Safe", states=[SampleChangerState.Ready, SampleChangerState.Alarm])
        else :
            self.environment.setPhase(EnvironmentPhase.TRANSFER)

    def _doPowerState(self, state=False):
        """
        Switch on CATS power if >state< == True, power off otherwise

        :returns: None
        :rtype: None
        """
        if state:
            self._cmdPowerOn()
        else:
            self._cmdPowerOff()

    def _doEnableRegulation(self):
        """
        Switch on CATS regulation

        :returns: None
        :rtype: None
        """
        self._cmdRegulOn()

    def _doHomeOpen(self):
        """
        Execute HomeOpen command on CATS

        :returns: None
        :rtype: None
        """
        self._executeServerTask(self._cmdHomeOpen, "HomeOpen")
	
    def _doSoak(self):
        """
        Execute Soak command on CATS

        :returns: None
        :rtype: None
        """
        self._cmdSoak()

    def _doLidState(self, state = True):
        """
        Opens lid if >state< == True, closes the lid otherwise

        :returns: None
        :rtype: None
        """
        if state:
            self._executeServerTask(self._cmdOpenLid, "OpenLid")
        else:
            self._executeServerTask(self._cmdCloseLid, "CloseLid")
           
    def _doToolOpen(self, state=False):
        """

        Open/close CATS tool 

        :returns: None
        :rtype: None
        """
        #if state:
        #    self._chnToolOpen.setValue(True)
        #else:
        #    self._chnToolOpen.setValue(False)
        return

    def _updateGlobalState(self):
        """
        At least every two seconds re-emit a list with state values as it seems
        the brick is missing events
        Device values are updated in previous calls.  See doUpdateInfo()
        """  
        now = time.time()  
        global_state ={ 'SCstate': self._sc_state,
                        'lidOpen': not self._lidState, 
                        'safeNeeded': self._safeNeeded, 
                        'powered': self._poweredState,
                        'ln2regul': self._ln2regul,
                        'toolOpen': self._toolState,
                        'status': self._last_status } 

        if global_state != self._global_state or (now - self.last_state_emit) > 1.0:
              self.emit("stateValues", global_state)
              self._global_state = global_state
              self.last_state_emit = time.time()  

    def _updateRunningState(self, value):
        self.emit('runningStateChanged', (value, ))

    def _updateMessage(self, value):
        self.emit('messageChanged', (value, ))

    def _updateRegulationState(self, value=None):
        if value is None:
# Modif Patrick le 18/03/2015
# Correction probleme sur etat de la regulation qui reste en rouge
#             value = self._chnSafeNeeded.getValue()
             value = self._chnLN2Regulation.getValue()

        if self._ln2regul != value:
             self._ln2regul = value
             self.emit('regulationStateChanged', (value, ))

    def _updateSafeNeeded(self, value=None):
        if value is None:
             value = self._chnSafeNeeded.getValue()

        if self._safeNeeded != value:
             self._safeNeeded = value
             self.emit('safeNeeded', (value, ))

    def _updatePoweredState(self, value=None):
        if value is None:
             value = self._chnPowered.getValue()

        if self._poweredState != value:
             self._poweredState = value
             self.emit('powerStateChanged', (value, ))

    def _updateToolOpen(self, value=None):
        #logging.info("PX1Cats1. _updateToolOpen Value: %s" % value)
        if value is None:
             #value = self._chnToolOpen.getValue()
             pass
        #self._toolState = value
        #if self._toolState != value:
        #     self._toolState = value
        #     self.emit('toolOpenChanged', (value, ))

    def _updateLidState(self, value=None):
        if value is None:
            value = self._chnLidState.getValue()

        self._lidState = value

        if value != self._lidState:
            self.emit('lidStateChanged', (not value, ))

    def _dryAndSoakNeeded(self, value=None):
        if value :
            homeOpened = self._chnhomeOpened.getValue()
            if not self._waitDeviceReady() and not homeOpened:
                self._cmdDrySoak()  
        

    def _updateAckSampleMemory(self, value=None):
        logging.info("PX1Cats1. UpdateAckSampleMemory: %s" % value)
        if value is None:
            value = self._chnIncoherentGonioSampleState.getValue()
            logging.info("PX1Cats2. UpdateAckSampleMemory: %s" % value)

        if value:
            self.emit('loadError', value)
        
	self._incoherentGonioSampleState = value


def main():
    # create the xanes object
    hwr_directory = os.environ["XML_FILES_PATH"]

    hwr = HardwareRepository.HardwareRepository(os.path.abspath(hwr_directory))
    hwr.connect()

    sc = hwr.getHardwareObject("/cryotong")
    print sc.getLoadedSample().getCoords()


if __name__ == '__main__':
    import sys
    import os

    print "Running PX1Cats standalone"
    hwrpath = os.environ.get('XML_FILES_PATH',None)

    if hwrpath is None:
        print "  -- you should first source the file mxcube.rc to set your environment variables"
        sys.exit(0)
    else:
        main()

