#!/usr/bin/python

import sys
import re
import tempfile
import os
import time
import struct
import math
import shutil
import io
from PIL import Image
from optparse import OptionParser

BS = 64*1024

class MapError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

def proj2datum(x):
    m = re.search('DATUM\["([^"]+)"', x, re.I)
    if m:
        return m.group(1).upper()
    return None

def gdalinfo_shell(mapfile):
    gdal_info = os.popen('gdalinfo %s' % (mapfile)).readlines()
    datum = None
    upper_left = None
    bottom_right = None
    size = None
    interp = ''
    raw_scale = None
    for line in gdal_info:
        m = re.search('^\s+DATUM\["([^"]+)"', line)
        if m:
            datum = m.group(1)
        m = re.search('^Upper Left\s+\(\s*([0-9.,-]+),\s*([0-9.,-]+)\s*\)', line)
        if m:
            upper_left = (float(m.group(1)), -float(m.group(2)))
        m = re.search('^Lower Right\s+\(\s*([0-9.,-]+),\s*([0-9.,-]+)\s*\)', line)
        if m:
            bottom_right = (float(m.group(1)), -float(m.group(2)))
        m = re.search('^Pixel Size\s+=\s+\(\s*([0-9.,-]+),\s*([0-9.,-]+)\s*\)', line)
        if m:
            raw_scale = (float(m.group(1)), float(m.group(2)))
        m = re.search('^Size\s+is\s+(\d+),\s*(\d+)($|[^0-9])', line)
        if m:
            size = (int(m.group(1)), int(m.group(2)))
        m = re.search('ColorInterp=Palette', line)
        if m:
            interp = ' -expand rgb '
        m = re.search('^Band\s+(\d+)\s+.*ColorInterp=(Red|Green|Blue)', line)
        if m:
            interp += ' -b %s ' % (m.group(1))
    for i in [datum, size, upper_left, bottom_right, raw_scale, interp]:
        if not i:
            return None
    return (datum, size, upper_left, bottom_right, raw_scale, interp)

def gdalinfo_gdal(mapfile):
    tmp = gdal.Open(mapfile)
    proj = tmp.GetProjection()
    tran = tmp.GetGeoTransform()
    size = (tmp.RasterXSize, tmp.RasterYSize)
    datum = proj2datum(proj)
    interp = ' '
    for i in range(1, 5):
        try:
            raw_interp = tmp.GetRasterBand(i).GetRasterColorInterpretation()
        except:
            break
        if raw_interp==gdal.GCI_PaletteIndex:
            interp = ' -expand rgb '
            break
        elif raw_interp in [gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand]:
            interp += '-b %u ' % (i)
    upper_left = (tran[0], -tran[3])
    bottom_right = (tran[0]+tran[1]*size[0]+tran[2]*size[1], -(tran[3]+tran[4]*size[0]+tran[5]*size[1]))
    raw_scale = (tran[1], tran[5])
    return (datum, size, upper_left, bottom_right, raw_scale, interp)

def gdalinfo_rasterio(mapfile):
    with rasterio.open(mapfile) as src:
        interp = None
        tran = src.get_transform()
        proj = src.crs_wkt
        size = (src.width, src.height)
        datum = proj2datum(proj)
        upper_left = (tran[0], -tran[3])
        bottom_right = (tran[0]+tran[1]*size[0]+tran[2]*size[1], -(tran[3]+tran[4]*size[0]+tran[5]*size[1]))
        raw_scale = (tran[1], tran[5])
        return (datum, size, upper_left, bottom_right, raw_scale, interp)

def gdal_translate_shell(infile, outfile, jpeg_quality, x, y, tw, th, interp = None):
    os.system('gdal_translate -of JPEG' + interp + '-co QUALITY=%u ' % (jpeg_quality) + '-srcwin %u %u %u %u ' % (x,y,tw,th) + infile + ' ' + outfile + ' >/dev/null')

def gdal_translate_rasterio(infile, outfile, jpeg_quality, x, y, tw, th, interp = None):
    with rasterio.open(infile) as src:
        bands = src.indexes
        data = src.read(window=((y, y+th), (x, x+tw)))
        if len(data)==1:
            colormap = src.colormap(bands[0])
            vec = numpy.vectorize(lambda z:colormap[z], otypes=[numpy.uint8]*4) 
            tmp = vec(data[0])
            bands = range(1, 4)
            data = numpy.array(tmp[:3])
    with rasterio.open(outfile, 'w', driver='JPEG', width=tw, height=th, count=len(data), dtype=numpy.uint8, quality=jpeg_quality) as dst:
        dst.write(data, bands)

