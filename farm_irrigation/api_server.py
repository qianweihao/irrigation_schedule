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
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# 配置日志（修复编码问题）
import os
# 基于项目根目录计算日志路径
_log_dir = os.path.join(os.path.dirname(__file__), 'data', 'execution_logs')
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(_log_dir, 'api_server.log'), encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入现有模块
from src.core.pipeline import IrrigationPipeline
from src.core.farm_irr_full_device_modified import farmcfg_from_json_select, generate_multi_pump_scenarios
from src.api.batch_regeneration_api import (
    BatchModificationRequest, 
    BatchRegenerationResponse, 
    PumpAssignment,
    TimeModification,
    create_batch_regeneration_endpoint,
    create_batch_info_endpoint,
    generate_batch_cache_key
)

# 导入动态执行模块
from src.api.dynamic_execution_api import (
    DynamicExecutionRequest,
    DynamicExecutionResponse,
    ExecutionStatusResponse,
    CurrentExecutionIdResponse,
    WaterLevelUpdateRequest,
    WaterLevelUpdateResponse,
    ManualRegenerationRequest,
    ManualRegenerationResponse,
    ExecutionHistoryResponse,
    create_dynamic_execution_endpoints
)

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
GZP_FARM_DIR = os.path.join(os.path.dirname(__file__), "data", "gzp_farm")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data", "output")

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

class MultiPumpRequest(BaseModel):
    """多水泵方案请求模型"""
    config_file: str
    active_pumps: Optional[List[str]] = None
    zone_ids: Optional[List[str]] = None
    use_realtime_wl: bool = False
    min_fields_trigger: Optional[int] = None  # 触发灌溉的最小田块数量，None表示使用配置文件中的值

class MultiPumpResponse(BaseModel):
    """多水泵方案响应模型"""
    scenarios: List[dict]
    analysis: dict
    total_scenarios: int

def generate_cache_key(farm_id: str, target_depth_mm: float, pumps: str, zones: str, 
                      merge_waterlevels: bool, print_summary: bool, multi_pump_scenarios: bool = False, 
                      custom_waterlevels: str = "") -> str:
    """生成缓存键"""
    key_data = f"{farm_id}_{target_depth_mm}_{pumps}_{zones}_{merge_waterlevels}_{print_summary}_{multi_pump_scenarios}_{custom_waterlevels}"
    return hashlib.md5(key_data.encode()).hexdigest()

def get_from_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    """从缓存获取数据"""
    with _cache_lock:
        if cache_key in _cache:
            cache_data = _cache[cache_key]
            # 检查缓存是否过期（5分钟）
            if time.time() - cache_data['timestamp'] < 60:
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
    multi_pump_scenarios: bool = Form(False),
    custom_waterlevels: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[])
):
    """生成灌溉计划（支持文件上传）"""
    backup_dir = ""
    
    try:
        print(f"开始处理灌溉计划请求 - farm_id: {farm_id}, target_depth_mm: {target_depth_mm}")
        
        # 生成缓存键
        cache_key = generate_cache_key(
            farm_id, target_depth_mm, pumps or "", zones or "", 
            merge_waterlevels, print_summary, multi_pump_scenarios, custom_waterlevels or ""
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
            'print_summary': print_summary,
            'multi_pump_scenarios': multi_pump_scenarios,
            'custom_waterlevels': custom_waterlevels
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

@app.post("/api/irrigation/multi-pump-scenarios", response_model=MultiPumpResponse)
async def generate_multi_pump_scenarios_api(request: MultiPumpRequest):
    """生成多水泵方案对比"""
    try:
        print(f"开始处理多水泵方案请求 - config_file: {request.config_file}")
        
        # 检查配置文件是否存在
        config_path = os.path.join(os.path.dirname(__file__), request.config_file)
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail=f"配置文件不存在: {request.config_file}")
        
        # 加载配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        # 创建农场配置
        cfg = farmcfg_from_json_select(
            config_data,
            active_pumps=request.active_pumps,
            zone_ids=request.zone_ids,
            use_realtime_wl=request.use_realtime_wl
        )
        
        # 确定触发阈值（优先使用请求参数，否则使用配置文件中的值）
        min_fields_trigger = request.min_fields_trigger
        if min_fields_trigger is None:
            min_fields_trigger = config_data.get('irrigation_trigger_config', {}).get('min_fields_trigger', 1)
        
        # 生成多水泵方案
        scenarios_result = generate_multi_pump_scenarios(cfg, min_fields_trigger=min_fields_trigger)
        
        print(f"多水泵方案生成成功，共 {scenarios_result.get('total_scenarios', 0)} 个方案（触发阈值: {min_fields_trigger}个田块）")
        
        return MultiPumpResponse(
            scenarios=scenarios_result.get('scenarios', []),
            analysis=scenarios_result.get('analysis', {}),
            total_scenarios=scenarios_result.get('total_scenarios', 0)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"多水泵方案生成失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"多水泵方案生成失败: {str(e)}"
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
            "POST /api/irrigation/plan-with-upload": "生成灌溉计划（支持文件上传和多水泵方案对比）",
            "POST /api/irrigation/multi-pump-scenarios": "生成多水泵方案对比",
            "POST /api/irrigation/regenerate-batch": "批次重新生成（支持田块、水泵和时间修改）",
            "GET /api/irrigation/batch-info/{plan_id}": "获取批次详细信息",
            "POST /api/irrigation/dynamic-execution/start": "启动动态批次执行",
            "POST /api/irrigation/dynamic-execution/stop": "停止动态批次执行",
            "GET /api/irrigation/dynamic-execution/status": "获取动态执行状态",
            "POST /api/irrigation/dynamic-execution/update-waterlevels": "手动更新水位数据",
            "POST /api/irrigation/dynamic-execution/regenerate-batch": "手动重新生成批次",
            "GET /api/irrigation/dynamic-execution/history": "获取执行历史",
            "GET /api/irrigation/dynamic-execution/waterlevel-summary": "获取水位数据摘要",
            "GET /api/irrigation/dynamic-execution/field-trend/{field_id}": "获取田块水位趋势分析",
            "GET /api/health": "健康检查",
            "GET /docs": "API文档"
        }
    }

