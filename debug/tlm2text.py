#!/usr/bin/python

import os
import sys
import struct
import math

def tlm2text(tlmfile):
    tlmsize = os.stat(tlmfile).st_size
    tlm = open(tlmfile, 'rb')
    tlm.read(4)
    num_tiles = struct.unpack('I', tlm.read(4))[0]
    print 'Num tiles: %u' % (num_tiles)
    tlm.read(8)
    scale = struct.unpack('dd', tlm.read(16))
    print 'Scale: %f, %f' % scale
    tl = struct.unpack('dd', tlm.read(16))
    print 'Top left corner: %f, %f' % tl
    br = struct.unpack('dd', tlm.read(16))
    print 'Bottom right corner: %f, %f' % br
    num_blocks = int(math.ceil(num_tiles/float(70)))
    if num_blocks>1:
        num_blocks += 1
        num_addblocks = num_blocks - 2
    else:
        num_addblocks = 0

    blocks = []
    for tilenum in range(0, num_tiles):
        block = 0
        for j in range(2, num_blocks):
            if tilenum>(j-1)*70+j-3 and tilenum<j*70+j-1:
                block = j
                break
        for j in range(0, num_blocks):
            if tilenum==70*(j+1)+j:
                block = 1
                break
        if len(blocks)<=block:
            blocks.append(0)
        offset = 0x105c + 0x7c8*block + 8 + 16 * blocks[block]
        tlm.seek(offset, 0)
        (x, y, tmp, tileoffset) = struct.unpack('IIII', tlm.read(16))
        print 'Tile %u with coordinates %u %u, block %u[%u] and offset %u' % (tilenum, x, y, blocks[block], block, tileoffset)
        blocks[block] += 1

    checks = True
    for i in range(0, num_blocks):
        offset = 0x105c + 0x7c8*i
        tlm.seek(offset, 0)
        if i==1:
            tmp = struct.unpack('II', tlm.read(8))
            if tmp[0]!=num_tiles or tmp[1]!=blocks[i]:
                print 'Funny checks failed in #1'
                checks = False
        else:
            tmp = struct.unpack('IHH', tlm.read(8))
            if tmp[0]!=blocks[i] or tmp[1]!=blocks[i] and tmp[2]!=1:
                print 'Funny checks failed in #2'
                checks = False

    if num_addblocks>0:
        tlm.seek(0x108, 0)
        if tlm.read(4)!='$\x17\x00\x00':
            print 'Funny checks failed in #3'
            checks = False
        tlm.seek(0x1E5C, 0)
        if tlm.read(4)!='\\\x0f\x00\x00':
            print 'Funny checks failed in #4'
            checks = False
        for i in range(2, num_blocks):
            offset = 0x1E5C + (i-1)*4
            val = 0x0F5C + 0x0f90 + 0x07c8*(i-2)
            tlm.seek(offset, 0)
            if struct.unpack('I', tlm.read(4))[0]!=val:
                print 'Funny checks failed in #5'
                checks = False
    else:
        tlm.seek(0x108, 0)
        if tlm.read(4)!='\\\x0f\x00\x00':
            print 'Funny checks failed in #6'
            checks = False

    val = 0x105c + 0x7c8*(num_blocks+2)
    tlm.seek(0x9c, 0)
    if struct.unpack('I', tlm.read(4))[0]!=val:
        print 'Funny checks failed in #7'
        checks = False
    tlm.seek(val-1, 0)
    if tlm.read(1)!='\0':
        print 'Funny checks failed in #8'
        checks = False
    if checks:
        print 'Funny checks is ok'

    tlm.close()
    return (0,'')

if __name__=='__main__':
    res = tlm2text(sys.argv[1])
    if res[0]!=0:
        sys.stderr.write('%s\n' % (res[1]))
        sys.exit(-1)