def progress(percent):
    sp = '%.1f%%' % (percent)
    ln = int(float(percent)*70/float(100))
    if ln>len(sp):
        lo = 70-ln
        ln -= len(sp)
    else:
        lo = 70-ln-len(sp)
    sys.stderr.write('\r['+'='*ln+sp+'-'*lo+']')
    if percent==100:
        sys.stderr.write('\n')

try:
    import rasterio
    import numpy
    gdalinfo = gdalinfo_rasterio
    gdal_translate = gdal_translate_rasterio
except:
    try:
        import gdal
        gdalinfo = gdalinfo_gdal
        gdal_translate = gdal_translate_shell
    except:
        gdalinfo = gdalinfo_shell
        gdal_translate = gdal_translate_shell

class mapFile(object):
    def __init__(self, filename):
        self.filename = filename
        try:
            info = gdalinfo(filename)
        except:
            raise MapError('Cant read file "%s" as a map' % (filename))
        if info[0]!='WGS_1984':
            raise MapError('Map "%s" is not in WGS_1984 datum' % (filename))
        self.size = info[1]
        if self.size[0]<256 or self.size[1]<256:
            raise MapError('Map image "%s" should be larger than 256x256 pixels' % (filename))
        self.top_left = info[2]
        self.bottom_right = info[3]
        self.raw_scale = info[4]
        self.scale = (self.raw_scale[0]*256, self.raw_scale[1]*256)
        self.interp = info[5]
        self.first_tile = self.get_first_tile()
        self.diff = self.get_tile_diff()
        self.size_in_tiles = self.get_size_in_tiles()

    def get_size_in_tiles(self):
        tilew = int(math.ceil((self.size[0]-self.diff[0])/float(256))+1)
        tileh = int(math.ceil((self.size[1]-self.diff[1])/float(256))+1)
        return (tilew, tileh)

    def get_tile_diff(self):
        tx = self.first_tile[0]*self.scale[0]
        if tx>0:
            tx = tx - 180
        else:
            tx = -180 - tx
        diffx = 256 - int(round(abs((self.top_left[0] - tx)/self.raw_scale[0])))
        ty = self.first_tile[1]*self.scale[1]
        if ty>0:
            ty = ty - 90
        else:
            ty = -90 - ty
        diffy = 256 - int(round(abs((self.top_left[1] - ty)/self.raw_scale[1])))
        return (diffx, diffy)

    def get_first_tile(self):
        x = int(math.ceil((self.top_left[0]+180)/(abs(self.scale[0])))-10)
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
            if cmin<=self.top_left[0] and self.top_left[0]<cmax:
                first_tile_x = i
                break
        y = int(math.ceil((self.top_left[1]+90)/(abs(self.scale[1])))-10)
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
            if cmin<=self.top_left[1] and self.top_left[1]<cmax:
                first_tile_y = i
                break
        return (first_tile_x, first_tile_y)

class rmpAppender(object):
    def __init__(self, rmpfile, filename):
        self.rmpfile = rmpfile
        self.fileio = self.rmpfile.rmpfile_tmp
        self.filename = filename
        self.start = self.fileio.tell()

    def write(self, *data):
        self.fileio.write(*data)

    def seek(self, pos, whence=0):
        if whence==0:
            self.fileio.seek(self.start+pos, 0)
        elif whence==1:
            self.fileio.seek(pos, 1)
        elif whence==2:
            self.fileio.seek(pos, 2)

    def close(self):
        self.fileio.seek(0, 2)
        filesize = self.fileio.tell()-self.start
        self.rmpfile.files.append((self.filename, self.rmpfile.offset, filesize))
        self.rmpfile.offset += filesize
        if filesize%2==1:
            self.rmpfile.rmpfile_tmp.write('\0')
            self.rmpfile.offset += 1

