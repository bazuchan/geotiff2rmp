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
    os.popen4('gdal_translate -of JPEG' + interp + '-co QUALITY=%u ' % (jpeg_quality) + '-srcwin %u %u %u %u ' % (x,y,tw,th) + infile + ' ' + outfile)[1].read()

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
        ln = 0
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
    if os.path.isdir('gdal') and os.getenv('PATH'):
        os.environ['PATH'] += os.pathsep + os.path.join(os.getcwd(), 'gdal')
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
        (self.first_tile, self.first_tile_coord) = self.get_first_tile()
        self.diff = self.get_tile_diff()
        self.size_in_tiles = self.get_size_in_tiles()
        max_tiles = tlmFile().get_max_num_tiles()
        self.num_topos = (self.size_in_tiles[0]*self.size_in_tiles[1]+max_tiles-1)/max_tiles
        self.topo_len = max_tiles/self.size_in_tiles[1]

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
                first_tile_lat = cmin
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
                first_tile_lon = cmin
                first_tile_y = i
                break
        return ((first_tile_x, first_tile_y), (first_tile_lat, first_tile_lon))

class rmpAppender(object):
    def __init__(self, rmpfile, filename):
        self.rmpfile = rmpfile
        self.fileio = self.rmpfile.rmpfile
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

    def tell(self):
        return self.fileio.tell()-self.start

    def close(self):
        self.fileio.seek(0, 2)
        filesize = self.fileio.tell()-self.start
        self.rmpfile.files.append((self.filename, self.rmpfile.offset, filesize))
        self.rmpfile.offset += filesize
        if filesize%2==1:
            self.rmpfile.rmpfile.write('\0')
            self.rmpfile.offset += 1

