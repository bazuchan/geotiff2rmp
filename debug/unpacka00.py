#!/usr/bin/python

import os
import sys
import struct

BS = 64*1024

def unpack_a00(a00file, upath):
    a00size = os.stat(a00file).st_size
    a00 = open(a00file, 'rb')
    numfiles = struct.unpack('I', a00.read(4))[0]
    files = []
    if not os.path.exists(upath):
        os.makedirs(upath)
    if not os.path.isdir(upath):
        return (-1, 'Cant create targer directory: %s\n' % (upath))
    filenum = 0
    while a00size-a00.tell()>2:
        filename = ('%10u.jpg' % (filenum)).replace(' ', '0')
        sys.stderr.write('Unpacking %s\n' % (filename))
        filesize = struct.unpack('I', a00.read(4))[0]
        w = open(os.path.join(upath, filename), 'wb')
        for k in range(0, (filesize+BS-1)/BS):
            data = a00.read(min(filesize-BS*k, BS))
            w.write(data)
        w.close()
        filenum += 1
    a00.close()
    return (0,'')

if __name__=='__main__':
    res = unpack_a00(sys.argv[1], sys.argv[2])
    if res[0]!=0:
        sys.stderr.write('%s\n' % (res[1]))
        sys.exit(-1)

