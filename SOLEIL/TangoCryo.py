
from HardwareRepository import BaseHardwareObjects
import logging

class TangoCryo(BaseHardwareObjects.Device):

    def __init__(self, name):
        BaseHardwareObjects.Device.__init__(self, name)

    def init(self):

        try:
            tempchan = self.getChannelObject('temperature')
            tempchan.connectSignal('update', self.temperatureChanged)
            statuschan = self.getChannelObject('state')
            statuschan.connectSignal('update', self.stateChanged)
        except KeyError:
            logging.getLogger().warning('%s: cannot connect to channel', self.name())


    def temperatureChanged(self, value):
        #
        # emit signal
        #
        #self.emit('valueChange', value)
        self.emit('temperatureChanged', value)


    def stateChanged(self, value):
        #
        # emit signal
        #
        #self.emit('valueChange', value)
        self.emit('cryoStatusChanged', value)
