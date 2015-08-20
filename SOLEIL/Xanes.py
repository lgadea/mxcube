#!/usr/bin/env python
# -*- coding: utf-8 -*-

from HardwareRepository import HardwareRepository
from HardwareRepository import BaseHardwareObjects

from xabs_lib import McMaster
import time
import threading
import logging
import matplotlib.pyplot as plt
import numpy
import commands
import pickle
import math
import os
import PyTango

class Xanes(BaseHardwareObjects.Device):

    cutoff = 4
    
    def setup(self, parent,
                 element,
                 edge,
                 directory='/tmp/testXanes',
                 prefix='x5',
                 session_id=None,
                 blsample_id=None,
                 nbSteps=100,
                 roiwidth=0.25,
                 beforeEdge=0.025,
                 afterEdge=0.075,
                 integrationTime=1,
                 peakingTime=2.5,
                 dynamicRange=20000, #47200
                 presettype=1,
                 bleSteps=1,
                 bleMode='c', # possibilities 'a' (ascending), 'd' (descending), 'c' (center)
                 undulatorOffset=0.,
                 filterNumber=7,
                 transmission=1.,
                 testFile='/927bis/ccd/gitRepos/Scans/pychooch/examples/SeFoil.raw',
                 transmission_min=0.001,
                 transmission_max=0.05,
                 epsilon=1e-4,
                 channelToeV=10.,
                 test=True,
                 save=True,
                 plot=True,
                 expert=False):

        # initialize logging
        self.parent = parent
        self.element = element
        self.edge = edge
        self.prefix = prefix
        self.nbSteps = nbSteps
        self.roiwidth = roiwidth
        self.beforeEdge = beforeEdge
        self.afterEdge = afterEdge
        self.integrationTime = integrationTime
        self.peakingTime = peakingTime
        self.dynamicRange = dynamicRange
        self.bleSteps = bleSteps
        self.bleMode = bleMode
        self.undulatorOffset = undulatorOffset
        self.presettype = presettype
        self.filterNumber = filterNumber
        self.transmissionValue = transmission
        self.directory = directory
        self.prefix = prefix
        self.session_id = session_id
        self.blsample_id = blsample_id
        self.getAbsEm()
        self.scanRange = float(afterEdge + beforeEdge)
        self.epsilon = epsilon
        
        # conversion between energy and channel
        self.channelToeV = channelToeV

        # state variables
        self.stt = None
        self.save = save
        self.plot = plot
        self.Stop = False
        self.Abort = False
        self.newPoint = False
        self.expert = expert

        #test specifics
        if self.mode == 'test':
            self.integrationTime = 0.01

    def init(self):
        # Initialize all the devices used throughout the collect

        self.stt = 'Init'

        self.raw = []
        self.e_edge = ''

        self.fluodet = self.getObjectByRole("fluodet")

        if self.mode == 'test': 
            self.integrationTime = 0.01
            self.test = True
            self.testFile = self.testdata
            return
        else:
            self.test = False

        from PyTango import DeviceProxy as dp

        self.safshut = self.getObjectByRole("safety_shutter")
        self.fastshut = self.getObjectByRole("fast_shutter")

        self.mono = dp(self.mono_dev)
        self.monoFine = dp(self.monoFine_dev)
        self.undulator = dp(self.undulator_dev)
        self.ble = dp(self.ble_dev)
        
        self.diodes = {}
        for diode in self['diodes']:
            name = diode.getProperty('diode') 
            devname = diode.getProperty('devname') 
            self.diodes[name] = dp(devname)

        self.normdiode = self.getProperty('normalization_diode') 

        if self.normdiode not in self.diodes:
            logging.error("Xanes.py - normalization_diode must be in .xml and should be one of the defined diodes") 
        logging.error("Xanes.py - self.diodes: %s" % self.diodes) 
 
        #self.counter = dp(self.counter_dev)
        self.pss = dp(self.pss_dev)
        
        self.Fp = dp(self.fp_dev)
        self.Ps_h = dp(self.ps_h_dev)
        self.Ps_v = dp(self.ps_v_dev)
        self.Const = dp(self.const_dev)

        self.Attenuator = dp(self.attenuator_dev)

    def getAbsEm(self):
        self.e_edge, self.roi_center = self.getEdgefromXabs(
            self.element, self.edge)

    def moveBeamlineEnergy(self, energy):
        if self.test: return
        self.ble.write_attribute('energy', energy)
        self.wait(self.ble)

    def prepare(self):
        if self.test is False:
            self.monoFine.On()

        self.getAbsEm()
        self.setROI()
        
        self.set_collect_phase()
        
        self.moveBeamlineEnergy(self.e_edge)
        
        self.optimizeTransmission()
        
        if not self.test:
            self.fluodet.set_preset( float(self.integrationTime) )
        
        self.fluodet.insert()
        time.sleep(4)
        
        self.results = {}
        self.results['timestamp'] = time.time()
        self.results['prefix'] = self.prefix
        self.results['element'] = self.element
        self.results['edge'] = self.edge
        self.results['peakingTime'] = self.peakingTime
        self.results['dynamicRange'] = self.dynamicRange
        self.results['integrationTime'] = self.integrationTime
        self.results['nbSteps'] = self.nbSteps
        
    def cleanUp(self):
        self.saveRaw()
        self.chooch()
        self.saveResults()

        if self.test: 
            return

        self.ble.write_attribute('energy', self.pk/1000.)
        self.fluodet.extract()
        self.safeTurnOff(self.monoFine)
        
    def closeSafetyShutter(self):
        logging.info('Closing the safety shutter')

        if self.test:
            return

        self.safshut.closeShutter()

    def safeOpenSafetyShutter(self):

        logging.info('Opening the safety shutter -- checking the hutch PSS state')

        if self.test: return

        if int(self.pss.prmObt) == 1:
            self.safshut.openShutter()
            while self.safshut.getShutterState() != 'opened' and self.stt not in ['STOP', 'ABORT']:
                time.sleep(0.1)

        logging.info(self.safshut.getShutterState())

    def openSafetyShutter(self):
        logging.info('Opening the safety shutter')

        if self.test:
            return

        while self.safshut.getShutterState() != 'opened' and self.stt not in ['STOP', 'ABORT']:
            logging.info(self.safshut.getShutterState())
            self.safeOpenSafetyShutter()
            time.sleep(0.1)

    def safeTurnOff(self, device):
        if self.test: return
        if device.state().name == 'STANDBY':
            device.Off()

    def wait(self, device):
        if self.test: return
        while device.state().name == 'MOVING':
            time.sleep(.1)

        while device.state().name == 'RUNNING':
            time.sleep(.1)

    # Should be adapted at each beamline
    def get_state(self):
        print "Returning global state. ADATP to your beamline"
        return 'Ready'
        
    # Should be adapted at each beamline
    def set_collect_phase(self, phase_name='DataCollection'):
        print "Setting gonio phase. STUB"
            
    # Should be adapted at each beamline
    def get_calibration(self):
        print "obtaining calibration. ADAPT to your beamline"
        A = -0.0161723871876
        C = 0.0
        B = 0.00993475667754
        return A, B, C
        
    def setROI(self):
        if self.test: return
        A, B, C = self.get_calibration()
        self.roi_center += A # A + B*self.roi_center + C*self.roi_center**2
        
        roi_debut = 1000.0 * \
            (self.roi_center - self.roiwidth / 2.0)  # values set in eV
        roi_fin   = 1000.0 * \
            (self.roi_center + self.roiwidth / 2.0)  # values set in eV
        channel_debut = int(roi_debut / (B*1e3)) # self.channelToeV)
        channel_fin = int(roi_fin / (B*1.e3)) #self.channelToeV)
        self.channel_fin = channel_fin
        self.channel_debut = channel_debut
        self.roi_debut = roi_debut
        self.roi_fin = roi_fin

        self.fluodet.set_roi(channel_debut, channel_fin)

    # You may want to adapt to your beamline in PX1Xanes
    def transmission(self, x=None):
        '''Get or set the transmission'''
        if self.test: return 0
        if x == None:
            return self.Fp.TrueTrans_FP

        truevalue = (2.0 - math.sqrt(4 - 0.04 * x)) / 0.02

        newGapFP_H = math.sqrt(
            (truevalue / 100.0) * self.Const.FP_Area_FWHM / self.Const.Ratio_FP_Gap)
        newGapFP_V = newGapFP_H * self.Const.Ratio_FP_Gap

        self.Ps_h.gap = newGapFP_H
        self.Ps_v.gap = newGapFP_V

    # You may want to adapt to your beamline in PX1Xanes
    def attenuation(self, x=None):
        '''Read or set the attenuation (for PX2)'''
        if self.test: return 0
        
        # PX2
        labels = ['00 None',
                  '01 Carbon 200um',
                  '02 Carbon 250um',
                  '03 Carbon 300um',
                  '04 Carbon 500um',
                  '05 Carbon 1mm',
                  '06 Carbon 2mm',
                  '07 Carbon 3mm',
                  '10 Ref Fe 5um',
                  '11 Ref Pt 5um']
        if x == None:
            status = self.Attenuator.Status()
            print 'status', status
            status = status[:status.index(':')]
            value = status
            return value
        NumToLabel = dict([(int(l.split()[0]), l) for l in labels])
        self.Attenuator.write_attribute(NumToLabel[x], True)
        self.wait(self.Attenuator)

    def getEdgefromXabs(self, element, edge):
        edge = edge.upper()
        roi_center = McMaster[element]['edgeEnergies'][edge + '-alpha']
        if edge == 'L':
            edge = 'L3'
        e_edge = McMaster[element]['edgeEnergies'][edge]

        return e_edge, roi_center

    def _pointsToStrings(self, points):
        return [str(e) for e in points] 
        
    def getObservationPoints(self):
        if self.test:
            print 'getObservationPoints in test mode'
            self.getTestData()
            print "self.testData['ens']", self.testData['ens']
            return self.testData['ens']
        points = numpy.arange(
            0., 1. + 1. / (self.nbSteps), 1. / (self.nbSteps))
        points *= self.scanRange
        points -= self.beforeEdge
        points += self.e_edge
        points = numpy.array([round(en, self.cutoff) for en in points])
        return points
    
    def getObservationPointsAsStrings(self):
        if self.test:
            return self.testData['ens_strings']
        points = self.getObservationPoints()
        return self._pointsToStrings(points)

    def getBLEPoints(self):
        s = int(self.bleSteps)
        if self.bleSteps == 1:
            return [self.e_edge + 0.01]
        if self.bleMode == 'c':
            points = numpy.arange(0., 1., 1. / (2*s))[1::2]
        elif self.bleMode == 'a':
            points = numpy.arange(0., 1. + 1./(2*s), 1./(2*s))[2::2]
        elif self.bleMode == 'd':
            points = numpy.arange(0., 1., 1. / (2*s))[0::2]
        points *= self.scanRange
        points -= self.beforeEdge
        points += self.e_edge
        return points

    def getBLEPointsAsStrings(self):
        points = self.getBLEPoints()
        return self._pointsToStrings(points)
        
    def getRawData(self):
        return self.raw

    def getElementEdge(self):
        return self.e_edge

    def getBleVsEn(self):
        print 'inside getBleVsEn'
        ens_floats = self.getObservationPoints()
        ble_floats = self.getBLEPoints()
        ens_strings = self.getObservationPointsAsStrings()
        ble_strings = self.getBLEPointsAsStrings()
        print 'ens_floats', ens_floats
        print 'ble_floats', ble_floats
        print 'ens_strings', ens_strings
        print 'ble_strings', ble_strings
        return dict([(en, ble_floats[list(abs(en - ble_floats)).index(min(list(abs(en - ble_floats))))]) for k, en in enumerate(ens_floats)])
        
    def getBleVsEnAsStrings(self):
        ens_floats = self.getObservationPoints()
        ble_floats = self.getBLEPoints()
        ens_strings = self.getObservationPointsAsStrings()
        ble_strings = self.getBLEPointsAsStrings()
        print 'ens_floats', ens_floats
        print 'ble_floats', ble_floats
        print 'ens_strings', ens_strings
        print 'ble_strings', ble_strings
        return dict([(ens_strings[k], ble_floats[list(abs(en - ble_floats)).index(min(list(abs(en - ble_floats))))]) for k, en in enumerate(ens_floats)])
        
    def setMono(self, energy):
        logging.info('setMono: energy %s' % energy)
        if self.test: return
        self.mono.write_attribute('energy', float(energy))
        self.wait(self.mono)

    def setBLE(self, energy):
        logging.info('setBLE')
        if self.test: return                                   
        if abs(self.ble.read_attribute('energy').w_value - self.BleVsEnStrings[energy]) > 0.001:
            print 'setting undulator energy', energy
            print 'self.BleVsEn[energy]', self.BleVsEnStrings[energy]
            self.ble.write_attribute('energy', self.BleVsEnStrings[energy])
            self.wait(self.ble)
            if self.undulatorOffset != 0:
                self.undulator.gap += self.undulatorOffset
                self.wait(self.undulator)
            
    def setObservationParameters(self, energy):
        logging.info('setObservationParameters: energy %s' % energy)
        self.setBLE(energy)
        self.setMono(energy)
        
    
    def stop(self):
        logging.info('Stopping the scan')
        self.Stop = True
        self.stt = 'Stop'
    
    def abort(self):
        logging.info('Aborting the scan')
        self.stop()
        self.Abort = True
        self.stt = 'Abort'
        if self.test: return

        self.closeFastShutter()
    
    def openFastShutter(self):
        self.fastshut.openShutter()

    def closeFastShutter(self):
        self.fastshut.closeShutter()

    def start(self):
        logging.info('scan thread')
        self.scanThread = threading.Thread(target=self.scan)
        #self.scanThread.daemon = True
        self.scanThread.start()
    
    def optimizeTransmission(self):
        logging.info('Optmizing transmission')
        if self.test: return
    
        # REVISE / PX2
        import XfeCollect
        xfe = XfeCollect.XfeCollect()
        xfe.optimizeTransmission(self.element, self.edge)
        
    def scan(self):
        logging.info('scan started')
        if self.plot:
            plt.ion()
            self.plotInit()
        self.stt = 'Scanning'
        self.prepare()

        self.ens = self.getObservationPoints()
        self.bles = self.getBLEPoints()
        self.ens_strings = self.getObservationPointsAsStrings()
        self.bles_strings = self.getBLEPointsAsStrings() 
        print 'ens'
        print self.ens
        print 'bles'
        print self.bles
        print 'ens strings'
        print self.ens_strings
        print 'bles strings'
        print self.bles_strings
        
        self.BleVsEn = self.getBleVsEn()
        self.BleVsEnStrings = self.getBleVsEnAsStrings()
        print 'ble vs en'
        print self.BleVsEn
        
        print 'ble vs en strings'
        print self.BleVsEnStrings
        
        self.safeOpenSafetyShutter()
        
        self.results['transmission'] = self.transmission()
        self.results['attenuation'] = self.filterNumber
        self.results['points'] = self.ens_strings
        self.results['ens'] = self.ens
        self.results['bles'] = self.bles
        self.results['ens_strings'] = self.ens_strings
        self.results['bles_strings'] = self.bles_strings
        self.results['BleVsEn'] = self.BleVsEn
        self.results['BleVsEnStrings'] = self.BleVsEnStrings
        self.results['observations'] = {}
        self.results['roiwidth'] = self.roiwidth
        self.results['roi_center'] = self.roi_center
        #self.results['roi_debut'] = self.roi_debut
        #self.results['roi_fin'] = self.roi_fin
        self.runningScan = {'ens': [], 'points': []}
        self.results['raw'] = self.runningScan
        
        if self.test is True:
            print 'self.testData.keys()', self.testData.keys()
        for en in self.ens_strings:
            #logging.info('measuring at energy %s (%s of %s)' % (en, x(en), len(ens)))
            if self.stt == 'Stop':
                break
            self.setObservationParameters(en)
            self.measure()
            self.takePoint(en)
            self.updateRunningScan(en)
            if self.plot:
                self.newPoint = True
                self.plotNewPoint()
            
        #self.closeSafetyShutter()
        self.results['duration'] = time.time() - self.results['timestamp']
        self.cleanUp()
        if self.plot:
            plt.ioff()
        self.stt = 'Finished'
        
    def measure(self):
        # measurement
        if self.test:
            time.sleep(self.integrationTime)
            return

        self.openFastShutter()

        self.fluodet.start()
        self.fluodet.wait()

        self.closeFastShutter()
        
    def takePoint(self, en):
        logging.info('takePoint %s' % en)
        # readout
        if self.test:
            self.results['observations'][en] = {'point': self.testData[en]}
            if self.parent is not None:
                self.parent.newPoint(float(en), float(self.results['observations'][en]['point']))
            return

        # measurement
        results = {'roiCounts': self.fluodet.get_roi_counts(),
                   'inputCountRate00': self.fluodet.getICR(),
                   'outputCountRate00': self.fluodet.getOCR(),
                   'eventsInRun': self.fluodet.get_events(),
                   'spectrum': self.fluodet.get_data() }

        for diode in self.diodes:
            dev = self.diodes[diode]
            results[diode] = dev.intensity

        self.results['observations'][en] = results

        uptoendroi = self.results['observations'][en]['spectrum'][50: self.channel_fin]
        uptostartroi = self.results['observations'][en]['spectrum'][50: self.channel_debut]
        self.results['observations'][en]['uptoendroi'] = sum(uptoendroi)
        self.results['observations'][en]['uptostartroi'] = sum(uptostartroi)

        #logging.info('self.results[\'observations\'][en] %s' % self.results['observations'][en])

        self.results['observations'][en]['point'] = float(self.results['observations'][en]['roiCounts']) / self.results['observations'][en][ self.normdiode ]

        #self.results['observations'][en]['point'] = float(self.results['observations'][en]['roiCounts']) / self.results['observations'][en]['eventsInRun']
        #self.results['observations'][en]['point'] = float(self.results['observations'][en]['roiCounts']) / self.results['observations'][en]['uptostartroi']

        self.parent.newPoint(float(en), float(self.results['observations'][en]['point']))
            
    def updateRunningScan(self, en):
        self.runningScan['ens'].append(float(en))
        self.runningScan['points'].append(self.results['observations'][en]['point'])
        

    def setMiddleTransmission(self):
        self.transmission((self.transmission_max - self.transmission_min) / 2.)


    def saveDat(self):

        # PX2

        logging.info('saveDat')
        f = open('{prefix}_{element}_{edge}.dat'.format(**self.results), 'w')
        f.write('# EScan {date}\n'.format(**{'date': time.ctime(self.results['timestamp'])}))
        f.write('# Energy Motor %s\n' % self.mono_dev)
        f.write('# Normalized value\n')
        f.write('# roi counts\n')
        f.write('# normalization diode: %s\n' % self.normdiode)
        f.write(
            '# Counts on the fluorescence detector: all channels\n')
        f.write(
            '# Counts on the fluorescence detector: channels up to end of ROI\n')
        for en in self.results['ens_strings']:
            normalized_intensity=self.results['observations'][en][
                'roiCounts'] / self.results['observations'][en][ self.normdiode ]
            f.write(
                ' {en} {normalized_intensity} {roiCounts} {normdiode} {eventsInRun}\n'.format(**{'en': en,
                                                                                              'normalized_intensity': normalized_intensity,
                                                                                              'roiCounts': self.results['observations'][en]['roiCounts'],
                                                                                              'normdiode': self.results['observations'][en][self.normdiode],
                                                                                              'eventsInRun': self.results['observations'][en]['eventsInRun']}))
        f.write('# Duration: {duration}\n'.format(**self.results))
        f.close()

    def saveRaw(self):

        # PX2

        logging.info('saveRaw')
        #logging.info('self.results %s' % self.results)
        logging.info('raw filename %s' % os.path.join(self.directory, '{prefix}_{element}_{edge}.raw'.format(**self.results)))
        f = open(os.path.join(self.directory, '{prefix}_{element}_{edge}.raw'.format(**self.results)), 'w')
        f.write('{beamline}, Escan, {date}\n'.format(**{'beamline': self.beamlinename, 'date': time.ctime(self.results['timestamp'])}))
        f.write('{nbPoints}\n'.format(**{'nbPoints': len(self.results['points'])}))
        self.raw = []
        for en in self.ens_strings:
            en_float = float(en)
            x = en_float < 1e3 and en_float*1e3 or en_float
            point = self.results['observations'][en]['point']
            f.write('{en} {point}\n'.format(**{'en': x, 'point': point}))
            self.raw.append((x, point))
        f.close()
        time.sleep(3)

    def saveResults(self):
        logging.info('saveResults')
        f = open(os.path.join(self.directory, '{prefix}_{element}_{edge}_results.pck'.format(**self.results)), 'w')
        #f = open('{prefix}_{element}_{edge}.pck'.format(**self.results), 'w')
        pickle.dump(self.results, f)
        f.close()

    def parse_chooch_output(self, output):
        logging.info('parse_chooch_output')
        table = output[output.find('Table of results'):]
        tabl = table.split('\n')
        tab = numpy.array([ line.split('|') for line in tabl if line and line[0] == '|'])
        print 'tab', tab
        self.pk = float(tab[1][2])
        self.fppPeak = float(tab[1][3])
        self.fpPeak = float(tab[1][4])
        self.ip = float(tab[2][2])
        self.fppInfl = float(tab[2][3])
        self.fpInfl = float(tab[2][4])
        self.efs = self.getEfs()
        return {'pk': self.pk, 'fppPeak': self.fppPeak, 'fpPeak': self.fpPeak, 'ip': self.ip, 'fppInfl': self.fppInfl, 'fpInfl': self.fpInfl, 'efs': self.efs}
    
    def chooch(self):
        logging.info('chooch')
        chooch_parameters = {'element': self.element, 
                             'edge': self.edge,
                             'raw_file': os.path.join(self.directory, '{prefix}_{element}_{edge}.raw'.format(**self.results)),
                             'output_ps': os.path.join(self.directory, '{prefix}_{element}_{edge}.ps'.format(**self.results)),
                             'output_efs':os.path.join(self.directory, '{prefix}_{element}_{edge}.efs'.format(**self.results))}
        chooch_cmd = 'chooch -p {output_ps} -o {output_efs} -e {element} -a {edge} {raw_file}'.format(**chooch_parameters)
        logging.info('chooch command %s' % chooch_cmd)
        
        chooch_output = commands.getoutput(chooch_cmd)
        self.results['chooch_output'] = chooch_output
        print 'chooch_output', chooch_output
        chooch_results = self.parse_chooch_output(chooch_output)
        self.results['chooch_results'] = chooch_results
        
    def getEfs(self):
        filename = os.path.join(self.directory, '{prefix}_{element}_{edge}.efs'.format(**self.results))
        f = open(filename)
        data = f.read().split('\n')
        efs = numpy.array([numpy.array(map(float, line.split())) for line in data if len(line.split()) == 3])
        return efs
        
    def suivi(self):
        self.plotThread = threading.Thread(target=self.plot)
        self.plotThread.daemon = True
        self.plotThread.start()
        
    def plotInit(self):
        self.fig = plt.figure()
        self.ax = self.fig.add_subplot(1, 1, 1)
        self.ax.set_title('Energy scan {element}, {edge}'.format(**{'element': self.element, 'edge': self.edge}))
        self.ax.set_xlabel('Energy [eV]')
        self.ax.set_ylabel('Normalized counts [a.u.]')
    
    def plotNewPoint(self):
        self.ax.plot(self.runningScan['ens'], self.runningScan['points'], 'bo-')
        plt.draw()
        
    def getRunningScan(self):
        ens = []
        points = []
        for en in self.results['ens']:
            en = round(en, self.cutoff)
            if self.results.has_key(en):
                ens.append(en)
                normalized_intensity = self.results['observations'][en]['roiCounts'] / self.results['observations'][en][ self.normdiode ]
                points.append(normalized_intensity)
        return ens, points
    
    def getTestData(self):
        logging.info('getTestData')
        self.testData = {}
        logging.info('self.testFile %s' % self.testFile)
        f = open(self.testFile)
        fr = f.read()
        lines = fr.split('\n')
        print 'lines', lines
        try:
            nPoints = int(lines[1])
        except ValueError:
            nPoints = len(lines) - 2
        ens = []
        ens_strings = []
        points = []
        for l in lines[2: nPoints + 2]:
            ls = l.split()
            if len(ls) == 2:
                en_string = ls[0].strip() #.strip() #round(float(ls[0]), self.cutoff)
                en_float = float(en_string)
                point = float(ls[1])
                ens.append(en_float)
                ens_strings.append(en_string)
                self.testData[en_float] = point
                self.testData[en_string] = point

        self.testData['ens'] = numpy.array(ens)
        self.testData['ens_strings'] = ens_strings #self._pointsToStrings(ens)
        logging.info('self.testData %s' % self.testData)
        
