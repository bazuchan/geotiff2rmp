GeoTiff2RMP is a simple command-line converter from GeoTiff raster format with WGS84 projection to RMP fromat used by Magellan Triton/Explorist GPS units.

Code was based on RMPCreator project https://github.com/antalos/RMPCreator

Dependencies:
	- python2.7
	- gdal binaries
	- pillow (python-pil)
	- rasterio (optional, https://github.com/mapbox/rasterio)
	- python-gdal (optional)

Restrictions:
	- input map should be in WGS84 projection
	- works only on linux (other OS untested)
	- license is unclear, due to no license file in RMPCreator project

Example usage:
	- Convert map to WGS84 projection: gdalwarp -t_srs WGS84 -tr 0.00013 0.000055 -overwrite Arbalet-MO_All_300DPI.map arbalet_wgs84.tiff
	- Run GeoTiff2RMP: ./geotiff2rmp.py -o arbalet.rmp arbalet_wgs84.tiff
	- Upload map to your Magellan unit and mark it to display

