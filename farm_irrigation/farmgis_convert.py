import geopandas as gpd
import os
import glob
import sys
import io

# 设置输出编码以解决Windows命令行中文显示问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

outdir = "gzp_farm"
os.makedirs(outdir, exist_ok=True)

# 自动检索gzp_farm文件夹下的所有shp文件
shp_files = glob.glob(os.path.join(outdir, "*.shp"))

if not shp_files:
    print(f"在 {outdir} 文件夹中未找到任何 .shp 文件")
else:
    print(f"找到 {len(shp_files)} 个 .shp 文件")
    
    for shp_path in shp_files:
        try:
            # 读取shp文件
            gdf = gpd.read_file(shp_path)
            
            # 生成输出文件名：原文件名_code.geojson
            base_name = os.path.splitext(os.path.basename(shp_path))[0]
            outpath = os.path.join(outdir, f'{base_name}_code.geojson')
            
            # 转换并保存为geojson
            gdf.to_file(outpath)
            print(f"已转换: {os.path.basename(shp_path)} -> {os.path.basename(outpath)}")
            
        except Exception as e:
            print(f"转换失败 {os.path.basename(shp_path)}: {e}")

print("转换完成！")