class rmpFile(object):
    def __init__(self, filename):
        self.filename = filename
        try:
            self.rmpfile_tmp = open(filename+'.tmp', 'w+')
        except:
            raise MapError('Cant open tmp file "%s.tmp" for writing' % (filename))
        self.files = []
        self.offset = 0

    def get_appender(self, filename):
        return rmpAppender(self, filename)

    def append_from_file(self, targetname, sourcename):
        appender = self.get_appender(targetname)
        rfile = open(sourcename)
        while True:
            data = rfile.read(BS)
            appender.write(data)
            if len(data)<BS:
                break
        rfile.close()
        appender.close()

    def append_from_string(self, targetname, content):
        appender = self.get_appender(targetname)
        appender.write(content)
        appender.close()

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
    def __init__(self, outfile, map_group, map_prov, jpeg_quality = 75, show_progress = False, resdir = 'bin_res', tempdir = tempfile.mkdtemp('', 'rmp')):
        self.maps = []
        self.outfile = outfile
        self.map_group = map_group
        self.map_prov = map_prov
        self.jpeg_quality = jpeg_quality
        self.show_progress = show_progress
        self.resdir = resdir
        self.tempdir = tempdir

    def add_map(self, rmap):
        self.maps.append(rmap)

    def prepare_tmpdir(self):
        try:
            os.makedirs(self.tempdir)
        except:
            pass

    def craft_description_file(self):
        descfile = ';Map Support File : Contains Meta Data Information about the Image\r\n'
        descfile += 'IMG_NAME = %s\r\n' % (self.outfile.replace('.rmp', ''))
        descfile += 'PRODUCT = %s\r\n' % (self.map_group)
        descfile += 'PROVIDER = %s\r\n' % (self.map_prov)
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
            inifile += '%u=TOPO%u\r\n' % (i, i)
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

    @staticmethod
    def crop_image(str_img, tw, th, xpad, ypad):
        if xpad>=0:
            xcrop = 0
        else:
            xcrop = 256 - tw
        if ypad>=0:
            ycrop = 0
        else:
            ycrop = 256 - th
        img = Image.open(io.BytesIO(str_img))
        new_img = Image.new("RGB", (256, 256))
        new_img.paste(img, (xcrop, ycrop))
        o_img = io.BytesIO()
        new = new_img.save(o_img, 'JPEG')
        return o_img.getvalue()

    def craft_tiles(self, rmap):
        num_tiles = rmap.size_in_tiles[0]*rmap.size_in_tiles[1]
        idx = self.maps.index(rmap)

        a00name = 'topo%u.a00' % (idx)
        a00 = self.rmpfile.get_appender(a00name)
        a00.write(struct.pack('I', num_tiles))
        offsets = [4]

        for ix in range(0, rmap.size_in_tiles[0]):
            if self.show_progress:
                progress(100*ix/float(rmap.size_in_tiles[0]))
            for iy in range(0, rmap.size_in_tiles[1]):
                (x, tw, xpad) = self.get_tile_geometry(ix, rmap.diff[0], rmap.size[0])
                (y, th, ypad) = self.get_tile_geometry(iy, rmap.diff[1], rmap.size[1])
                jtile = os.path.join(self.tempdir, 'tile.jpg')
                gdal_translate(rmap.filename, jtile, self.jpeg_quality, x, y, tw, th, rmap.interp)
                tile = open(jtile).read()
                if xpad!=0 or ypad!=0:
                    tile = self.crop_image(tile, tw, th, xpad, ypad)
                a00.write(struct.pack('I', len(tile)))
                a00.write(tile)
                offsets.append(offsets[-1] + len(tile) + 4)
        a00.close()
        if self.show_progress:
            progress(100)

        tlmname = 'topo%u.tlm' % (idx)
        tlm = self.rmpfile.get_appender(tlmname)
        header = '\x01\x00\x00\x00'
        header += struct.pack('I', num_tiles)
        header += '\x00\x01\x00\x01\x01\x00\x00\x00'
        header += struct.pack('dd', abs(rmap.scale[1]), abs(rmap.scale[0]))
        header += struct.pack('dd', rmap.top_left[0], rmap.top_left[1])
        header += struct.pack('dd', rmap.bottom_right[0], rmap.bottom_right[1])
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
        for ix in range(0, rmap.size_in_tiles[0]):
            for iy in range(0, rmap.size_in_tiles[1]):
                x = rmap.first_tile[0] + ix
                y = rmap.first_tile[1] + iy
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
                tlm.write(struct.pack('II', num_tiles, blocks[i]))
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

    def run(self):
        self.rmpfile = rmpFile(self.outfile)
        self.prepare_tmpdir()
        self.craft_resourse_files()
        for rmap in self.maps:
            self.craft_tiles(rmap)
        self.craft_description_file()
        self.craft_ini_file()
        self.rmpfile.finish()
        shutil.rmtree(self.tempdir)
 
if __name__=='__main__':
    usage = "usage: %prog [options] <input map1> [input map2] ..."
    parser = OptionParser(usage=usage)
    parser.add_option("-o", "--outfile", dest="rmpfile", help="write result to rmp file")
    parser.add_option("-g", "--group", dest="group", help="map group [default: %default]", default='Map')
    parser.add_option("-p", "--provider", dest="prov", help="map provider [default: %default]", default='geotiff2rmp.py')
    (options, args) = parser.parse_args()
    if not options.rmpfile or len(args)<1:
        parser.print_usage()
        sys.exit(-1)
    converter = rmpConverter(options.rmpfile, options.group, options.prov, show_progress=True)
    for mapfile in args:
        rmap = mapFile(mapfile)
        converter.add_map(rmap)
    converter.run()

