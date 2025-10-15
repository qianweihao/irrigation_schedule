#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灌溉计划API服务
提供单一接口支持文件上传和灌溉计划生成
"""

import os
import sys
import json
import shutil
import tempfile
import hashlib
import time
import gc
from typing import List, Optional, Dict, Any
from pathlib import Path
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入现有模块
from pipeline import IrrigationPipeline

# 全局缓存和线程池
_cache = {}
_cache_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2)  # 限制并发数

# 设置UTF-8编码（Windows兼容）
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

app = FastAPI(
    title="灌溉计划API",
    description="农场灌溉计划生成服务",
    version="1.0.0"
)

# 配置常量
GZP_FARM_DIR = os.path.join(os.path.dirname(__file__), "gzp_farm")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

class IrrigationRequest(BaseModel):
    """灌溉计划请求模型"""
    farm_id: str
    target_depth_mm: float = 90.0
    pumps: Optional[str] = None
    zones: Optional[str] = None
    merge_waterlevels: bool = True
    print_summary: bool = True

class IrrigationResponse(BaseModel):
    """灌溉计划响应模型"""
    success: bool
    message: str
    plan: Optional[dict] = None
    summary: Optional[str] = None

def generate_cache_key(farm_id: str, target_depth_mm: float, pumps: str, zones: str, 
                      merge_waterlevels: bool, print_summary: bool) -> str:
    """生成缓存键"""
    key_data = f"{farm_id}_{target_depth_mm}_{pumps}_{zones}_{merge_waterlevels}_{print_summary}"
    return hashlib.md5(key_data.encode()).hexdigest()

def get_from_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    """从缓存获取数据"""
    with _cache_lock:
        if cache_key in _cache:
            cache_data = _cache[cache_key]
            # 检查缓存是否过期（5分钟）
            if time.time() - cache_data['timestamp'] < 300:
                return cache_data['data']
            else:
                del _cache[cache_key]
    return None

def set_cache(cache_key: str, data: Dict[str, Any]):
    """设置缓存数据"""
    with _cache_lock:
        # 限制缓存大小，最多保存10个结果
        if len(_cache) >= 10:
            oldest_key = min(_cache.keys(), key=lambda k: _cache[k]['timestamp'])
            del _cache[oldest_key]
        
        _cache[cache_key] = {
            'data': data,
            'timestamp': time.time()
        }

def cleanup_resources():
    """清理资源"""
    gc.collect()  # 强制垃圾回收

def validate_shp_files(files: List[UploadFile]) -> bool:
    """验证上传的文件是否为有效的shapefile组合"""
    if not files:
        return True  # 允许不上传文件，使用现有数据
    
    # 检查文件扩展名
    extensions = set()
    for file in files:
        if file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            extensions.add(ext)
    
    # shapefile至少需要.shp, .dbf, .shx文件
    required_exts = {'.shp', '.dbf', '.shx'}
    return required_exts.issubset(extensions)

def backup_existing_files() -> str:
    """备份现有的gzp_farm文件"""
    if not os.path.exists(GZP_FARM_DIR):
        return ""
    
    backup_dir = tempfile.mkdtemp(prefix="gzp_farm_backup_")
    if os.listdir(GZP_FARM_DIR):
        shutil.copytree(GZP_FARM_DIR, os.path.join(backup_dir, "gzp_farm"))
    return backup_dir

def restore_files(backup_dir: str):
    """恢复备份的文件"""
    if backup_dir and os.path.exists(backup_dir):
        backup_gzp = os.path.join(backup_dir, "gzp_farm")
        if os.path.exists(backup_gzp):
            if os.path.exists(GZP_FARM_DIR):
                shutil.rmtree(GZP_FARM_DIR)
            shutil.copytree(backup_gzp, GZP_FARM_DIR)
        shutil.rmtree(backup_dir)

def save_uploaded_files(files: List[UploadFile]) -> bool:
    """保存上传的文件到gzp_farm目录"""
    try:
        # 确保目录存在
        os.makedirs(GZP_FARM_DIR, exist_ok=True)
        
        # 清理现有的shapefile相关文件
        for filename in os.listdir(GZP_FARM_DIR):
            if any(filename.endswith(ext) for ext in ['.shp', '.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx']):
                os.remove(os.path.join(GZP_FARM_DIR, filename))
        
        # 保存新文件
        for file in files:
            if file.filename:
                file_path = os.path.join(GZP_FARM_DIR, file.filename)
                with open(file_path, "wb") as f:
                    content = file.file.read()
                    f.write(content)
                file.file.seek(0)  # 重置文件指针
        
        return True
    except Exception as e:
        print(f"保存文件失败: {e}")
        return False

@app.post("/api/irrigation/plan-with-upload", response_model=IrrigationResponse)
async def generate_irrigation_plan_with_upload(
    farm_id: str = Form("13944136728576"),
    target_depth_mm: float = Form(90.0),
    pumps: Optional[str] = Form(None),
    zones: Optional[str] = Form(None),
    merge_waterlevels: bool = Form(True),
    print_summary: bool = Form(True),
    files: List[UploadFile] = File(default=[])
):
    """生成灌溉计划（支持文件上传）"""
    backup_dir = ""
    
    try:
        print(f"开始处理灌溉计划请求 - farm_id: {farm_id}, target_depth_mm: {target_depth_mm}")
        
        # 生成缓存键
        cache_key = generate_cache_key(
            farm_id, target_depth_mm, pumps or "", zones or "", 
            merge_waterlevels, print_summary
        )
        
        # 如果没有文件上传，尝试从缓存获取结果
        if not files or all(not f.filename for f in files):
            cached_result = get_from_cache(cache_key)
            if cached_result:
                print(f"从缓存返回结果 - cache_key: {cache_key}")
                cleanup_resources()  # 清理资源
                return IrrigationResponse(**cached_result)
        
        # 验证上传的文件
        if files and files[0].filename:  # 检查是否真的有文件上传
            print(f"检测到文件上传，文件数量: {len(files)}")
            for file in files:
                print(f"上传文件: {file.filename}")
            
            if not validate_shp_files(files):
                print("文件验证失败：无效的shapefile文件组合")
                raise HTTPException(
                    status_code=400, 
                    detail="无效的shapefile文件组合，需要包含.shp, .dbf, .shx文件"
                )
            
            print("文件验证通过")
            
            # 备份现有文件
            print("开始备份现有文件")
            backup_dir = backup_existing_files()
            print(f"备份目录: {backup_dir}")
            
            # 保存上传的文件
            print("开始保存上传的文件")
            if not save_uploaded_files(files):
                print("文件保存失败，恢复备份")
                if backup_dir:
                    restore_files(backup_dir)
                raise HTTPException(status_code=500, detail="文件保存失败")
            print("文件保存成功")
        else:
            print("未检测到文件上传，使用现有数据")
        
        # 构建pipeline参数
        kwargs = {
            'input_dir': GZP_FARM_DIR,
            'output_dir': OUTPUT_DIR,
            'config_file': None,
            'pumps': pumps,
            'zones': zones,
            'merge_waterlevels': merge_waterlevels,
            'print_summary': print_summary
        }
        print(f"Pipeline参数: {kwargs}")
        
        # 更新auto_config_params.yaml中的farm_id和target_depth_mm
        config_params_file = os.path.join(os.path.dirname(__file__), "auto_config_params.yaml")
        print(f"配置文件路径: {config_params_file}")
        
        try:
            if os.path.exists(config_params_file):
                import yaml
                print("读取配置文件")
                with open(config_params_file, 'r', encoding='utf-8') as f:
                    config_params = yaml.safe_load(f)
                
                config_params['default_farm_id'] = farm_id
                config_params['default_target_depth_mm'] = target_depth_mm
                
                print("更新配置文件")
                with open(config_params_file, 'w', encoding='utf-8') as f:
                    yaml.dump(config_params, f, ensure_ascii=False, indent=2)
                print("配置文件更新成功")
            else:
                print("配置文件不存在，跳过更新")
        except Exception as config_error:
            print(f"配置文件处理错误: {config_error}")
            # 配置文件错误不应该阻止主流程
        
        # 运行灌溉计划生成
        print("开始运行灌溉计划生成")
        try:
            pipeline = IrrigationPipeline()
            success = pipeline.run_pipeline(**kwargs)
            print(f"Pipeline执行结果: success={success}")
        except Exception as pipeline_error:
            print(f"Pipeline执行异常: {pipeline_error}")
            if backup_dir:
                print("恢复备份文件")
                restore_files(backup_dir)
            raise HTTPException(status_code=500, detail=f"灌溉计划生成异常: {str(pipeline_error)}")
        
        if not success:
            print("Pipeline执行失败")
            if backup_dir:
                print("恢复备份文件")
                restore_files(backup_dir)
            raise HTTPException(status_code=500, detail="灌溉计划生成失败")
        
        # 读取生成的计划文件（查找最新的irrigation_plan_*.json文件）
        plan_data = None
        if os.path.exists(OUTPUT_DIR):
            import glob
            plan_files = glob.glob(os.path.join(OUTPUT_DIR, "irrigation_plan_*.json"))
            if plan_files:
                # 获取最新的文件
                latest_plan_file = max(plan_files, key=os.path.getmtime)
                print(f"读取计划文件: {latest_plan_file}")
                try:
                    with open(latest_plan_file, 'r', encoding='utf-8') as f:
                        plan_data = json.load(f)
                    print(f"成功读取计划数据，包含 {len(plan_data) if plan_data else 0} 项")
                except Exception as e:
                    print(f"读取计划文件失败: {e}")
            else:
                print("未找到灌溉计划文件")
        
        # 清理备份
        if backup_dir:
            shutil.rmtree(backup_dir)
        
        # 准备响应数据
        response_data = {
            "success": True,
            "message": "灌溉计划生成成功",
            "plan": plan_data,
            "summary": "灌溉计划生成成功" if print_summary else None
        }
        
        # 保存到缓存（仅当没有文件上传时）
        if not files or all(not f.filename for f in files):
            set_cache(cache_key, response_data)
            print(f"结果已保存到缓存 - cache_key: {cache_key}")
        
        # 清理资源
        cleanup_resources()
        
        return IrrigationResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        # 恢复备份文件
        if backup_dir:
            restore_files(backup_dir)
        
        # 清理资源
        cleanup_resources()
        
        raise HTTPException(
            status_code=500, 
            detail=f"服务器内部错误: {str(e)}"
        )

@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy", "message": "灌溉计划API服务运行正常"}

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "灌溉计划API服务",
        "version": "1.0.0",
        "endpoints": {
            "POST /api/irrigation/plan-with-upload": "生成灌溉计划（支持文件上传）",
            "GET /api/health": "健康检查",
            "GET /docs": "API文档"
        }
    }

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="灌溉计划API服务")
    parser.add_argument("--host", default="127.0.0.1", help="服务器地址")
    parser.add_argument("--port", type=int, default=8000, help="服务器端口")
    parser.add_argument("--reload", action="store_true", help="开发模式（自动重载）")
    
    args = parser.parse_args()
    
    print(f"启动灌溉计划API服务...")
    print(f"服务地址: http://{args.host}:{args.port}")
    print(f"API文档: http://{args.host}:{args.port}/docs")
    
    uvicorn.run(
        "api_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload
    )