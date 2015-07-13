#!/usr/bin/python

import sys
sys.path.append('..')
import geotiff2rmp

def pack_rmp(rmpdir, rmpfile):
    rmp = geotiff2rmp.rmpFile(rmpfile)
    rmp.append_dir(rmpdir)
    rmp.finish()

if len(sys.argv)<3:
    sys.stderr.write('Usage: packrmp.py <dir> <rmp file>\n')
    sys.exit(1)

pack_rmp(sys.argv[1], sys.argv[2])

