#!/usr/bin/python

import sys
import gdal
import re
import tempfile
import os
import time
import struct
import math
import shutil

BS = 64*1024

class MapError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class mapFile(object):
    def __init__(self, filename):
        self.filename = filename
        try:
            tmp = gdal.Open(filename)
            self.proj = tmp.GetProjection()
            self.tran = tmp.GetGeoTransform()
            self.size = (tmp.RasterXSize, tmp.RasterYSize)
        except:
            raise MapError('Cant read file "%s" as a map' % (filename))
        if self.size[0]<256 or self.size[1]<256:
            raise MapError('Map image "%s" should be larger than 256x256 pixels' % (filename))
        if self.proj2datum(self.proj)!='WGS_1984':
            raise MapError('Map "%s" is not in WGS_1984 datum' % (filename))
        self.interp = ' '
        for i in range(1, 4):
            try:
                interp = tmp.GetRasterBand(i).GetRasterColorInterpretation()
            except:
                break
            if interp==gdal.GCI_PaletteIndex:
                self.interp = ' -expand rgb '
                break
            elif interp in [gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand]:
                self.interp += '-b %u ' % (i)
        self.tl = (self.tran[0], -self.tran[3])
        self.br = (self.tran[0]+self.tran[1]*self.size[0]+self.tran[2]*self.size[1], -(self.tran[3]+self.tran[4]*self.size[0]+self.tran[5]*self.size[1]))
        self.scale = (self.tran[1]*256, self.tran[5]*256)
        self.firsttile = self.get_first_tile()
        self.diff = self.get_tile_diff()
        self.tiles = self.get_size_in_tiles()
        del tmp
   
    def get_size_in_tiles(self):
        tilew = int(math.ceil((self.size[0]-self.diff[0])/float(256))+1)
        tileh = int(math.ceil((self.size[1]-self.diff[1])/float(256))+1)
        return (tilew, tileh)

    def get_tile_diff(self):
        tx = self.firsttile[0]*self.scale[0]
        if tx>0:
            tx = tx - 180
        else:
            tx = -180 - tx
        diffx = 256 - int(round(abs((self.tl[0] - tx)/self.tran[1])))
        ty = self.firsttile[1]*self.scale[1]
        if ty>0:
            ty = ty - 90
        else:
            ty = -90 - ty
        diffy = 256 - int(round(abs((self.tl[1] - ty)/self.tran[5])))
        return (diffx, diffy)

    def get_first_tile(self):
        x = int(math.ceil((self.tl[0]+180)/(abs(self.scale[0])))-10)
        for i in range(x, x+21):
            cmin = i*self.scale[0]
            cmax = (i+1)*self.scale[0]
            if cmin<0:
                cmin = -180 - cmin
            else:
                cmin = cmin - 180
            if cmax<0:
                cmax = -180 - cmax
            else:
                cmax = cmax - 180
            if cmin<=self.tl[0] and self.tl[0]<cmax:
                firsttilex = i
                break
        y = int(math.ceil((self.tl[1]+90)/(abs(self.scale[1])))-10)
        for i in range(y, y+21):
            cmin = i*self.scale[1]
            cmax = (i+1)*self.scale[1]
            if cmin<0:
                cmin = -90 - cmin
            else:
                cmin = cmin - 90
            if cmax<0:
                cmax = -90 - cmax
            else:
                cmax = cmax - 90
            if cmin<=self.tl[1] and self.tl[1]<cmax:
                firsttiley = i
                break
        return (firsttilex, firsttiley)

    @staticmethod
    def proj2datum(x):
        m = re.search('DATUM\["([^"]+)"', x, re.I)
        if m:
            return m.group(1).upper()
        return None
     