# 创建批次重新生成端点
regenerate_batch_plan_func = create_batch_regeneration_endpoint()

# 创建批次信息查询端点
get_batch_info_func = create_batch_info_endpoint()

# 创建动态执行端点
dynamic_execution_endpoints = create_dynamic_execution_endpoints()

@app.post("/api/irrigation/regenerate-batch", response_model=BatchRegenerationResponse)
async def regenerate_batch_plan(request: BatchModificationRequest):
    """
    批次重新生成端点
    
    根据前端的田块修改请求（添加或移除田块），重新生成灌溉批次计划。
    支持田块修改、水泵分配和时间调整。
    
    - **original_plan_id**: 原始计划ID或文件路径
    - **field_modifications**: 田块修改列表，每项包含field_id、action（add/remove）、可选的custom_water_level
    - **pump_assignments**: 水泵分配列表，每项包含batch_index和pumps
    - **time_modifications**: 时间修改列表，每项包含batch_index、start_time和duration
    - **regeneration_params**: 可选的重新生成参数
    
    返回包含原始计划、修改后计划和修改摘要的响应。
    """
    # 生成缓存键
    cache_key = generate_batch_cache_key(request)
    
    # 尝试从缓存获取结果
    cached_result = get_from_cache(cache_key)
    if cached_result:
        print(f"从缓存返回批次重新生成结果 - cache_key: {cache_key}")
        return BatchRegenerationResponse(**cached_result)
    
    # 执行批次重新生成
    try:
        result = await regenerate_batch_plan_func(request)
        
        # 将结果保存到缓存
        response_data = result.dict()
        set_cache(cache_key, response_data)
        print(f"批次重新生成结果已保存到缓存 - cache_key: {cache_key}")
        
        return result
        
    except Exception as e:
        print(f"批次重新生成失败: {str(e)}")
        raise

@app.get("/api/irrigation/batch-info/{plan_id}")
async def get_batch_info(plan_id: str):
    """
    获取批次详细信息端点
    
    根据计划ID获取批次的详细信息，包括每个批次的水泵配置和时间信息。
    
    - **plan_id**: 计划ID或文件路径
    
    返回包含所有批次详细信息的响应。
    """
    try:
        result = await get_batch_info_func(plan_id)
        return result
        
    except Exception as e:
        print(f"获取批次信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取批次信息失败: {str(e)}")

# 动态执行端点
@app.post("/api/irrigation/dynamic-execution/start", response_model=DynamicExecutionResponse)
async def start_dynamic_execution(request: DynamicExecutionRequest):
    """启动动态批次执行"""
    return await dynamic_execution_endpoints["start_dynamic_execution"](request)

@app.post("/api/irrigation/dynamic-execution/stop", response_model=DynamicExecutionResponse)
async def stop_dynamic_execution():
    """停止动态批次执行"""
    return await dynamic_execution_endpoints["stop_dynamic_execution"]()

@app.get("/api/irrigation/dynamic-execution/status", response_model=ExecutionStatusResponse)
async def get_execution_status():
    """获取动态执行状态"""
    return await dynamic_execution_endpoints["get_execution_status"]()

@app.get("/api/irrigation/dynamic-execution/current-id", response_model=CurrentExecutionIdResponse)
async def get_current_execution_id():

    return await dynamic_execution_endpoints["get_current_execution_id"]()

@app.post("/api/irrigation/dynamic-execution/update-waterlevels", response_model=WaterLevelUpdateResponse)
async def update_waterlevels(request: WaterLevelUpdateRequest):
    """手动更新水位数据"""
    return await dynamic_execution_endpoints["update_water_levels"](request)

@app.post("/api/irrigation/dynamic-execution/regenerate-batch", response_model=ManualRegenerationResponse)
async def regenerate_batch_manual(request: ManualRegenerationRequest):
    """手动重新生成批次"""
    return await dynamic_execution_endpoints["manual_regenerate_batch"](request)

@app.get("/api/irrigation/dynamic-execution/history", response_model=ExecutionHistoryResponse)
async def get_execution_history(
    limit: int = 10,
    offset: int = 0,
    field_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> ExecutionHistoryResponse:
    """获取执行历史"""
    try:
        return await dynamic_execution_endpoints["get_execution_history"](limit)
    except Exception as e:
        logger.error(f"获取执行历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/irrigation/dynamic-execution/waterlevel-summary")
async def get_water_level_summary(farm_id: str = "default", field_ids: Optional[List[str]] = None):
    """获取水位数据摘要"""
    try:
        return await dynamic_execution_endpoints["get_water_level_summary"](farm_id, field_ids)
    except Exception as e:
        logger.error(f"获取水位摘要失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/irrigation/dynamic-execution/field-trend/{field_id}")
async def get_field_trend_analysis(field_id: str, hours: int = 48):
    """获取田块水位趋势分析"""
    try:
        return await dynamic_execution_endpoints["get_field_trend_analysis"](field_id, hours)
    except Exception as e:
        logger.error(f"获取田块趋势分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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