#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Created on Fri Nov 27 10:06:42 2015

@author: com-proxima2a
"""
#==============================================================================
# Somes Utils used in PROXIMA1 ;
#   - merge n cbf in one cbf file
#==============================================================================


import re
import os
import sys
import subprocess
import logging
import time


endHeader = b"\x0c\x1a\x04\xd5"
BINARAY_SECTION = b"--CIF-BINARY-FORMAT-SECTION--"
CIF_BINARY_BLOCK_KEY = "_array_data.data"
BLOCK_DATA = "_array_data.header_contents"

def fillHeader(instream,filenameD,start,increment,expotime):
    #param = [start,increment]
    bufFile = None    
    
    #l = 0
    #firstline = ''
    #templist = []
    strlist = readHeader(instream,start,increment,expotime)
    with open(filenameD, "r") as in_file:
        bufFile = in_file.readlines()
    
    with open(filenameD, "r+") as out_file:
        flag = 0
        for line in bufFile:
            if '###' in line :
                line = '###CBF: Files generated from 10 image to XDS analysis \n'               
            if 'data_' in line :
                line = 'data_'+os.path.basename(filenameD)+' \n'
            if ";" in line and flag == 0:
                line = line + strlist
                flag += 1
            out_file.write(line)
                
                
def run_job(executable, arguments = [], stdin = [], working_directory = None):
    '''Run a program with some command-line arguments and some input,
    then return the standard output when it is finished.'''
    
    if working_directory is None:
        working_directory = os.getcwd()

    command_line = '%s' % executable
    for arg in arguments:
        command_line += ' "%s"' % arg
    try:
        popen = subprocess.Popen(command_line,
                             bufsize = 1,
                             stdin = subprocess.PIPE,
                             stdout = subprocess.PIPE,
                             stderr = subprocess.STDOUT,
                             cwd = working_directory,
                             universal_newlines = True,
                             shell = True,
                             env = os.environ)
    except :
        logging.info( "ERROR in run_job process during merge file")                         
    for record in stdin:
        popen.stdin.write('%s\n' % record)

    popen.stdin.close()

    output = []

    while True:
        record = popen.stdout.readline()
        if not record:
            break

        output.append(record)

    return output

def run_merge2cbf1(input_template, image_range, output_template,dirPath):
    MERGE2CBF_file = os.path.join(dirPath, 'MERGE2CBF.INP')
    
    mergeFile = open(MERGE2CBF_file, 'w')
    mergeFile.write(
        'NAME_TEMPLATE_OF_DATA_FRAMES=%s\n' % input_template +
        'DATA_RANGE= %d %d\n' % image_range +
        'NAME_TEMPLATE_OF_OUTPUT_FRAMES=%s\n' % output_template +
        'NUMBER_OF_DATA_FRAMES_COVERED_BY_EACH_OUTPUT_FRAME=%d\n' %
        image_range[1])
    mergeFile.close()
    output = run_job('merge2cbf',working_directory=dirPath)
    logging.info(''.join(output))

 #WRONGGGGGGGGGGGGGGGg  
#==============================================================================
# def run_merge2cbf(input_template, image_range, output_template,dirPath):
#     MERGE2CBF_file = os.path.join(dirPath, 'MERGE2CBF.INP')
#     open(MERGE2CBF_file, 'w').write(
#         'NAME_TEMPLATE_OF_DATA_FRAMES=%s\n' % input_template +
#         'DATA_RANGE= %d %d\n' % image_range +
#         'NAME_TEMPLATE_OF_OUTPUT_FRAMES=%s\n' % output_template +
#         'NUMBER_OF_DATA_FRAMES_COVERED_BY_EACH_OUTPUT_FRAME=%d\n' %
#         image_range[1])
#     try :
#         subprocess.call('merge2cbf')
#     except:
#         print 'MERGE 2  ###### ', sys.exc_info()[0]
#==============================================================================

#==============================================================================
# def readHeader2(instream,start,angle,expotime):
#     data = ['# Exposure_time','# Start_angle', '# Angle_increment']
#     with open(instream , 'r') as f:
#         headerLine = f.read()
#         hs = headerLine.find(BLOCK_DATA)
#         he = headerLine.find(CIF_BINARY_BLOCK_KEY)
#         
#         headerIn = headerLine[hs:he]
#         lines = headerIn.split(b"\n")
#         #modif = lines[20]
#         for line in lines :
#             if data[0] in line :
#                 line = re.sub('\d','?',line)
#                 line = line.replace('?.???????','%08.7f')
#                 line = line % float(expotime)
#             if data[1] in line :
#                 line = re.sub('\d','?',line)
#                 ncar = '?'*(line.count('?')-5)+'?.????'
#                 line = line.replace(ncar,'%05.4f')
#                 line = line % float(start)
#             if data[2] in line :
#                 line = re.sub('\d','?',line)
#                 ncar = '?'*(line.count('?')-5)+'?.????'
#                 line = line.replace(ncar,'%05.4f')
#                 line = line % float(start)
#         newHeader = lines[2:-2]
#         strlist = "\n".join(newHeader)
#         return strlist
#         
#==============================================================================

def readHeader(instream,start,angle,expotime):
    with open(instream , 'r') as f:
        headerLine = f.read()
        hs = headerLine.find(BLOCK_DATA)
        he = headerLine.find(CIF_BINARY_BLOCK_KEY)
        
        headerIn = headerLine[hs:he]
        lines = headerIn.split(b"\n")
        lines[6] = re.sub('\d','?',lines[6])
        lines[20] = re.sub('\d','?',lines[20])
        lines[21] = re.sub('\d','?',lines[21])
        ncar = '?'*(lines[20].count('?')-5)+'?.????'
        lines[20] = lines[20].replace(ncar,'%05.4f')
        lines[21] = lines[21].replace(ncar,'%05.4f')
        lines[6] = lines[6].replace('?.???????','%08.7f')
        lines[6] = lines[6] % float(expotime)
        lines[20] = lines[20] % float(start)
        lines[21] = lines[21] % float(angle)
        newHeader = lines[2:-2]
        strlist = "\n".join(newHeader)
        return strlist

def merge(firstFile, templateImage, dirPath, startAngle, nOscillation, expotime):
    '''Merge the cbf images of N files with random names.'''
    logging.info(" XXXXXXXXXXXXXXXXXXXXXXXx    IMPORT MERGE images ")
    logging.info("file s is %s " % str(firstFile))
    #output_template = os.path.join(dirPath,'summed_????.cbf')
    output_template = 'summed_????.cbf'
    templateIn = firstFile[:-6]+"??.cbf"
    #templateIn = os.path.join(dirPath,(firstFile[:-6]+"??.cbf"))#ref-wdg-mx20100023_1_00??.cbf'
    logging.info("test template filenames %s" % str(templateIn))
    #_output_template = output_template [:-6]+"??.cbf"#'ref-mx20100023_1_00??.cbf'
    #logging.info("test template filenames %s" % str(_output_template))
    finalName = os.path.join(dirPath,templateImage)
    wait_all_image_compil_on_disk(firstFile[:-6], dirPath, timeout=20.0)
    try:
        logging.info(" XXXXX MERGE images ")
        run_merge2cbf1(os.path.join(os.getcwd(), templateIn) ,
                      (1, 10), output_template,dirPath)
        os.rename(os.path.join(dirPath,'summed_0001.cbf'), finalName)
        #finalName ='summx20100023_1_0001.cbf'
        #firstFileCbf = "r"
        #readHeader('ref-mx20100023_1_0001.cbf',90,1,0.015)
        #fillHeader(filenames[0],finalName,start=startAngle,oscillation=nOscillation,expotime=expotime)        
        fillHeader(firstFile ,finalName ,start=startAngle ,oscillation=nOscillation ,expotime=expotime)
    except :
        logging.error(" No merge cbf images ")
    #return
    
def countFilewithPattern(pattern,dirPath):
    return len([f for f in os.listdir(dirPath) if f.startswith(pattern) and os.path.isfile(os.path.join(dirPath, f))])
    
def wait_all_image_compil_on_disk(pattern,dirPath, timeout=20.0):
        start_wait = time.time()
        while countFilewithPattern(pattern,dirPath) <= 10:
            #logging.info("Waiting for image %s to appear on disk. Not there yet." % filename)
            if time.time() - start_wait > timeout:
               logging.info("Giving up waiting for image. Timeout")
               break
            time.sleep(0.1)

def main():

    
    pattern = 'summx20100023_1_00??.cbf'
    pattern2 = 'summx20100023_1_0001.cbf'
        
    #merge(sys.argv[2:], 'summed_????.cbf')
    merge(sys.argv[1:], pattern)
    temp = 'ref-mx20100023_1_0001.cbf'
    #insertline(pattern2)    
    #readHeader(temp,pattern2)
    #print 'Merged %d images to %s' % (len(sys.argv[2:]), sys.argv[1])
    
if __name__ == '__main__':
    main()
