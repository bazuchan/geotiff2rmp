#!/usr/bin/python

import os
import sys
import struct

BS = 64*1024

def unpack_rmp(rmpfile, upath):
    rmp = open(rmpfile, 'rb')
    (numfiles, numfiles) = struct.unpack('II', rmp.read(8))
    files = []
    for i in range(0, numfiles):
        metadata = rmp.read(24)
        filename = metadata[:9].rstrip('\0') + '.' + metadata[9:16].rstrip('\0')
        (fileoffset, filesize) = struct.unpack('II', metadata[16:])
        files.append((filename, fileoffset, filesize))
    tmp = rmp.read(40)
    if tmp[2:10]!='MAGELLAN':
        print repr(tmp)
        return (-1,'Broken RMP file: %s\n' % (rmpfile))
    if not os.path.exists(upath):
        os.makedirs(upath)
    if not os.path.isdir(upath):
        return (-1, 'Cant create targer directory: %s\n' % (upath))
    for i in files:
        if i[0].find('/')!=-1:
            sys.stderr.write('Skipping file %s due to bad name\n' % (i[0]))
            continue
        sys.stderr.write('Unpacking %s\n' % (i[0]))
        rmp.seek(i[1], 0)
        w = open(os.path.join(upath, i[0]), 'wb')
        for k in range(0, (i[2]+BS-1)/BS):
            data = rmp.read(min(i[2]-BS*k, BS))
            w.write(data)
        w.close()
    rmp.close()
    return (0,'')

if __name__=='__main__':
    res = unpack_rmp(sys.argv[1], sys.argv[2])
    if res[0]!=0:
        sys.stderr.write('%s\n' % (res[1]))
        sys.exit(-1)

