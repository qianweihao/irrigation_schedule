#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
农场GIS数据转换工具
将Shapefile格式转换为GeoJSON格式
"""
import geopandas as gpd
import os
import glob
import sys
import io

def convert_shapefiles_to_geojson(input_dir="data/gzp_farm", output_dir=None):
    """
    将指定目录下的所有Shapefile转换为GeoJSON格式
    
    Args:
        input_dir: 输入目录路径，默认为"data/gzp_farm"
        output_dir: 输出目录路径，默认与输入目录相同
    
    Returns:
        int: 成功转换的文件数量
    """
    # 设置输出编码以解决Windows命令行中文显示问题
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    if output_dir is None:
        output_dir = input_dir
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 自动检索文件夹下的所有shp文件
    shp_files = glob.glob(os.path.join(input_dir, "*.shp"))
    
    if not shp_files:
        print(f"在 {input_dir} 文件夹中未找到任何 .shp 文件")
        return 0
    
    print(f"找到 {len(shp_files)} 个 .shp 文件")
    converted_count = 0
    
    for shp_path in shp_files:
        try:
            # 读取shp文件
            gdf = gpd.read_file(shp_path)
            
            # 生成输出文件名：原文件名_code.geojson
            base_name = os.path.splitext(os.path.basename(shp_path))[0]
            outpath = os.path.join(output_dir, f'{base_name}_code.geojson')
            
            # 转换并保存为geojson
            gdf.to_file(outpath)
            print(f"已转换: {os.path.basename(shp_path)} -> {os.path.basename(outpath)}")
            converted_count += 1
            
        except Exception as e:
            print(f"转换失败 {os.path.basename(shp_path)}: {e}")
    
    print(f"转换完成！共转换 {converted_count}/{len(shp_files)} 个文件")
    return converted_count

if __name__ == "__main__":
    # 兼容旧的调用方式
    import argparse
    parser = argparse.ArgumentParser(description="转换Shapefile为GeoJSON")
    parser.add_argument("--input-dir", default="data/gzp_farm", help="输入目录")
    parser.add_argument("--output-dir", default=None, help="输出目录（默认与输入目录相同）")
    args = parser.parse_args()
    
    convert_shapefiles_to_geojson(args.input_dir, args.output_dir)