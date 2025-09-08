import geopandas as gpd
import os

outdir = "gzp_farm"
os.makedirs(outdir, exist_ok=True)
shp_path = os.path.join(outdir, "港中坪水路.shp")
gdf = gpd.read_file(shp_path)
outpath = os.path.join(outdir, '港中坪水路_code.geojson')
gdf.to_file(outpath)