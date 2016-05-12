

from BeamlineSetup import BeamlineSetup

class PX1BeamlineSetup(BeamlineSetup):
    def __init__(self,*args):
        BeamlineSetup.__init__(self,*args)
        self._role_list.append("configuration")

