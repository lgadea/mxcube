# -*- coding: utf-8 -*-
from qt import *

from HardwareRepository import HardwareRepository
from HardwareRepository.BaseHardwareObjects import Equipment

import logging
import os
import time
import types
import gevent


class XfeSpectrumPX1(Equipment):

    def init(self):
        self.scanning = None
        self.moving = None

        self.storeSpectrumThread = None

        self.xfecollect = self.getObjectByRole("xfecollect")

        if self.isConnected():
            self.sConnected()

    def doSpectrum(self): #, ct, filename):
        self.xfecollect.measureSpectrum()
        self.spectrumCommandFinished(0)
        value = self.xfecollect.getValue()
        print value
        return value

    def isConnected(self):
        return True

    # Handler for spec connection
    def sConnected(self):
        self.emit('connected', ())
        curr = self.getSpectrumParams()

    # Handler for spec disconnection
    def sDisconnected(self):
        self.emit('disconnected', ())

    # Energy spectrum commands
    def canSpectrum(self):
        if not self.isConnected():
            return False
        return self.xfecollect is not None

    def startXfeSpectrum(self, ct, directory, prefix, session_id=None, blsample_id=None):
        self.spectrumInfo = {"sessionId": session_id}
        self.spectrumInfo["blSampleId"] = blsample_id
        
        #inintializing the collect object
        self.xfecollect.setup(ct, directory, prefix, sessionId = session_id, sampleId = blsample_id)
        
        if not os.path.isdir(directory):
            logging.getLogger().debug(
                "XRFSpectrum: creating directory %s" % directory)
            try:
                os.makedirs(directory)
            except OSError, diag:
                logging.getLogger().error(
                    "XRFSpectrum: error creating directory %s (%s)" % (directory, str(diag)))
                self.emit(
                    'spectrumStatusChanged', ("Error creating directory",))
                return False
        curr = self.getSpectrumParams()

        try:
            curr["escan_dir"] = directory
            curr["escan_prefix"] = prefix
        except TypeError:
            curr = {}
            curr["escan_dir"] = directory
            curr["escan_prefix"] = prefix

        a_dir = os.path.normpath(directory)
        print 'XfeSpectrumPX1.py a_dir', a_dir
        filename_pattern = os.path.join(
            directory, "%s_%s_%%02d" % (prefix, time.strftime("%d_%b_%Y")))
        aname_pattern = os.path.join(
            "%s/%s_%s_%%02d" % (a_dir, prefix, time.strftime("%d_%b_%Y")))

        filename_pattern = os.path.extsep.join((filename_pattern, "dat"))
        html_pattern = os.path.extsep.join((aname_pattern, "html"))
        aname_pattern = os.path.extsep.join((aname_pattern, "png"))
        filename = filename_pattern % 1
        aname = aname_pattern % 1
        htmlname = html_pattern % 1

        i = 2
        while os.path.isfile(filename):
            filename = filename_pattern % i
            aname = aname_pattern % i
            htmlname = html_pattern % i
            i = i + 1

        self.spectrumInfo["filename"] = filename
        #self.spectrumInfo["scanFileFullPath"] = filename
        self.spectrumInfo["jpegScanFileFullPath"] = aname
        self.spectrumInfo["exposureTime"] = ct
        self.spectrumInfo["annotatedPymcaXfeSpectrum"] = htmlname
        logging.getLogger().debug("XRFSpectrum: archive file is %s", aname)

        print "spawning task"
        gevent.spawn(self.reallyStartXfeSpectrum, ct, filename)

        return True

    def reallyStartXfeSpectrum(self, ct, filename):
        try:
            print "really starting"
            res = self.doSpectrum() #(ct, filename, wait=True)
        except:
            logging.getLogger().exception(
                'XfeSpectrum: problem calling spec macro')
            self.emit('spectrumStatusChanged', ("Error problem spec macro",))
        else:
            self.spectrumCommandFinished(res)

    def cancelXfeSpectrum(self, *args):
        if self.scanning:
            self.xfecollect.cancelXfeSpectrum()

    def spectrumCommandReady(self):
        if not self.scanning:
            self.emit('xfeSpectrumReady', (True,))

    def spectrumCommandNotReady(self):
        if not self.scanning:
            self.emit('xfeSpectrumReady', (False,))

    def spectrumCommandStarted(self, *args):
        self.spectrumInfo['startTime'] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.scanning = True
        self.emit('xfeSpectrumStarted', ())

    def spectrumCommandFailed(self, *args):
        self.spectrumInfo['endTime'] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.scanning = False
        self.storeXfeSpectrum()
        self.emit('xfeSpectrumFailed', ())

    def spectrumCommandAborted(self, *args):
        self.scanning = False
        self.emit('xfeSpectrumFailed', ())

    def spectrumCommandFinished(self, result):
        self.spectrumInfo['endTime'] = time.strftime("%Y-%m-%d %H:%M:%S")
        logging.getLogger().debug(
            "XRFSpectrum: XRF spectrum result is %s" % str(result))
        self.scanning = False

        if result == 0:
            #mcaData = self.getChannelObject('mca_data').getValue()
            mcaData = self.xfecollect.getValue()
            #mcaCalib = self.getChannelObject('calib_data').getValue()
            mcaCalib = self.xfecollect.getMcaCalib()
            #mcaConfig = self.getChannelObject('config_data').getValue()
            mcaConfig = self.xfecollect.getMcaConfig()
            self.spectrumInfo["beamTransmission"] = mcaConfig['att']
            self.spectrumInfo["energy"] = mcaConfig['energy']
            self.spectrumInfo["beamSizeHorizontal"] = float(mcaConfig['bsX'])
            self.spectrumInfo["beamSizeVertical"] = float(mcaConfig['bsY'])
            mcaConfig["file"] = self.spectrumInfo['filename']
            mcaConfig["legend"] = self.spectrumInfo[
                "annotatedPymcaXfeSpectrum"]

            # here move the png file
            pf = self.spectrumInfo["filename"].split(".")
            pngfile = os.path.extsep.join((pf[0], "png"))
            if os.path.isfile(pngfile) is True:
                try:
                    copy(pngfile, self.spectrumInfo["jpegScanFileFullPath"])
                except:
                    logging.getLogger().error(
                        "XRFSpectrum: cannot copy %s", pngfile)

            logging.getLogger().debug("finished %r", self.spectrumInfo)
            self.storeXfeSpectrum()
            self.emit('xfeSpectrumFinished', (mcaData, mcaCalib, mcaConfig))
        else:
            self.spectrumCommandFailed()

    def spectrumStatusChanged(self, status):
        self.emit('spectrumStatusChanged', (status,))

    def storeXfeSpectrum(self):
        print "storing xfespectrum" 
        self.xfecollect.saveData()
        #logging.getLogger().debug("db connection %r", self.dbConnection)
        #logging.getLogger().debug("spectrum info %r", self.spectrumInfo)
        #if self.dbConnection is None:
            #return
        #try:
            #session_id = int(self.spectrumInfo['sessionId'])
        #except:
            #return
        #blsampleid = self.spectrumInfo['blSampleId']
        #self.spectrumInfo.pop('blSampleId')
        #db_status = self.dbConnection.storeXfeSpectrum(self.spectrumInfo)

    def updateXfeSpectrum(self, spectrum_id, jpeg_spectrum_filename):
        pass

    def getSpectrumParams(self):
        try:
            self.curr = 'params' #self.xfeCollect.getSpectrumParameters() #energySpectrumArgs.getValue()
            return self.curr
        except NameError, diag:
            logging.getLogger().exception(
                'XRFSpectrum: error getting xrfspectrum parameters (%s)' % str(diag))
            self.emit('spectrumStatusChanged', (
                "Error getting xrfspectrum parameters",))
            return False

    def setSpectrumParams(self, pars):
        self.energySpectrumArgs.setValue(pars)

def main():
    # create the xanes object
    hwr_directory = os.environ["XML_FILES_PATH"]

    hwr = HardwareRepository.HardwareRepository(os.path.abspath(hwr_directory))
    hwr.connect()

    xfe = hwr.getHardwareObject("/xfespectrum")
    #xfe.xfecollect.setup(1, '/tmp', 'toto')
    xfe.startXfeSpectrum(1, '/tmp', 'toto', session_id=None, blsample_id=None)
    time.sleep(0.5)
    #xfe.xfecollect.measureSpectrum()
    #xfe.xfecollect.plotSpectrum()


if __name__ == '__main__':
    import sys
    import os


    print "Running XfeCollect procedure standalone"
    hwrpath = os.environ.get('XML_FILES_PATH',None)

    if hwrpath is None:
        print "  -- you should first source the file mxcube.rc to set your environment variables"
        sys.exit(0)
    else:
        main()

