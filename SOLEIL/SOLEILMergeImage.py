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
import gevent


endHeader = b"\x0c\x1a\x04\xd5"
BINARAY_SECTION = b"--CIF-BINARY-FORMAT-SECTION--"
CIF_BINARY_BLOCK_KEY = "_array_data.data"
BLOCK_DATA = "_array_data.header_contents"

def fillHeader(instream,filenameD,start,angle,expotime):

    bufFile = None    
    
    strlist = readHeader(instream,start,angle,expotime)
    
    with open(filenameD, "r") as in_file:
        bufFile = in_file.readlines()
        
    with open(filenameD, "r+") as out_file:
        flag = 0
        for line in bufFile:
            if '###' in line :
               line = '###CBF: Files generated from 10 image to XDS analysis \n'               
            if 'data_' in line:
               line = 'data_'+os.path.basename(filenameD)+' \n'
            if ";" in line and flag == 0:
                line = line + strlist +' \n'
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
    
        popen = subprocess.Popen(command_line,
                                 bufsize = 1,
                                 stdin = subprocess.PIPE,
                                 stdout = subprocess.PIPE,
                                 stderr = subprocess.STDOUT,
                                 cwd = working_directory,
                                 universal_newlines = True,
                                 shell = True,
                                 env = os.environ)
    
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
        
def run_merge2cbf(input_template, image_range, output_template,dirPath):
    MERGE2CBF_file = os.path.join(dirPath, 'MERGE2CBF.INP')
    inpf = open(MERGE2CBF_file, 'w')
    inpf.write(
        'NAME_TEMPLATE_OF_DATA_FRAMES=%s\n' % input_template +
        'DATA_RANGE= %d %d\n' % image_range +
        'NAME_TEMPLATE_OF_OUTPUT_FRAMES=%s\n' % output_template +
        'NUMBER_OF_DATA_FRAMES_COVERED_BY_EACH_OUTPUT_FRAME=%d\n' %
        image_range[1])
    inpf.close()
    try :
        output = run_job('merge2cbf',working_directory = dirPath)
        #print "################  run_merge2cbf Process end  >>>>>>>>>>>>>>>>>> %s" % "".join(output)
        #logging.info("################  run_merge2cbf Process end  >>>>>>>>>>>>>>>>>> %s" % "".join(output))
    except:
        logging.info("run_merge2cbf Process not ended")

def insertlines(outstream, metadata):
    BINARAY_SECTION = b"--CIF-BINARY-FORMAT-SECTION--"
    CIF_BINARY_BLOCK_KEY = "_array_data.data"
    BLOCK_DATA = "_array_data.header_contents"
    strlist = metadata
    #print metadata, type(metadata)
    with open(outstream, "r") as in_file:
        bufFile = in_file.readlines()
    
    with open(outstream, "w") as out_file:
        flag = 0
        for line in bufFile:
            #if '###' in line :
            #   line = '###CBF: Files generated from 10 image to XDS analysis \n'               
            #if 'data_' in line :
            #   line = 'data_'+os.path.basename(filenameD)+' \n'
            if ";" in line and flag == 0:
                line = line + strlist
                flag += 1
            if ";" in line and flag!=0:
                break
            out_file.write(line)

def readHeader(instream,start,angle,expotime):
    
    with open(instream , 'r') as f:
        headerLine = f.read()
        hs,he = 0,0
        hs = headerLine.find(BLOCK_DATA)
        he = headerLine.find(CIF_BINARY_BLOCK_KEY)
        headerIn = headerLine[hs:he]
        lines = headerIn.split(b"\n")
        #lines[6] = re.sub('\d','?',lines[6])
        lines[20] = re.sub('\d','?',lines[20])
        lines[21] = re.sub('\d','?',lines[21])
        ncar = '?'*(lines[20].count('?')-5)+'?.????'
        ncar2 = '?'*(lines[21].count('?')-5)+'?.????'
        lines[20] = lines[20].replace(ncar,'%05.4f')
        lines[21] = lines[21].replace(ncar2,'%05.4f')
        lines[20] = lines[20] % float(start)
        lines[21] = lines[21] % float(angle)
        newHeader = lines[2:-3]
        strlist = "\n".join(newHeader)
        return strlist


def merge(input_filename, output_template, dirPath, startAngle, nOscillation, expotime):
    '''Merge the cbf images of N files with random names.'''
    
    templateIn = input_filename[:-6]+"??.cbf" 
    _output_template_temp = os.path.join(dirPath,output_template)
    output_template = os.path.join(dirPath,output_template[:-6]+"_sum_??.cbf")
    
    try:
        run_merge2cbf(templateIn, (1, 10), output_template, dirPath)
        lastTemplate = output_template[:-6]+"01.cbf"
        os.rename(lastTemplate, _output_template_temp)
        fillHeader(input_filename,_output_template_temp,startAngle,nOscillation,expotime)
        logging.info("merge done in %s" % str(_output_template_temp))
    except :
        logging.info("error during merge process")
    return

def main():
        
    #pattern = 'ref_wdg-lolotest_1_1_00'
    instream_1 = 'ref_wdg-lolotest_1_1_0001.cbf'
    outstream_1 = 'ref-lolotest_1_1_0001.cbf'
    instream_2 = 'ref_wdg-lolotest_1_1_0901.cbf'
    outstream_2 = 'ref-lolotest_1_1_0002.cbf'
    instream_3 = 'ref_wdg-lolotest_1_1_1801.cbf'
    outstream_3 = 'ref-lolotest_1_1_0003.cbf'
    instream_4 = 'ref_wdg-lolotest_1_1_2701.cbf'
    outstream_4 = 'ref-lolotest_1_1_0004.cbf'
    
    start_1 = 0
    start_2 = 90
    start_3 = 180
    start_4 = 270
    angle = 1.0
    expotime = 0.250
    dirPath = os.getcwd()
    
    merge(instream_1, outstream_1,dirPath,start_1,angle,expotime)
    time.sleep(1.0)
    merge(instream_2, outstream_2,dirPath,start_2,angle,expotime) 
    time.sleep(1.0)
    merge(instream_3, outstream_3,dirPath,start_3,angle,expotime)
    time.sleep(1.0)
    merge(instream_4, outstream_4,dirPath,start_4,angle,expotime)
    
if __name__ == '__main__':
    main()
