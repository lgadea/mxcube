#!/usr/bin/env python
# -*- coding: utf-8 -*-

from HardwareRepository import HardwareRepository
from HardwareRepository import BaseHardwareObjects

import logging
import time
import numpy
import os
import math

from PyTango import DeviceProxy
from PyTango import AttributeProxy

class Ketek(BaseHardwareObjects.Device):

    def init(self):

        self.devname = self.getProperty("tangoname")
        self.dev = DeviceProxy(self.devname)

        self.num_channels = 2048

         
        try:
            self.presettype = int(self.getProperty("presettype") )
        except:
            self.presettype = None

        try:
            self.peakingtime = float(self.getProperty("peakingtime") )
        except:
            self.peakingtime = None

        self.default_channel = self.getProperty("default_channel")

        self.channo = self.default_channel

        self.calib_a = float(self.getProperty('calib_a'))
        self.calib_b = float(self.getProperty('calib_b'))
        self.calib_c = float(self.getProperty('calib_c'))

        try:
            self.insertcommand = self.getCommandObject("insert")
            self.extractcommand = self.getCommandObject("extract")
        except:
            self.insertcommand = None
            self.extractcommand = None

        try:
            self.commandchannel = self.getChannelObject("command")
        except:
            self.commandchannel = None

        try:
            commandlogic = self.getProperty("commandlogic")
            logging.error("Ketek. commandlogic is %s" % commandlogic)
            if commandlogic == 'inverted':
                self.commandlogic = 'inverted'
            else:
                self.commandlogic = 'direct'
        except:
            self.commandlogic = 'direct'

        if self.commandchannel is not None:
            logging.info("Ketek. insert/command using channel command. logic is %s" % self.commandlogic)

        self.init_dev()

    def init_dev(self):
        if self.presettype is not None:
            self.dev.write_attribute('presettype', self.presettype )

        if self.peakingtime is not None:
            self.dev.write_attribute('peakingtime', self.peakingtime )

    def select_channel(self, channo):
        self.channo = channo

    def getICR(self):
        attrname = "inputCountRate%02d" % int(self.channo)
        countrate = self.dev.read_attribute(attrname).value
        return countrate

    def getOCR(self):
        attrname = "outputCountRate%02d" % int(self.channo)
        countrate = self.dev.read_attribute(attrname).value
        return countrate

    def getRealTime(self):
        attrname = "realTime%02d" % int(self.channo)
        time = self.dev.read_attribute(attrname).value
        return time

    def get_input_countrate(self):
        attrname = "inputCountRate%02d" % int(self.channo)
        countrate = self.dev.read_attribute(attrname).value
        return countrate

    def get_calibration(self):
        return (self.calib_a, self.calib_b, self.calib_c)

    def set_preset(self, exptime):
        self.dev.write_attribute('presetValue', float(exptime) )

    def set_roi(self,chbeg=0,chend=2048):
        self.dev.SetROIs( numpy.array((chbeg, chend)) )

    def set_roi_kev(self,ebeg,eend):
        ebeg += self.calib_a
        eend += self.calib_a
        chbeg = int(ebeg / (self.calib_b)) 
        chend = int(eend / (self.calib_b)) 
        self.dev.SetROIs( numpy.array((chbeg, chend)) )

    def start(self):
        self.dev.Start()

    def expose(self, exptime, wait=True):

        self.set_preset(exptime)
        self.start()
        if wait:
            self.wait()

    def wait(self):
        while self.dev.state().name != 'STANDBY':
            time.sleep(0.1)

    def get_spectrum(self):
        return self.get_xvals(), self.get_data()

    def get_spectrum_calibrated(self):
        return self.get_calibrated_energies(), self.get_data()

    def abort(self):
        self.dev.Abort()
        
    def get_state(self):
        return self.dev.State()

    def get_xvals(self):
        start, end   = 0, self.num_channels
        step = 1
        return numpy.arange(start, end, step)

    def get_calibrated_energies(self):
        energies = self.get_xvals()
        energies = self.calib_a + self.calib_b*energies + self.calib_c*energies**2
        return energies
        
    def get_data(self):
        attrname = "channel%02d" % int(self.channo)
        data = self.dev.read_attribute(attrname).value
        return data
        
    def get_roi_counts(self):
        attrname = "roi%02d_01" % int(self.channo)
        counts = self.dev.read_attribute(attrname).value
        return counts

    def get_events(self):
        attrname = "eventsInRun%02d" % int(self.channo)
        events = self.dev.read_attribute(attrname).value
        return events

    def insert(self):
        if self.insertcommand is not None:
            self.insertcommand()
        elif self.commandchannel is not None:
            logging.error("Ketek.  Inserted using command channel. logic is %s" % self.commandlogic)
            if self.commandlogic != 'inverted':
                self.commandchannel.setValue(1)
            else:
                self.commandchannel.setValue(0)
        else:
            logging.error("Ketek.  No command available for insert / extract ")

    def extract(self):
        if self.extractcommand is not None:
            self.extractcommand()
        elif self.commandchannel is not None:
            if self.commandlogic != 'inverted':
                self.commandchannel.setValue(0)
            else:
                self.commandchannel.setValue(1)
        else:
            logging.error("Ketek.  No command available for insert / extract ")

def main():
    # create the ketek object
    hwr_directory = os.environ["XML_FILES_PATH"]

    hwr = HardwareRepository.HardwareRepository(os.path.abspath(hwr_directory))
    hwr.connect()

    ketek = hwr.getHardwareObject("/ketek")
    chans = ketek.get_calibrated_energies()
    nbch = len(chans)
    print nbch
    print chans[0:50]
    print chans[nbch-50:]
      
    return

    ketek.set_roi(1, 2048)
    ketek.expose(3)
    ketek.wait()

    print ketek.get_spectrum() 

if __name__ == '__main__':
    import sys
    import os

    print "Running Ketek tests "

    hwrpath = os.environ.get('XML_FILES_PATH',None)

    if hwrpath is None:
        print "  -- you should first source the file mxcube.rc to set your environment variables"
        sys.exit(0)
    else:
        main()

