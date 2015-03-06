
from HardwareRepository import HardwareRepository
import logging
import os

import Session

class SOLEILSession(Session.Session):

    def __init__(self, *args, **kwargs):
        Session.Session.__init__(self,*args, **kwargs)
        self.username = ''
        self.gid = ''
        self.uid = ''
        self.projuser = ''

    def path_to_ispyb(self, path):
        ispyb_base = self["file_info"].getProperty('ispyb_base_directory') % {'projuser': self.projuser}
        path = path.replace( self["file_info"].getProperty('base_directory'), ispyb_base )
        return path

    def set_user_info(self, username, user_id, group_id, projuser=None ):
        logging.debug("SESSION - User %s logged in. gid=%s / uid=%s " % (username,group_id,user_id))
        self.username = username 
        self.group_id = group_id 
        self.user_id = user_id 
        self.projuser = projuser

    def get_rawdata_directory(self, directory=None):
        if directory is None:
            thedir = self.get_base_data_directory()
        else:
            thedir = directory

        if 'RAW_DATA' not in thedir:
            thedir = os.path.join(thedir, 'ARCHIVE')

        return thedir

    def get_archive_directory(self, directory=None):
        if directory is None:
            thedir = self.get_base_data_directory()
        else:
            thedir = directory

        if 'RAW_DATA' in thedir:
            thedir = thedir.replace('RAW_DATA','ARCHIVE')
        else:
            thedir = os.path.join(thedir, 'ARCHIVE')

        return thedir

    def get_ruche_info(self, path):

        if self.is_inhouse( self.username ):
           usertype = 'soleil'
        else:
           usertype = 'users'

        basedir = os.path.dirname( path )
        ruchepath = basedir.replace( self["file_info"].getProperty('base_directory'), '' )
        if ruchepath and ruchepath[0] == os.path.sep:
            ruchepath = ruchepath[1:]
                      
        infostr = "%s %s %s %s %s %s\n" % (usertype, self.username, self.user_id,
                                        self.group_id, basedir,ruchepath)
        return infostr

def test():
    import os
    hwr_directory = os.environ["XML_FILES_PATH"]

    hwr = HardwareRepository.HardwareRepository(os.path.abspath(hwr_directory))
    hwr.connect()

    sess = hwr.getHardwareObject("/session")

    sess.set_user_info('mx2014', '143301', '14330', '20100023')

    path = "/data1-1/test/visitor/mx2014/px1/20150120/ARCHIVE/mx2014/mx2014_2_4.snapshot.jpeg"
    ispyb_path = sess.path_to_ispyb(path)
 
    print path
    print "  will become "
    print ispyb_path
 
    #print sess.get_ruche_info(path)

if __name__ == '__main__':
    test()