def main():
    #scan = xanes('Se', 'K', prefix='SeMet', testFile='/927bis/ccd/gitRepos/Scans/pychooch/examples/SeMet.raw')
    #points = scan.getObservationPoints()
    #print 'len(points)', len(points)
    #print points

    #print scan.element
    #print scan.e_edge
    
    #scan.scan()
    
    usage = '''Program for energy scans
    
    ./Xanes.py -e <element> -s <edge> <options>
    
    '''
    
    import optparse
    
    parser = optparse.OptionParser(usage=usage)
        
    parser.add_option('-e', '--element', type=str, help='Specify the element')
    parser.add_option('-s', '--edge', type=str, help='Specify the edge')
    parser.add_option('-n', '--steps', type=int, default=80, help='number of scan points (default=%default)')
    parser.add_option('-u', '--undulator', type=int, default=1, help='Number of optimal undulator positions during the scan (default=%default)')
    parser.add_option('-o', '--undulatorOffset', type=float, default=0, help='Offset to the undulator gap (default=%default)')
    parser.add_option('-r', '--roiWidth', type=float, default=0.300, help='ROI width in keV (default=%default)')
    parser.add_option('-b', '--beforeEdge', type=float, default=0.030, help='Start scan this much (in keV) before the theoretical edge (default=%default)')
    parser.add_option('-a', '--afterEdge', type=float, default=0.050, help='Start scan this much (in keV) before the theoretical edge (default=%default)')
    parser.add_option('-g', '--dynamicRange', type=int, default=20000, help='Set the dynamic range (in eV) of the fluorescence detector (default=%default)')
    parser.add_option('-i', '--integrationTime', type=float, default=0.64, help='Set the integration time in seconds (default=%default)')
    parser.add_option('-p', '--peakingTime', type=float, default=2.5, help='Set the integration time in microseconds (default=%default)')
    parser.add_option('-t', '--transmission', default=None, help='Set the transmission. If not set, the optimal transmission search routine will try to determine the optimal value (default=%default)')
    parser.add_option('-f', '--filter', type=int, default=7, help='Set the attenuation filter (default=%default)')
    parser.add_option('-d', '--directory', type='str', default='/tmp/testXanes', help='Directory to store the results (default=%default)')
    
    options, args = parser.parse_args()
    
    print 'options', options
    print 'args', args
    
    # create the xanes object
    hwr_directory = os.environ["XML_FILES_PATH"]

    hwr = HardwareRepository.HardwareRepository(os.path.abspath(hwr_directory))
    hwr.connect()

    xanes = hwr.getHardwareObject("/xanes")

    xanes.setup(None, options.element,
              options.edge,
              integrationTime = 0.1,
              undulatorOffset = options.undulatorOffset,
              bleSteps = options.undulator)
              
    xanes.scan()
              
    #scan.suivi()
    xanes.saveRaw()
    xanes.saveResults()
    xanes.chooch()

if __name__ == "__main__":

    import sys
    import os

    print "Running Xanes procedure standalone" 
    hwrpath = os.environ.get('XML_FILES_PATH',None)

    if hwrpath is None:
        print "  -- you should first source the file mxcube.rc to set your environment variables"
        sys.exit(0)
    else:
        main()