class rmpFile(object):
    def __init__(self, filename):
        self.filename = filename
        self.filename_tmp = self.filename + '.tmp'
        if os.path.exists(self.filename):
            os.unlink(self.filename)
        try:
            self.rmpfile = open(self.filename_tmp, 'wb+')
        except:
            raise MapError('Cant open tmp rmp file "%s" for writing' % (self.filename_tmp))
        self.files = []
        self.prealloc_files = 256
        self.header_len = 40+24*self.prealloc_files
        self.rmpfile.seek(self.header_len, 0)
        self.offset = 0

    def get_appender(self, filename):
        return rmpAppender(self, filename)

    def append_from_file(self, targetname, sourcename):
        appender = self.get_appender(targetname)
        rfile = open(sourcename, 'rb')
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

    def append_dir(self, rmpdir):
        for rdir in os.walk(rmpdir):
            for rfile in rdir[2]:
                path = os.path.join(rdir[0], rfile)
                self.append_from_file(rfile, path)

    def finish(self):
        if len(self.files)>self.prealloc_files:
            tmpfile = open(self.filename_tmp+'2', 'wb+')
            (rmpfile_old, self.rmpfile) = (self.rmpfile, tmpfile)
        self.rmpfile.seek(0, 0)
        numfiles = len(self.files)
        self.rmpfile.write(struct.pack('II', numfiles, numfiles))
        for i in range(0, numfiles):
            name = self.files[i][0].rsplit('.', 1) + ['']
            metadata =(name[0]+'\0'*9)[:9] + (name[1]+'\0'*7)[:7]
            metadata += struct.pack('II', self.files[i][1]+max(self.header_len, 40+24*numfiles), self.files[i][2])
            self.rmpfile.write(metadata)
        self.rmpfile.write('\xe5\xe5MAGELLAN\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
        if len(self.files)>self.prealloc_files:
            rmpfile_old.seek(self.header_len, 0)
            for i in range(0, (self.offset+BS-1)/BS):
                self.rmpfile.write(rmpfile_old.read(BS))
            rmpfile_old.close()
            os.unlink(self.filename_tmp)
            os.rename(self.filename_tmp+'2', self.filename_tmp)
        self.rmpfile.seek(0, 2)
        self.rmpfile.write('MAGELLAN};')
        self.rmpfile.close()
        os.rename(self.filename_tmp, self.filename)

class tlmFile(object):
    def __init__(self, tlm=None, rmap=None, tiles_offset=None, tiles_size=None):
        self.tlm = tlm
        self.rmap = rmap
        self.tiles_size = tiles_size
        self.tiles_offset = tiles_offset
        self.blocks_start = 0xf5c
        self.block_size = 0x7c8
        self.header_len = 0x100
        self.tiles_per_block = 99
        self.reserve = 19
        self.real_tiles_per_block = self.tiles_per_block - self.reserve
        if rmap==None:
            return
        self.calc_num_blocks()
        self.block = 0
        self.idxblock = 1
        self.blocks = [0]*self.num_data_blocks
        (self.top_left, self.bottom_right) = self.calc_corners()

    def calc_num_blocks(self):
        self.num_tiles = self.tiles_size[0]*self.tiles_size[1]
        self.num_data_blocks = (self.num_tiles+self.real_tiles_per_block-1)/self.real_tiles_per_block
        if self.num_data_blocks>1:
            self.num_data_blocks += 1
            self.num_index_blocks = (self.num_data_blocks+self.real_tiles_per_block-1)/self.real_tiles_per_block
            if self.num_index_blocks>1:
                raise MapError('TLM file seems to not support more than 1 index block')
            self.first_block_offset = self.blocks_start + self.block_size
        else:
            self.num_index_blocks = 0
            self.first_block_offset = self.blocks_start
        self.filesize = 0x105c + self.block_size*(self.num_data_blocks+2)

    def calc_corners(self):
        if self.tiles_offset and self.tiles_offset[0]>0:
            tlx = (self.rmap.first_tile[0]+self.tiles_offset[0])*abs(self.rmap.scale[0])-180
        else:
            tlx = self.rmap.top_left[0]
        if self.tiles_offset and self.tiles_offset[1]>0:
            tly = (self.rmap.first_tile[1]+self.tiles_offset[1])*abs(self.rmap.scale[1])-90
        else:
            tly = self.rmap.top_left[1]
        if self.tiles_size and self.tiles_size[0]<self.rmap.size_in_tiles[0]-self.tiles_offset[0]:
            brx = (self.rmap.first_tile[0]+self.tiles_offset[0]+self.tiles_size[0])*abs(self.rmap.scale[0])-180
        else:
            brx = self.rmap.bottom_right[0]
        if self.tiles_size and self.tiles_size[1]<self.rmap.size_in_tiles[1]-self.tiles_offset[1]:
            bry = (self.rmap.first_tile[1]+self.tiles_offset[1]+self.tiles_size[1])*abs(self.rmap.scale[1])-90
        else:
            bry = self.rmap.bottom_right[1]
        return ((tlx, tly), (brx, bry))

    def get_max_num_tiles(self):
        return (self.real_tiles_per_block-1)*self.real_tiles_per_block

    def write_header(self):
        header = struct.pack('I', 1)
        header += struct.pack('I', self.num_tiles)
        header += struct.pack('HH', 256, 256)
        header += struct.pack('I', 1)
        header += struct.pack('dd', abs(self.rmap.scale[1]), abs(self.rmap.scale[0]))
        header += struct.pack('dd', self.top_left[0], self.top_left[1])
        header += struct.pack('dd', self.bottom_right[0], self.bottom_right[1])
        header += '\0'*(0x98-len(header))
        # another 256?
        header += struct.pack('HH', 256, 0)
        header += struct.pack('I', self.filesize)
        header += '\0'*(0x100-len(header))
        header += struct.pack('I', 1)
        header += struct.pack('I', self.tiles_per_block)
        header += struct.pack('I', self.first_block_offset)
        header += '\0'*(self.blocks_start-len(header))
        self.tlm.write(header)

    def get_block_offset(self, block, idx):
        offset = self.blocks_start + self.header_len + self.block_size*block + 8 + 16 * idx
        return offset

    def get_next_block(self):
        if self.blocks[self.block]<self.real_tiles_per_block:
            self.blocks[self.block] +=1
            return (self.block, self.blocks[self.block]-1)
        else:
            if self.block==0:
                self.block = self.num_index_blocks + 1
            else:
                self.block += 1
            if self.blocks[self.idxblock]>=self.real_tiles_per_block:
                self.idxblock += 1
            self.blocks[self.idxblock] += 1
            return (self.idxblock, self.blocks[self.idxblock]-1)

    def add_tile(self, x, y, addr):
        next_block = self.get_next_block()
        offset = self.get_block_offset(*next_block)
        self.tlm.seek(offset, 0)
        self.tlm.write(struct.pack('IIII', x, y, 0, addr))

    def write_blocks_headers(self):
        for i in range(1, self.num_index_blocks+1):
            offset = self.blocks_start + self.block_size*i + self.header_len
            self.tlm.seek(offset, 0)
            self.tlm.write(struct.pack('IHH', self.num_tiles, self.blocks[i], 0))

        for i in [0] + range(self.num_index_blocks+1, self.num_data_blocks):
            offset = self.blocks_start + self.block_size*i + self.header_len
            self.tlm.seek(offset, 0)
            self.tlm.write(struct.pack('IHH', self.blocks[i], self.blocks[i], 1))

    def write_blocks_links(self):
        for i in range(0, self.num_index_blocks):
            self.tlm.seek(self.blocks_start +  self.block_size*(i+1) + self.header_len + 8 + 16*self.tiles_per_block, 0)
            self.tlm.write(struct.pack('I', self.blocks_start + self.block_size*i))
            for j in range(0, self.real_tiles_per_block):
                if j>self.blocks[i+1]-1:
                    break
                val = self.blocks_start + self.block_size*(j+2)
                self.tlm.write(struct.pack('I', val))

    def finish(self):
        self.write_blocks_headers()
        self.write_blocks_links()
        self.tlm.seek(self.filesize-1, 0)
        self.tlm.write('\0')
        self.tlm.close()

class rmpConverter(object):
    def __init__(self, outfile, map_name, map_group, map_prov, map_ver, map_contact, map_copyright, map_copyright_file, jpeg_quality = 75, show_progress = False, resdir = 'bin_res'):
        self.maps = []
        self.outfile = outfile
        self.map_name = map_name
        self.map_group = map_group
        self.map_prov = map_prov
        self.map_ver = map_ver
        self.map_contact = map_contact
        self.map_copyright = map_copyright
        self.map_copyright_file = map_copyright_file
        self.jpeg_quality = jpeg_quality
        self.show_progress = show_progress
        self.resdir = resdir
        self.temp_tile = self.outfile + '.tile0'
        self.idx = 0

    def add_map(self, rmap):
        self.maps.append(rmap)

    def craft_description_file(self):
        descfile = ';Map Support File : Contains Meta Data Information about the Image\r\n'
        descfile += 'IMG_NAME = %s\r\n' % (self.map_name)
        descfile += 'PRODUCT = %s\r\n' % (self.map_group)
        descfile += 'PROVIDER = %s\r\n' % (self.map_prov)
        descfile += 'IMG_DATE = %s\r\n' % (time.strftime('%d.%m.%Y %H:%M:%S'))
        descfile += 'IMG_VERSION = %s\r\n' % (self.map_ver)
        descfile += 'CONTACT_INFO = %s\r\n' % (self.map_contact)
        descfile += 'MAP_TYPE = TNDB_RASTER_MAP\r\n'
        descfile += 'MAP_COUNT = %u\r\n' % (self.idx)
        descfile += 'COPY_RIGHT_LOCATION = cprt_txt.txt\r\n'
        descfile += 'COPY_RIGHT_INFO = %s\r\n' % (self.map_copyright)
        descfile += 'ADDITIONAL_COMMENTS = created with geotiff2rmp.py\r\n'
        self.rmpfile.append_from_string('cvg_map.msf', descfile)

    def craft_copyright_file(self):
        if self.map_copyright_file:
            try:
                self.rmpfile.append_from_file('cprt_txt.txt', self.map_copyright_file)
            except:
                raise MapError('Cant read copyright file "%s"' % (self.map_copyright_file))
        else:
            self.rmpfile.append_from_string('cprt_txt.txt', self.map_copyright)

    def craft_ini_file(self):
        inifile = '[T_Layers]\r\n'
        idx = 0
        for i in range(0, len(self.maps)):
            for j in range(0, self.maps[i].num_topos):
                inifile += '%u=TOPO%u\r\n' % (idx, idx)
                idx += 1
        inifile += '\0'
        self.rmpfile.append_from_string('rmp.ini', inifile)

    def craft_resourse_files(self):
        for i in ['bmp2bit.ics', 'bmp4bit.ics']:
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
    def crop_image(img, tw, th, xpad, ypad):
        if xpad>=0:
            xcrop = 0
        else:
            xcrop = 256 - tw
        if ypad>=0:
            ycrop = 0
        else:
            ycrop = 256 - th
        img = Image.open(img)
        new_img = Image.new("RGB", (256, 256))
        new_img.paste(img, (xcrop, ycrop))
        o_img = io.BytesIO()
        new = new_img.save(o_img, 'JPEG')
        return o_img.getvalue()

    def craft_tiles(self, rmap, idx, tiles_offset, tiles_size):
        num_tiles = tiles_size[0]*tiles_size[1]

        a00name = 'topo%u.a00' % (idx)
        a00 = self.rmpfile.get_appender(a00name)
        a00.write(struct.pack('I', num_tiles))
        offsets = [4]

        for ix in range(tiles_offset[0], tiles_offset[0]+tiles_size[0]):
            if self.show_progress:
                progress(100*ix/float(rmap.size_in_tiles[0]))
            for iy in range(tiles_offset[1], tiles_offset[1]+tiles_size[1]):
                (x, tw, xpad) = self.get_tile_geometry(ix, rmap.diff[0], rmap.size[0])
                (y, th, ypad) = self.get_tile_geometry(iy, rmap.diff[1], rmap.size[1])
                gdal_translate(rmap.filename, self.temp_tile, self.jpeg_quality, x, y, tw, th, rmap.interp)
                if xpad!=0 or ypad!=0:
                    tile = self.crop_image(self.temp_tile, tw, th, xpad, ypad)
                else:
                    tile = open(self.temp_tile, 'rb').read()
                a00.write(struct.pack('I', len(tile)))
                a00.write(tile)
                offsets.append(offsets[-1] + len(tile) + 4)
        a00.close()
        if self.show_progress and tiles_offset[0]+tiles_size[0]==rmap.size_in_tiles[0]:
            progress(100)
        return offsets

    def craft_index(self, rmap, idx, offsets, tiles_offset, tiles_size):
        tlmname = 'topo%u.tlm' % (idx)
        tlmfile = tlmFile(self.rmpfile.get_appender(tlmname), rmap, tiles_offset, tiles_size)
        tlmfile.write_header()

        done = 0
        for ix in range(tiles_offset[0], tiles_offset[0]+tiles_size[0]):
            for iy in range(tiles_offset[1],tiles_offset[1]+tiles_size[1]):
                x = rmap.first_tile[0] + ix
                y = rmap.first_tile[1] + iy
                tlmfile.add_tile(x, y, offsets[done])
                done += 1

        tlmfile.finish()

    def run(self):
        self.rmpfile = rmpFile(self.outfile)
        self.craft_resourse_files()
        self.craft_copyright_file()
        for rmap in self.maps:
            for topo in range(0, rmap.num_topos):
                tiles_offset = (rmap.topo_len*topo, 0)
                tiles_size = (min(rmap.size_in_tiles[0]-tiles_offset[0], rmap.topo_len), rmap.size_in_tiles[1])
                offsets = self.craft_tiles(rmap, self.idx, tiles_offset, tiles_size)
                self.craft_index(rmap, self.idx, offsets, tiles_offset, tiles_size)
                self.idx += 1
        self.craft_description_file()
        self.craft_ini_file()
        self.rmpfile.finish()
        try:
            os.unlink(self.temp_tile)
            if os.path.exists(self.temp_tile+'.aux.xml'):
                os.unlink(self.temp_tile+'.aux.xml')
        except:
            pass
 
if __name__=='__main__':
    usage = "usage: %prog [options] <input map1> [input map2] ..."
    parser = OptionParser(usage=usage)
    parser.add_option("-o", "--outfile", dest="rmpfile", help="write result to rmp file")
    parser.add_option("-n", "--name", dest="name", help="map name [default: %default]", default='Map')
    parser.add_option("-g", "--group", dest="group", help="map group [default: %default]", default='Map')
    parser.add_option("-p", "--provider", dest="prov", help="map provider [default: %default]", default='Map')
    parser.add_option("-v", "--version", dest="version", help="map version [default: %default]", default='31')
    parser.add_option("-c", "--contact", dest="contact", help="map contact [default: %default]", default='Anonymous')
    parser.add_option("-l", "--copyright", dest="copyright", help="map copyright [default: %default]", default='(C) Anonymous. License CC-BY-4.0.')
    parser.add_option("-f", "--copyright-file", dest="copyrightfile", help="map copyright text file [default: none]", default='')
    parser.add_option("-r", "--rewrite", dest="rewrite", action="store_true", help="rewrite destination file even if it exists", default=False)
    (options, args) = parser.parse_args()
    if not options.rmpfile or len(args)<1:
        parser.print_usage()
        sys.exit(1)
    if os.path.exists(options.rmpfile) and not options.rewrite:
        sys.stderr.write('Destination rmp file "%s" already exists, use -r/--rewrite to overwrite\n' % (options.rmpfile))
        sys.exit(2)
    if gdalinfo == gdalinfo_shell:
        sys.stderr.write('Using dgal binaries (Slow!)\n')
    elif gdalinfo == gdalinfo_gdal:
        sys.stderr.write('Using dgal module and binaries (Slow!)\n')
    elif gdalinfo == gdalinfo_rasterio:
        sys.stderr.write('Using rasterio module (Fast!)\n')
    converter = rmpConverter(options.rmpfile, options.name, options.group, options.prov, options.version, options.contact, options.copyright, options.copyrightfile, show_progress=True)
    for mapfile in args:
        rmap = mapFile(mapfile)
        converter.add_map(rmap)
    converter.run()