class rmpFile(object):
    def __init__(self, filename):
        self.filename = filename
        try:
            self.rmpfile_tmp = open(filename+'.tmp', 'w+')
        except:
            raise MapError('Cant open tmp file "%s.tmp" for writing' % (filename))
        self.files = []
        self.offset = 0

    def append_from_file(self, targetname, sourcename):
        filesize = os.stat(sourcename).st_size
        self.files.append((targetname, self.offset, filesize))
        rfile = open(sourcename)
        for i in range(0, (filesize+BS-1)/BS):
            self.rmpfile_tmp.write(rfile.read(BS))
        rfile.close()
        self.offset += filesize
        if filesize%2==1:
            self.rmpfile_tmp.write('\0')
            self.offset += 1

    def append_from_string(self, targetname, content):
        self.files.append((targetname, self.offset, len(content)))
        self.rmpfile_tmp.write(content)
        self.offset += len(content)
        if len(content)%2==1:
            self.rmpfile_tmp.write('\0')
            self.offset += 1

    def finish(self):
        try:
            self.rmpfile = open(self.filename, 'w')
        except:
            raise MapError('Cant open result file for "%s" for writing' % (self.filename))
        numfiles = len(self.files)
        self.rmpfile.write(struct.pack('II', numfiles, numfiles))
        for i in range(0, numfiles):
            name = self.files[i][0].rsplit('.', 1)
            metadata =(name[0]+'\0'*9)[:9] + (name[1]+'\0'*7)[:7]
            metadata += struct.pack('II', self.files[i][1]+40+24*numfiles, self.files[i][2])
            self.rmpfile.write(metadata)
        self.rmpfile.write('\xe5\xe5MAGELLAN\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
        self.rmpfile_tmp.seek(0, 0)
        for i in range(0, (self.offset+BS-1)/BS):
            self.rmpfile.write(self.rmpfile_tmp.read(BS))
        self.rmpfile.write('MAGELLAN};')
        self.rmpfile.close()
        self.rmpfile_tmp.close()
        os.unlink(self.filename+'.tmp')

class rmpConverter(object):
    def __init__(self, outfile, mapgroup, mapprov, jpegquality = 75, resdir = 'bin_res', tempdir = tempfile.mkdtemp('', 'rmp')):
        self.maps = []
        self.outfile = outfile
        self.mapgroup = mapgroup
        self.mapprov = mapprov
        self.jpegquality = jpegquality
        self.resdir = resdir
        self.tempdir = tempdir
        self.tilesdir = tempdir + '/tiles/'

    def add_map(self, rmap):
        self.maps.append(rmap)

    def prepare_tmpdir(self):
        try:
            shutil.rmtree(self.tilesdir)
        except:
            pass
        os.makedirs(self.tilesdir)

    def craft_description_file(self):
        descfile = ';Map Support File : Contains Meta Data Information about the Image\r\n'
        descfile += 'IMG_NAME = %s\r\n' % (self.outfile.replace('.rmp', ''))
        descfile += 'PRODUCT = %s\r\n' % (self.mapgroup)
        descfile += 'PROVIDER = %s\r\n' % (self.mapprov)
        descfile += 'IMG_DATE = %s\r\n' % (time.strftime('%d.%m.%Y %H:%M:%S'))
        descfile += 'IMG_VERSION = 31\r\n'
        descfile += 'Version = 31\r\n'
        descfile += 'BUILD=\r\n'
        descfile += 'VENDOR_ID = -1\r\n'
        descfile += 'REGION_ID = -1\r\n'
        descfile += 'MAP_TYPE = TNDB_RASTER_MAP\r\n'
        descfile += 'ADDITIONAL_COMMENTS = created with geotiff2rmp.py\r\n'
        self.rmpfile.append_from_string('cvg_map.msf', descfile)

    def craft_ini_file(self):
        inifile = '[T_Layers]\r\n' 
        for i in range(0, len(self.maps)):
            inifile += '%u=TOPO%u\r\n' % (i, i+1)
        inifile += '\0'
        self.rmpfile.append_from_string('rmp.ini', inifile)

    def craft_resourse_files(self):
        for i in ['chunk.ics', 'BMP4BIT.ICS']:
            self.rmpfile.append_from_file(i, self.resdir + '/' + i)

    @staticmethod
    def get_tile_geometry(tileno, diff, size):
        if tileno==0:
            x = 0
        else:
            x = diff + (tileno-1)*256
        if diff<256 and tileno==0:
            w = diff
            pad = -1
        elif size<x+256:
            w = size-x
            pad = 1
        else:
            w = 256
            pad = 0
        return (x, w, pad)

    def craft_tiles(self, rmap):
        for iy in range(0, rmap.tiles[1]):
            for ix in range(0, rmap.tiles[0]):
                (x, tw, xpad) = self.get_tile_geometry(ix, rmap.diff[0], rmap.size[0])
                (y, th, ypad) = self.get_tile_geometry(iy, rmap.diff[1], rmap.size[1])
                tile = 'tile-%u-%u-%u.jpg' % (self.maps.index(rmap), ix, iy)
                jtile = '%s/%s' % (self.tilesdir, tile)
                print 'gdal_translate -of JPEG' + rmap.interp + '-co QUALITY=%u ' % (self.jpegquality) + '-srcwin %u %u %u %u ' % (x,y,tw,th) + rmap.filename + ' ' + jtile
                os.system('gdal_translate -of JPEG' + rmap.interp + '-co QUALITY=%u ' % (self.jpegquality) + '-srcwin %u %u %u %u ' % (x,y,tw,th) + rmap.filename + ' ' + jtile)
                if xpad!=0 or ypad!=0:
                    if xpad>=0:
                        xcrop = '+0'
                    else:
                        xcrop = '-%u' % (256 - tw)
                    if ypad>=0:
                        ycrop = '+0'
                    else:
                        ycrop = '-%u' % (256 - th)
                    print 'convert -crop 256x256%s%s! -flatten %s %s.tmp' % (xcrop, ycrop, jtile, jtile)
                    os.system('convert -crop 256x256%s%s! -flatten %s %s.tmp' % (xcrop, ycrop, jtile, jtile))
                    os.unlink(jtile)
                    os.rename(jtile+'.tmp', jtile)

    def craft_a00(self, rmap):
        num_tiles = rmap.tiles[0]*rmap.tiles[1]
        idx = self.maps.index(rmap)

        a00name = 'topo%u.a00' % (idx)
        a00 = open(self.tempdir + '/' + a00name, 'w')
        a00.write(struct.pack('I', num_tiles))
        offsets = [4]
        for iy in range(0, rmap.tiles[1]):
            for ix in range(0, rmap.tiles[0]):
                tile = 'tile-%u-%u-%u.jpg' % (self.maps.index(rmap), ix, iy)
                jtile = '%s/%s' % (self.tilesdir, tile)
                tilesize = os.stat(jtile).st_size
                a00.write(struct.pack('I', tilesize))
                a00.write(open(jtile).read())
                offsets.append(offsets[-1] + tilesize + 4)
        a00.close()
        self.rmpfile.append_from_file(a00name, self.tempdir + '/' + a00name)
        
        tlmname = 'topo%u.tlm' % (idx)
        tlm = open(self.tempdir + '/' + tlmname, 'w')
        header = '\x01\x00\x00\x00'
        header += struct.pack('I', num_tiles)
        header += '\x00\x01\x00\x01\x01\x00\x00\x00'
        header += struct.pack('dd', abs(rmap.scale[0]), abs(rmap.scale[1]))
        header += struct.pack('dd', rmap.tl[0], rmap.tl[1])
        header += struct.pack('dd', rmap.br[0], rmap.br[1])
        header += '\0'*(0x99-len(header)) + '\x01'
        header += '\0'*(0x100-len(header)) + '\x01'
        header += '\0'*(0x104-len(header)) + '\x63'
        tlm.write(header)

        num_blocks = int(math.ceil(num_tiles/float(70)))
        if num_blocks>1:
            num_blocks += 1
            num_addblocks = num_blocks - 2
        else:
            num_addblocks = 0

        blocks = []
        done = 0
        for iy in range(0, rmap.tiles[1]):
            for ix in range(0, rmap.tiles[0]):
                x = rmap.firsttile[0] + ix
                y = rmap.firsttile[1] + iy
                block = 0
                for j in range(2, num_blocks):
                    if done>(j-1)*70+j-2 and done<=j*70+j-2:
                        block = j
                        break
                for j in range(0, num_blocks):
                    if done==70*(j+1)+j:
                        block = 1
                        break
                if len(blocks)<=block:
                    blocks.append(0)
                offset = 0x105c + 0x7c8*block + 8 + 16 * blocks[block]
                tlm.seek(offset, 0)
                tlm.write(struct.pack('IIII', x, y, 0, offsets[done]))
                blocks[block] += 1
                done += 1

        for i in range(0, num_blocks):
            offset = 0x105c + 0x7c8*i
            tlm.seek(offset, 0)
            if i==1:
                tlm.write(struct.pack('IHH', num_tiles, 0, blocks[i]))
            else:
                tlm.write(struct.pack('IHH', blocks[i], blocks[i], 1))

        if num_addblocks>0:
            tlm.seek(0x108, 0)
            tlm.write('\x24\x17\x00\x00')
            tlm.seek(0x1E5C, 0)
            tlm.write('\x5c\x0f\x00\x00')
            for i in range(2, num_blocks):
                offset = 0x1E5C + (i-1)*4
                val = 0x0F5C + 0x0f90 + 0x07c8*(i-2)
                tlm.seek(offset, 0)
                tlm.write(struct.pack('I', val))
        else:
            tlm.seek(0x108, 0)
            tlm.write('\x5c\x0f\x00\x00')

        val = 0x105c + 0x7c8*(num_blocks+2)
        tlm.seek(0x9c, 0)
        tlm.write(struct.pack('I', val))
        tlm.seek(val-1, 0)
        tlm.write('\0')
        tlm.close()
        self.rmpfile.append_from_file(tlmname, self.tempdir + '/' + tlmname)

    def run(self):
        self.rmpfile = rmpFile(self.outfile)
        self.prepare_tmpdir()
        self.craft_resourse_files()
        for rmap in self.maps:
            self.craft_tiles(rmap)
            self.craft_a00(rmap)
        self.craft_description_file()
        self.craft_ini_file()
        self.rmpfile.finish()
        shutil.rmtree(self.tempdir)
 
if __name__=='__main__':
    converter = rmpConverter('test.rmp', 'test', 'baz')
    for mapfile in ['test.tiff']:
        rmap = mapFile(mapfile)
        converter.add_map(rmap)
    converter.run()

