#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主动态执行API
整合所有动态执行功能，提供统一的接口

功能包括：
1. 动态批次执行管理
2. 实时水位数据获取和管理
3. 智能计划重新生成
4. 执行状态监控和历史记录
5. 田块水位趋势分析

作者: Assistant
创建时间: 2024-12-19
"""

import asyncio
import logging
import os
import json
import glob
import shutil
import tempfile
import hashlib
import time
import threading
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Form, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import geopandas as gpd

# 导入动态执行相关模块
from batch_execution_scheduler import BatchExecutionScheduler
from dynamic_waterlevel_manager import DynamicWaterLevelManager
from dynamic_plan_regenerator import DynamicPlanRegenerator
from execution_status_manager import ExecutionStatusManager

# 导入API模型和函数
from dynamic_execution_api import (
    DynamicExecutionRequest, DynamicExecutionResponse,
    ExecutionStatusResponse, WaterLevelUpdateRequest, WaterLevelUpdateResponse,
    ManualRegenerationRequest, ManualRegenerationResponse,
    ExecutionHistoryResponse,
    start_dynamic_execution, stop_dynamic_execution, get_execution_status,
    update_water_levels, manual_regenerate_batch, get_execution_history,
    get_water_level_summary, get_field_trend_analysis, get_water_level_history
)

# 导入批次重新生成相关模块
from batch_regeneration_api import (
    BatchModificationRequest, BatchRegenerationResponse,
    create_batch_regeneration_endpoint, generate_batch_cache_key
)

# 导入多水泵方案相关模块
from farm_irr_full_device_modified import farmcfg_from_json_select, generate_multi_pump_scenarios

# 全局缓存和线程池
_cache = {}
_cache_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2)  # 限制并发数

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('main_dynamic_execution.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="智能灌溉动态执行系统",
    description="基于实时水位数据的智能灌溉批次动态执行系统",
    version="1.0.0"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局变量存储系统组件
_scheduler: Optional[BatchExecutionScheduler] = None
_waterlevel_manager: Optional[DynamicWaterLevelManager] = None
_plan_regenerator: Optional[DynamicPlanRegenerator] = None
_status_manager: Optional[ExecutionStatusManager] = None

# 缓存相关函数
def generate_cache_key(farm_id: str, target_depth_mm: float, pumps: str, zones: str, 
                      merge_waterlevels: bool, print_summary: bool, multi_pump_scenarios: bool = False, 
                      custom_waterlevels: str = "", file_hash: str = "") -> str:
    """生成缓存键"""
    key_data = f"{farm_id}_{target_depth_mm}_{pumps}_{zones}_{merge_waterlevels}_{print_summary}_{multi_pump_scenarios}_{custom_waterlevels}_{file_hash}"
    return hashlib.md5(key_data.encode()).hexdigest()

def generate_batch_cache_key(original_plan_id: str, field_modifications: str, 
                           pump_assignments: str, time_modifications: str, 
                           regeneration_params: str) -> str:
    """为批次重新生成生成缓存键"""
    key_data = f"{original_plan_id}_{field_modifications}_{pump_assignments}_{time_modifications}_{regeneration_params}"
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

class SystemStatusResponse(BaseModel):
    """系统状态响应模型"""
    system_status: str
    scheduler_initialized: bool
    waterlevel_manager_initialized: bool
    plan_regenerator_initialized: bool
    status_manager_initialized: bool
    current_time: str
    uptime_seconds: float

class SystemInitRequest(BaseModel):
    """系统初始化请求模型"""
    config_path: str = "config.json"
    farm_id: str = "default_farm"
    enable_realtime_waterlevels: bool = True
    database_path: str = "execution_status.db"
    cache_file_path: str = "water_level_cache.json"

class IrrigationPlanRequest(BaseModel):
    """生成灌溉计划请求模型"""
    farm_id: str
    config_path: Optional[str] = None
    output_dir: Optional[str] = None
    scenario_name: Optional[str] = None
    multi_pump_scenarios: Optional[bool] = False

class IrrigationPlanResponse(BaseModel):
    """生成灌溉计划响应模型"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    plan_id: Optional[str] = None
    multi_pump_scenarios: Optional[Dict[str, Any]] = None

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

class OptimizationRequest(BaseModel):
    """优化请求模型"""
    original_plan_id: str
    optimization_goals: List[str] = ["cost_minimization", "time_minimization", "balanced"]
    constraints: Optional[Dict[str, Any]] = {}

class OptimizationResponse(BaseModel):
    """优化响应模型"""
    success: bool
    message: str
    total_scenarios: int
    scenarios: List[Dict[str, Any]]
    comparison: Dict[str, Any]
    base_plan_summary: Dict[str, Any]

class FieldModification(BaseModel):
    """田块修改信息"""
    field_id: str
    action: str  # 'add' 或 'remove'
    custom_water_level: Optional[float] = None

class PumpAssignment(BaseModel):
    """批次水泵分配信息"""
    batch_index: int
    pump_ids: List[str]

class TimeModification(BaseModel):
    """批次时间修改信息"""
    batch_index: int
    start_time_h: Optional[float] = None
    duration_h: Optional[float] = None

class BatchModificationRequest(BaseModel):
    """批次修改请求"""
    original_plan_id: str
    field_modifications: Optional[List[FieldModification]] = []
    pump_assignments: Optional[List[PumpAssignment]] = []
    time_modifications: Optional[List[TimeModification]] = []
    regeneration_params: Optional[Dict[str, Any]] = {}

class BatchRegenerationResponse(BaseModel):
    """批次重新生成响应"""
    success: bool
    message: str
    original_plan: Optional[Dict[str, Any]] = None
    modified_plan: Optional[Dict[str, Any]] = None
    modifications_summary: Dict[str, Any] = {}

class FieldAdjustment(BaseModel):
    """批次间田块调整信息"""
    field_id: str
    from_batch: int
    to_batch: int

class AdjustmentOptions(BaseModel):
    """调整选项"""
    recalculate_sequence: bool = True  # 是否重新计算灌溉顺序
    recalculate_timing: bool = True  # 是否重新计算时间
    maintain_pump_assignments: bool = True  # 是否保持水泵分配
    regenerate_commands: bool = True  # 是否重新生成命令

class BatchAdjustmentRequest(BaseModel):
    """批次间田块调整请求"""
    plan_id: str
    field_adjustments: List[FieldAdjustment]
    options: Optional[AdjustmentOptions] = AdjustmentOptions()

class BatchAdjustmentResponse(BaseModel):
    """批次间田块调整响应"""
    success: bool
    message: str
    original_plan: Optional[Dict[str, Any]] = None
    adjusted_plan: Optional[Dict[str, Any]] = None
    changes_summary: Dict[str, Any] = {}
    validation: Dict[str, Any] = {}
    output_file: Optional[str] = None

# 系统启动时间
_system_start_time = datetime.now()

# 文件上传相关常量
GZP_FARM_DIR = os.path.join(os.path.dirname(__file__), "gzp_farm")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# GeoJson相关常量
ROOT = os.path.abspath(os.path.dirname(__file__))
GEOJSON_DIR = os.path.join(ROOT, "gzp_farm")
VALVE_FILE = "港中坪阀门与节制闸_code.geojson"
FIELD_FILE = "港中坪田块_code.geojson"
WATERWAY_FILE = "港中坪水路_code.geojson"

# 标注后的文件（优先使用）
LABELED_DIR = os.path.join(ROOT, "labeled_output")
LABELED_FIELDS = os.path.join(LABELED_DIR, "fields_labeled.geojson")
LABELED_GATES = os.path.join(LABELED_DIR, "gates_labeled.geojson")
LABELED_SEGMENT = os.path.join(LABELED_DIR, "segments_labeled.geojson")

# GeoJson辅助函数
def _looks_like_lonlat(bounds):
    """检查边界是否像经纬度坐标"""
    try:
        minx, miny, maxx, maxy = bounds
        return -180 <= minx <= 180 and -90 <= miny <= 90 and -180 <= maxx <= 180 and -90 <= maxy <= 90
    except Exception:
        return False

# Scenario信息辅助函数
def get_scenario_info(scheduler=None):
    """
    获取当前计划的scenario信息
    
    Args:
        scheduler: 调度器实例，如果为None则使用全局调度器
        
    Returns:
        dict: 包含scenario_name, scenario_count, scenarios等信息的字典
    """
    if scheduler is None:
        global _scheduler
        scheduler = _scheduler
    
    if not scheduler:
        return {
            "scenario_name": "未知",
            "scenario_count": 0,
            "scenarios": [],
            "selected_scenario_index": 0
        }
    
    # 从调度器获取原始计划数据
    raw_plan_data = getattr(scheduler, 'raw_plan_data', None)
    if raw_plan_data:
        scenarios = raw_plan_data.get("scenarios", [])
    else:
        # 如果调度器没有raw_plan_data，查找最新的计划文件
        import json
        
        scenarios = []
        latest_plan_file = find_latest_plan_file()
        
        if latest_plan_file:
            try:
                with open(latest_plan_file, 'r', encoding='utf-8') as f:
                    file_data = json.load(f)
                scenarios = file_data.get("scenarios", [])
            except Exception as e:
                logger.warning(f"读取计划文件失败: {e}")
                scenarios = []
    
    scenario_count = len(scenarios)
    scenario_name = ""
    selected_scenario_index = 0
    
    if scenarios:
        # 使用第一个scenario
        first_scenario = scenarios[0]
        scenario_name = first_scenario.get("scenario_name", "默认场景")
        
        # 如果scenario_name为空，尝试生成一个描述性名称
        if not scenario_name or scenario_name.strip() == "":
            scenario_name = f"场景1"
    else:
        scenario_name = "顶层计划"
        scenario_count = 1  # 顶层计划算作1个scenario
    
    return {
        "scenario_name": scenario_name,
        "scenario_count": scenario_count,
        "scenarios": scenarios,
        "selected_scenario_index": selected_scenario_index
    }

def read_geo_ensure_wgs84(path: str) -> gpd.GeoDataFrame:
    """读取地理数据文件并确保为WGS84坐标系"""
    gdf = gpd.read_file(path)
    if gdf.empty:
        return gdf
    if gdf.crs is None:
        # 如果像经纬度，强设 WGS84；否则抛错提示重投影
        if _looks_like_lonlat(gdf.total_bounds):
            gdf = gdf.set_crs(epsg=4326)
        else:
            raise RuntimeError(f"{os.path.basename(path)} 无 CRS 且不像 WGS84，经纬度范围={gdf.total_bounds}")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    return gdf

def _first_existing(*paths):
    """返回第一个存在的文件路径"""
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None

def find_latest_plan_file(output_dir_path: str = None) -> Optional[str]:
    """
    动态查找最新的完整灌溉计划文件
    
    Args:
        output_dir_path: 输出目录路径，如果为None则使用默认output目录
        
    Returns:
        str: 最新计划文件的完整路径，如果没找到则返回None
    """
    from pathlib import Path
    
    if output_dir_path is None:
        script_dir = Path(__file__).parent
        output_dir = script_dir / "output"
    else:
        output_dir = Path(output_dir_path)
    
    if not output_dir.exists():
        logger.warning(f"输出目录不存在: {output_dir}")
        return None
    
    # 查找完整计划文件（排除手动重新生成的文件）
    plan_patterns = [
        "irrigation_plan_modified_*.json",
        "irrigation_plan_2*.json",
    ]
    
    all_plan_files = []
    for pattern in plan_patterns:
        all_plan_files.extend(output_dir.glob(pattern))
    
    if all_plan_files:
        # 按修改时间排序，选择最新的文件
        latest_plan = max(all_plan_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"找到最新计划文件: {latest_plan}")
        return str(latest_plan)
    
    logger.warning("未找到任何完整计划文件")
    return None

# 文件上传辅助函数
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
        logger.error(f"保存文件失败: {e}")
        return False

@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info("智能灌溉动态执行系统启动中...")
    
    # 初始化系统组件（使用默认配置）
    await initialize_system(SystemInitRequest())
    
    logger.info("智能灌溉动态执行系统启动完成")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("智能灌溉动态执行系统关闭中...")
    
    # 停止正在运行的执行
    global _scheduler
    if _scheduler and _scheduler.is_running:
        _scheduler.stop_execution()
    
    logger.info("智能灌溉动态执行系统已关闭")

async def initialize_system(request: SystemInitRequest) -> bool:
    """
    初始化系统组件
    
    Args:
        request: 初始化请求
        
    Returns:
        bool: 初始化是否成功
    """
    global _scheduler, _waterlevel_manager, _plan_regenerator, _status_manager
    
    try:
        logger.info("开始初始化系统组件...")
        
        # 初始化执行状态管理器
        _status_manager = ExecutionStatusManager(
            db_path=request.database_path,
            log_path="execution_logs"
        )
        logger.info("执行状态管理器初始化完成")
        
        # 初始化水位管理器
        _waterlevel_manager = DynamicWaterLevelManager(
            config_path=request.config_path,
            cache_file=request.cache_file_path
        )
        logger.info("水位管理器初始化完成")
        
        # 初始化计划重新生成器
        _plan_regenerator = DynamicPlanRegenerator(
            config_path=request.config_path,
            plan_template_path="plan_templates"
        )
        logger.info("计划重新生成器初始化完成")
        
        # 初始化批次执行调度器
        _scheduler = BatchExecutionScheduler(
            config_path=request.config_path,
            farm_id=request.farm_id,
            enable_realtime_waterlevels=request.enable_realtime_waterlevels,
            pre_execution_buffer_minutes=5
        )
        
        # 设置调度器的依赖组件
        _scheduler.waterlevel_manager = _waterlevel_manager
        _scheduler.plan_regenerator = _plan_regenerator
        _scheduler.status_manager = _status_manager
        
        logger.info("批次执行调度器初始化完成")
        
        logger.info("所有系统组件初始化成功")
        return True
        
    except Exception as e:
        logger.error(f"系统组件初始化失败: {e}")
        return False

# ==================== 系统管理API ====================

@app.post("/api/system/init", response_model=Dict[str, Any])
async def init_system(request: SystemInitRequest):
    """初始化系统"""
    try:
        success = await initialize_system(request)
        
        if success:
            return {
                "success": True,
                "message": "系统初始化成功",
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail="系统初始化失败")
            
    except Exception as e:
        logger.error(f"系统初始化失败: {e}")
        raise HTTPException(status_code=500, detail=f"系统初始化失败: {str(e)}")

@app.get("/api/system/status", response_model=SystemStatusResponse)
async def get_system_status():
    """获取系统状态"""
    try:
        global _scheduler, _waterlevel_manager, _plan_regenerator, _status_manager
        
        uptime = (datetime.now() - _system_start_time).total_seconds()
        
        return SystemStatusResponse(
            system_status="running",
            scheduler_initialized=_scheduler is not None,
            waterlevel_manager_initialized=_waterlevel_manager is not None,
            plan_regenerator_initialized=_plan_regenerator is not None,
            status_manager_initialized=_status_manager is not None,
            current_time=datetime.now().isoformat(),
            uptime_seconds=uptime
        )
        
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取系统状态失败: {str(e)}")

@app.post("/api/system/health-check")
async def health_check():
    """系统健康检查"""
    try:
        global _scheduler, _waterlevel_manager, _plan_regenerator, _status_manager
        
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "components": {
                "scheduler": "ok" if _scheduler else "not_initialized",
                "waterlevel_manager": "ok" if _waterlevel_manager else "not_initialized",
                "plan_regenerator": "ok" if _plan_regenerator else "not_initialized",
                "status_manager": "ok" if _status_manager else "not_initialized"
            }
        }
        
        # 检查是否有组件未初始化
        if any(status == "not_initialized" for status in health_status["components"].values()):
            health_status["status"] = "degraded"
        
        return health_status
        
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# ==================== 动态执行API ====================

@app.post("/api/execution/start", response_model=DynamicExecutionResponse)
async def start_execution(request: DynamicExecutionRequest):
    """启动动态执行"""
    return await start_dynamic_execution(request)

@app.post("/api/execution/stop", response_model=DynamicExecutionResponse)
async def stop_execution():
    """停止动态执行"""
    return await stop_dynamic_execution()

@app.get("/api/execution/status", response_model=ExecutionStatusResponse)
async def execution_status():
    """获取执行状态"""
    return await get_execution_status()

@app.get("/api/execution/history", response_model=ExecutionHistoryResponse)
async def execution_history(limit: int = 10):
    """获取执行历史"""
    return await get_execution_history(limit)

# ==================== 水位管理API ====================

@app.post("/api/water-levels/update", response_model=WaterLevelUpdateResponse)
async def update_water_level_data(request: WaterLevelUpdateRequest):
    """更新水位数据"""
    return await update_water_levels(request)

@app.get("/api/water-levels/summary")
async def water_level_summary(farm_id: str, field_ids: Optional[str] = None):
    """获取水位数据摘要"""
    field_id_list = field_ids.split(",") if field_ids else None
    return await get_water_level_summary(farm_id, field_id_list)

@app.get("/api/water-levels/trend/{field_id}")
async def field_trend_analysis(field_id: str, hours: int = 48):
    """获取田块水位趋势分析"""
    return await get_field_trend_analysis(field_id, hours)

@app.get("/api/water-levels/history")
async def water_level_history(farm_id: str, field_id: str, hours: int = 24):
    """获取田块水位历史数据"""
    return await get_water_level_history(farm_id, field_id, hours)

# ==================== 计划重新生成API ====================

@app.post("/api/regeneration/manual", response_model=ManualRegenerationResponse)
async def manual_regeneration(request: ManualRegenerationRequest):
    """手动重新生成批次"""
    return await manual_regenerate_batch(request)

@app.post("/api/regeneration/batch", response_model=BatchRegenerationResponse)
async def regenerate_batch_plan(request: BatchModificationRequest):
    """
    批次重新生成端点（支持缓存）
    
    根据前端的田块修改请求（添加或移除田块），重新生成灌溉批次计划。
    支持田块修改、水泵分配和时间调整。
    
    - **original_plan_id**: 原始计划ID或文件路径
    - **field_modifications**: 田块修改列表，每项包含field_id、action（add/remove）、可选的custom_water_level
    - **pump_assignments**: 水泵分配列表，每项包含batch_index和pump_ids
    - **time_modifications**: 时间修改列表，每项包含batch_index、start_time_h和duration_h
    - **regeneration_params**: 可选的重新生成参数
    
    返回包含原始计划、修改后计划和修改摘要的响应。
    """
    try:
        logger.info(f"开始批次重新生成 - plan_id: {request.original_plan_id}")
        
        # 生成缓存键
        cache_key = generate_batch_cache_key(
            original_plan_id=request.original_plan_id,
            field_modifications=str(request.field_modifications),
            pump_assignments=str(request.pump_assignments),
            time_modifications=str(request.time_modifications),
            regeneration_params=str(request.regeneration_params)
        )
        
        # 尝试从缓存获取结果
        cached_result = get_from_cache(cache_key)
        if cached_result:
            logger.info(f"从缓存返回批次重新生成结果 - cache_key: {cache_key}")
            return BatchRegenerationResponse(**cached_result)
        
        # 导入批次重新生成服务
        from batch_regeneration_api import BatchRegenerationService
        
        # 创建服务实例
        service = BatchRegenerationService()
        
        # 加载原始计划
        try:
            original_plan = service.load_original_plan(request.original_plan_id)
            if not original_plan:
                raise HTTPException(status_code=404, detail=f"未找到计划: {request.original_plan_id}")
        except Exception as e:
            logger.error(f"加载原始计划失败: {e}")
            raise HTTPException(status_code=404, detail=f"加载原始计划失败: {str(e)}")
        
        # 应用修改
        modified_plan = original_plan.copy()
        modifications_summary = {
            "field_modifications": [],
            "pump_assignments": [],
            "time_modifications": [],
            "total_changes": 0
        }
        
        # 处理田块修改
        if request.field_modifications:
            for mod in request.field_modifications:
                try:
                    if mod.action == "add":
                        # 添加田块到合适的批次
                        result = service._add_field_to_plan(modified_plan, mod.field_id, mod.custom_water_level)
                        modifications_summary["field_modifications"].append({
                            "field_id": mod.field_id,
                            "action": "add",
                            "result": result
                        })
                    elif mod.action == "remove":
                        # 从计划中移除田块
                        result = service._remove_field_from_plan(modified_plan, mod.field_id)
                        modifications_summary["field_modifications"].append({
                            "field_id": mod.field_id,
                            "action": "remove",
                            "result": result
                        })
                    modifications_summary["total_changes"] += 1
                except Exception as e:
                    logger.warning(f"田块修改失败 {mod.field_id}: {e}")
        
        # 处理水泵分配修改
        if request.pump_assignments:
            for assignment in request.pump_assignments:
                try:
                    result = service._update_pump_assignment(modified_plan, assignment.batch_index, assignment.pump_ids)
                    modifications_summary["pump_assignments"].append({
                        "batch_index": assignment.batch_index,
                        "pump_ids": assignment.pump_ids,
                        "result": result
                    })
                    modifications_summary["total_changes"] += 1
                except Exception as e:
                    logger.warning(f"水泵分配修改失败 batch {assignment.batch_index}: {e}")
        
        # 处理时间修改
        if request.time_modifications:
            try:
                # 使用apply_time_modifications批量处理所有时间修改（包含级联更新）
                modified_plan = service.apply_time_modifications(modified_plan, request.time_modifications)
                
                # 记录修改摘要
                for time_mod in request.time_modifications:
                    modifications_summary["time_modifications"].append({
                        "batch_index": time_mod.batch_index,
                        "start_time_h": time_mod.start_time_h,
                        "duration_h": time_mod.duration_h,
                        "result": "success"
                    })
                modifications_summary["total_changes"] += len(request.time_modifications)
            except Exception as e:
                logger.warning(f"时间修改失败: {e}")
                modifications_summary["time_modifications"].append({
                    "error": str(e)
                })
        
        # 保存修改后的计划
        try:
            output_file = service._save_modified_plan(modified_plan, request.original_plan_id)
            logger.info(f"修改后的计划已保存到: {output_file}")
        except Exception as e:
            logger.error(f"保存修改后的计划失败: {e}")
            raise HTTPException(status_code=500, detail=f"保存修改后的计划失败: {str(e)}")
        
        # 准备响应数据
        response_data = {
            "success": True,
            "message": f"批次计划重新生成成功，共进行了 {modifications_summary['total_changes']} 项修改",
            "original_plan": original_plan,
            "modified_plan": modified_plan,
            "modifications_summary": modifications_summary
        }
        
        # 将结果保存到缓存
        set_cache(cache_key, response_data)
        logger.info(f"批次重新生成结果已保存到缓存 - cache_key: {cache_key}")
        
        logger.info("批次重新生成完成")
        return BatchRegenerationResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批次重新生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"批次重新生成失败: {str(e)}")

@app.get("/api/regeneration/summary/{farm_id}")
async def regeneration_summary(farm_id: str):
    """获取重新生成摘要"""
    try:
        global _plan_regenerator
        if not _plan_regenerator:
            raise HTTPException(status_code=500, detail="计划重新生成器未初始化")
        
        stats = _plan_regenerator.get_regeneration_stats()
        stats["farm_id"] = farm_id
        stats["query_time"] = datetime.now().isoformat()
        
        return stats
        
    except Exception as e:
        logger.error(f"获取重新生成摘要失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取重新生成摘要失败: {str(e)}")

# ==================== 批次管理API ====================

@app.get("/api/batches")
async def get_batch_list():
    """获取批次列表"""
    try:
        global _scheduler
        if not _scheduler:
            raise HTTPException(status_code=500, detail="调度器未初始化")
        
        plan = _scheduler.get_current_plan()
        
        if not plan:
            # 尝试动态查找并加载最新的计划文件
            try:
                latest_plan_file = find_latest_plan_file()
                plan_loaded = False
                
                if latest_plan_file:
                    plan_loaded = _scheduler.load_irrigation_plan(latest_plan_file)
                    if plan_loaded:
                        plan = _scheduler.get_current_plan()
                        logger.info(f"成功加载计划文件: {latest_plan_file}")
                
                if not plan_loaded:
                    # 如果output目录没有文件，尝试加载根目录的plan.json作为备选
                    logger.warning("output目录中没有找到计划文件，尝试加载根目录的plan.json")
                    _scheduler.load_irrigation_plan("plan.json")
                    plan = _scheduler.get_current_plan()
                    logger.info("使用根目录plan.json作为备选")
                    
            except Exception as load_error:
                logger.error(f"加载计划文件失败: {load_error}")
                raise HTTPException(status_code=404, detail="当前没有执行计划，且无法加载任何计划文件")
        
        if not plan:
            raise HTTPException(status_code=404, detail="当前没有执行计划")
        
        batches = plan.get("batches", [])
        
        # 构建批次列表响应
        batch_list = []
        for batch in batches:
            batch_info = {
                "index": batch.get("index", 0),
                "area_mu": batch.get("area_mu", 0),
                "field_count": len(batch.get("fields", [])),
                "fields": [field.get("id", "") for field in batch.get("fields", [])],
                "segment_ids": list(set([field.get("segment_id", "") for field in batch.get("fields", []) if field.get("segment_id")]))
            }
            batch_list.append(batch_info)
        
        # 获取scenario信息
        scenario_info = get_scenario_info(_scheduler)
        
        return {
            "success": True,
            "total_batches": len(batch_list),
            "batches": batch_list,
            "farm_id": _scheduler.get_farm_id() if hasattr(_scheduler, 'get_farm_id') else "unknown",
            "scenario_name": scenario_info["scenario_name"],
            "scenario_count": scenario_info["scenario_count"],
            "selected_scenario_index": scenario_info["selected_scenario_index"],
            "query_time": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取批次列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取批次列表失败: {str(e)}")

@app.get("/api/batches/{batch_index}/details")
async def get_batch_details(batch_index: int):
    """获取批次详细信息"""
    try:
        global _scheduler
        if not _scheduler:
            raise HTTPException(status_code=500, detail="调度器未初始化")
        
        # 获取当前计划以验证批次索引
        plan = _scheduler.get_current_plan()
        if not plan:
            # 尝试动态查找并加载最新的计划文件
            try:
                latest_plan_file = find_latest_plan_file()
                plan_loaded = False
                
                if latest_plan_file:
                    plan_loaded = _scheduler.load_irrigation_plan(latest_plan_file)
                    if plan_loaded:
                        plan = _scheduler.get_current_plan()
                        logger.info(f"成功加载计划文件: {latest_plan_file}")
                
                if not plan_loaded:
                    logger.warning("output目录中没有找到计划文件")
                    raise HTTPException(status_code=404, detail="当前没有执行计划")
                    
            except Exception as load_error:
                logger.error(f"加载计划文件失败: {load_error}")
                raise HTTPException(status_code=404, detail="当前没有执行计划")
        
        if not plan:
            raise HTTPException(status_code=404, detail="当前没有执行计划")
        
        # 验证批次索引是否有效（批次索引从1开始）
        batches = []
        if 'scenarios' in plan and isinstance(plan['scenarios'], list) and len(plan['scenarios']) > 0:
            first_scenario = plan['scenarios'][0]
            if 'plan' in first_scenario and 'batches' in first_scenario['plan']:
                batches = first_scenario['plan']['batches']
        elif 'batches' in plan:
            batches = plan['batches']
        
        if not batches or batch_index < 1 or batch_index > len(batches):
            raise HTTPException(status_code=404, detail=f"批次 {batch_index} 不存在")
        
        # 获取批次信息（从计划文件中）
        batch_info = batches[batch_index - 1]  # 转换为0基索引
        
        # 尝试从调度器获取执行详情（如果有的话）
        execution_details = None
        try:
            # 调度器使用0基索引
            execution_details = await _scheduler.get_batch_details(batch_index - 1)
        except Exception as e:
            logger.warning(f"获取批次执行详情失败: {e}")
        
        # 构建详细信息
        details = {
            "batch_index": batch_index,
            "area_mu": batch_info.get("area_mu", 0),
            "field_count": len(batch_info.get("fields", [])),
            "fields": [
                {
                    "id": field.get("id"),
                    "area_mu": field.get("area_mu"),
                    "segment_id": field.get("segment_id"),
                    "distance_rank": field.get("distance_rank"),
                    "wl_mm": field.get("wl_mm"),
                    "inlet_G_id": field.get("inlet_G_id")
                }
                for field in batch_info.get("fields", [])
            ],
            "segment_ids": list(set(field.get("segment_id") for field in batch_info.get("fields", []) if field.get("segment_id"))),
            "execution_details": execution_details,
            "query_time": datetime.now().isoformat()
        }
        
        # 获取scenario信息
        scenario_info = get_scenario_info(_scheduler)
        details.update({
            "scenario_name": scenario_info["scenario_name"],
            "scenario_count": scenario_info["scenario_count"],
            "selected_scenario_index": scenario_info["selected_scenario_index"]
        })
        
        return details
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取批次详细信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取批次详细信息失败: {str(e)}")

@app.get("/api/batches/current-plan")
async def get_current_plan():
    """获取当前执行计划"""
    try:
        global _scheduler
        if not _scheduler:
            raise HTTPException(status_code=500, detail="调度器未初始化")
        
        plan = _scheduler.get_current_plan()
        
        if not plan:
            raise HTTPException(status_code=404, detail="当前没有执行计划")
        
        return {
            "plan": plan,
            "farm_id": _scheduler.get_farm_id(),
            "query_time": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取当前计划失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取当前计划失败: {str(e)}")

@app.post("/api/batch/adjust", response_model=BatchAdjustmentResponse)
async def adjust_fields_between_batches(request: BatchAdjustmentRequest):
    """
    批次间田块调整接口
    
    在不改变批次数量的情况下，调整田块在批次间的分配。
    保持现有批次结构，只重新计算灌溉顺序和时间。
    
    - **plan_id**: 计划ID或文件路径
    - **field_adjustments**: 田块调整列表，每项包含field_id、from_batch、to_batch
    - **options**: 调整选项（是否重新计算顺序、时间等）
    
    与 /api/regeneration/batch 的区别：
    - /api/regeneration/batch: 增减田块，可能改变批次数量和结构
    - /api/batch/adjust: 批次间移动田块，批次数量不变，只调整分配
    
    返回包含原始计划、调整后计划和变更摘要的响应。
    """
    try:
        logger.info(f"开始批次间田块调整 - plan_id: {request.plan_id}")
        logger.info(f"调整数量: {len(request.field_adjustments)}")
        
        # 导入批次调整服务
        from batch_adjustment_service import BatchAdjustmentService
        
        # 创建服务实例
        service = BatchAdjustmentService()
        
        # 转换请求为字典格式
        field_adjustments = [
            {
                "field_id": adj.field_id,
                "from_batch": adj.from_batch,
                "to_batch": adj.to_batch
            }
            for adj in request.field_adjustments
        ]
        
        options = {
            "recalculate_sequence": request.options.recalculate_sequence,
            "recalculate_timing": request.options.recalculate_timing,
            "maintain_pump_assignments": request.options.maintain_pump_assignments,
            "regenerate_commands": request.options.regenerate_commands
        }
        
        # 执行调整
        result = service.adjust_fields_between_batches(
            plan_id=request.plan_id,
            field_adjustments=field_adjustments,
            options=options
        )
        
        logger.info(f"批次调整完成 - 成功调整 {result['changes_summary']['total_fields_moved']} 个田块")
        
        return BatchAdjustmentResponse(
            success=result["success"],
            message=result["message"],
            original_plan=result["original_plan"],
            adjusted_plan=result["adjusted_plan"],
            changes_summary=result["changes_summary"],
            validation=result["validation"],
            output_file=result.get("output_file")
        )
        
    except ValueError as ve:
        logger.error(f"批次调整验证失败: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except FileNotFoundError as fnf:
        logger.error(f"计划文件未找到: {fnf}")
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as e:
        logger.error(f"批次调整失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"批次调整失败: {str(e)}")

# ==================== 灌溉计划生成API ====================

@app.post("/api/irrigation/plan-generation", response_model=IrrigationPlanResponse)
async def generate_irrigation_plan(request: IrrigationPlanRequest):
    """生成灌溉计划（支持多水泵方案对比和缓存）"""
    try:
        logger.info(f"开始生成灌溉计划 - farm_id: {request.farm_id}")
        
        # 生成缓存键
        cache_key = generate_cache_key(
            farm_id=request.farm_id,
            target_depth_mm=90.0,  # 默认值
            pumps="",
            zones="",
            merge_waterlevels=True,
            print_summary=True,
            multi_pump_scenarios=request.multi_pump_scenarios or False
        )
        
        # 尝试从缓存获取结果
        cached_result = get_from_cache(cache_key)
        if cached_result:
            logger.info(f"从缓存返回灌溉计划结果 - cache_key: {cache_key}")
            return IrrigationPlanResponse(**cached_result)
        
        # 导入pipeline模块
        try:
            from pipeline import IrrigationPipeline
        except ImportError as e:
            logger.error(f"导入pipeline模块失败: {e}")
            raise HTTPException(status_code=500, detail="系统模块导入失败")
        
        # 设置默认参数
        output_dir = request.output_dir or os.path.join(os.path.dirname(__file__), "output")
        config_path = request.config_path or os.path.join(os.path.dirname(__file__), "config.json")
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 构建pipeline参数
        kwargs = {
            'input_dir': os.path.join(os.path.dirname(__file__), "gzp_farm"),
            'output_dir': output_dir,
            'config_file': config_path if os.path.exists(config_path) else None,
            'merge_waterlevels': True,
            'print_summary': True,
            'multi_pump_scenarios': request.multi_pump_scenarios or False
        }
        
        logger.info(f"Pipeline参数: {kwargs}")
        
        # 运行灌溉计划生成
        try:
            pipeline = IrrigationPipeline()
            success = pipeline.run_pipeline(**kwargs)
            logger.info(f"Pipeline执行结果: success={success}")
        except Exception as pipeline_error:
            logger.error(f"Pipeline执行异常: {pipeline_error}")
            raise HTTPException(status_code=500, detail=f"灌溉计划生成异常: {str(pipeline_error)}")
        
        if not success:
            logger.error("Pipeline执行失败")
            raise HTTPException(status_code=500, detail="灌溉计划生成失败")
        
        # 读取生成的计划文件（查找最新的irrigation_plan_*.json文件）
        plan_data = None
        plan_id = None
        
        if os.path.exists(output_dir):
            plan_files = glob.glob(os.path.join(output_dir, "irrigation_plan_*.json"))
            if plan_files:
                # 获取最新的文件
                latest_plan_file = max(plan_files, key=os.path.getmtime)
                plan_id = latest_plan_file.replace('\\', '/')  # 返回完整路径，统一使用正斜杠
                logger.info(f"读取计划文件: {latest_plan_file}")
                
                try:
                    with open(latest_plan_file, 'r', encoding='utf-8') as f:
                        plan_data = json.load(f)
                    logger.info(f"成功读取计划数据，包含 {len(plan_data) if plan_data else 0} 项")
                except Exception as e:
                    logger.error(f"读取计划文件失败: {e}")
            else:
                logger.warning("未找到灌溉计划文件")
        
        # 如果启用了多水泵方案对比，添加方案对比数据
        multi_pump_data = None
        if request.multi_pump_scenarios and os.path.exists(config_path):
            try:
                logger.info("开始生成多水泵方案对比")
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                
                # 创建农场配置
                cfg = farmcfg_from_json_select(config_data)
                
                # 从配置中获取触发条件
                min_fields_trigger = config_data.get('irrigation_trigger_config', {}).get('min_fields_trigger', 1)
                
                # 生成多水泵方案
                scenarios_result = generate_multi_pump_scenarios(cfg, min_fields_trigger=min_fields_trigger)
                multi_pump_data = {
                    "scenarios": scenarios_result.get('scenarios', []),
                    "analysis": scenarios_result.get('analysis', {}),
                    "total_scenarios": scenarios_result.get('total_scenarios', 0)
                }
                logger.info(f"多水泵方案生成成功，共 {multi_pump_data['total_scenarios']} 个方案（触发阈值: {min_fields_trigger}个田块）")
            except Exception as e:
                logger.warning(f"多水泵方案生成失败: {e}")
        
        # 准备响应数据
        response_data = {
            "success": True,
            "message": "灌溉计划生成成功",
            "data": plan_data,
            "plan_id": plan_id,
            "multi_pump_scenarios": multi_pump_data
        }
        
        # 将结果保存到缓存
        set_cache(cache_key, response_data)
        logger.info(f"灌溉计划结果已保存到缓存 - cache_key: {cache_key}")
        
        logger.info("灌溉计划生成完成")
        return IrrigationPlanResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成灌溉计划失败: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"服务器内部错误: {str(e)}"
        )

@app.post("/api/irrigation/plan-with-upload", response_model=IrrigationPlanResponse)
async def generate_irrigation_plan_with_upload(
    farm_id: str = Form("13944136728576"),
    scenario_name: Optional[str] = Form("upload_test"),
    target_depth_mm: float = Form(90.0),
    pumps: Optional[str] = Form(None),
    zones: Optional[str] = Form(None),
    merge_waterlevels: bool = Form(True),
    print_summary: bool = Form(True),
    multi_pump_scenarios: bool = Form(False),
    custom_waterlevels: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[])
):
    """生成灌溉计划（支持文件上传、多水泵方案对比和缓存）"""
    backup_dir = ""
    
    try:
        logger.info(f"开始处理灌溉计划请求 - farm_id: {farm_id}, target_depth_mm: {target_depth_mm}")
        
        # 生成缓存键（包含文件信息）
        file_hash = ""
        if files and files[0].filename:
            # 为上传的文件生成哈希
            file_contents = []
            for file in files:
                content = await file.read()
                file_contents.append(content)
                await file.seek(0)  # 重置文件指针
            file_hash = hashlib.md5(b''.join(file_contents)).hexdigest()[:8]
        
        cache_key = generate_cache_key(
            farm_id=farm_id,
            target_depth_mm=target_depth_mm,
            pumps=pumps or "",
            zones=zones or "",
            merge_waterlevels=merge_waterlevels,
            print_summary=print_summary,
            multi_pump_scenarios=multi_pump_scenarios,
            file_hash=file_hash
        )
        
        # 尝试从缓存获取结果（仅当没有文件上传时）
        if not (files and files[0].filename):
            cached_result = get_from_cache(cache_key)
            if cached_result:
                logger.info(f"从缓存返回灌溉计划结果 - cache_key: {cache_key}")
                return IrrigationPlanResponse(**cached_result)
        
        # 导入pipeline模块
        try:
            from pipeline import IrrigationPipeline
        except ImportError as e:
            logger.error(f"导入pipeline模块失败: {e}")
            raise HTTPException(status_code=500, detail="系统模块导入失败")
        
        # 验证上传的文件
        if files and files[0].filename:  # 检查是否真的有文件上传
            logger.info(f"检测到文件上传，文件数量: {len(files)}")
            for file in files:
                logger.info(f"上传文件: {file.filename}")
            
            if not validate_shp_files(files):
                logger.error("文件验证失败：无效的shapefile文件组合")
                raise HTTPException(
                    status_code=400, 
                    detail="无效的shapefile文件组合，需要包含.shp, .dbf, .shx文件"
                )
            
            logger.info("文件验证通过")
            
            # 备份现有文件
            logger.info("开始备份现有文件")
            backup_dir = backup_existing_files()
            logger.info(f"备份目录: {backup_dir}")
            
            # 保存上传的文件
            logger.info("开始保存上传的文件")
            if not save_uploaded_files(files):
                logger.error("文件保存失败，恢复备份")
                if backup_dir:
                    restore_files(backup_dir)
                raise HTTPException(status_code=500, detail="文件保存失败")
            logger.info("文件保存成功")
        else:
            logger.info("未检测到文件上传，使用现有数据")
        
        # 构建pipeline参数
        kwargs = {
            'input_dir': GZP_FARM_DIR,
            'output_dir': OUTPUT_DIR,
            'config_file': None,
            'scenario_name': scenario_name,
            'pumps': pumps,
            'zones': zones,
            'merge_waterlevels': merge_waterlevels,
            'print_summary': print_summary,
            'multi_pump_scenarios': multi_pump_scenarios,
            'custom_waterlevels': custom_waterlevels
        }
        logger.info(f"Pipeline参数: {kwargs}")
        
        # 更新auto_config_params.yaml中的farm_id和target_depth_mm
        config_params_file = os.path.join(os.path.dirname(__file__), "auto_config_params.yaml")
        logger.info(f"配置文件路径: {config_params_file}")
        
        try:
            if os.path.exists(config_params_file):
                import yaml
                logger.info("读取配置文件")
                with open(config_params_file, 'r', encoding='utf-8') as f:
                    config_params = yaml.safe_load(f)
                
                config_params['default_farm_id'] = farm_id
                config_params['default_target_depth_mm'] = target_depth_mm
                
                logger.info("更新配置文件")
                with open(config_params_file, 'w', encoding='utf-8') as f:
                    yaml.dump(config_params, f, ensure_ascii=False, indent=2)
                logger.info("配置文件更新成功")
            else:
                logger.info("配置文件不存在，跳过更新")
        except Exception as config_error:
            logger.error(f"配置文件处理错误: {config_error}")
            # 配置文件错误不应该阻止主流程
        
        # 确保输出目录存在
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # 运行灌溉计划生成
        logger.info("开始运行灌溉计划生成")
        try:
            pipeline = IrrigationPipeline()
            success = pipeline.run_pipeline(**kwargs)
            logger.info(f"Pipeline执行结果: success={success}")
        except Exception as pipeline_error:
            logger.error(f"Pipeline执行异常: {pipeline_error}")
            if backup_dir:
                logger.info("恢复备份文件")
                restore_files(backup_dir)
            raise HTTPException(status_code=500, detail=f"灌溉计划生成异常: {str(pipeline_error)}")
        
        if not success:
            logger.error("Pipeline执行失败")
            if backup_dir:
                logger.info("恢复备份文件")
                restore_files(backup_dir)
            raise HTTPException(status_code=500, detail="灌溉计划生成失败")
        
        # 读取生成的计划文件（查找最新的irrigation_plan_*.json文件）
        plan_data = None
        plan_id = None
        
        if os.path.exists(OUTPUT_DIR):
            plan_files = glob.glob(os.path.join(OUTPUT_DIR, "irrigation_plan_*.json"))
            if plan_files:
                # 获取最新的文件
                latest_plan_file = max(plan_files, key=os.path.getmtime)
                plan_id = latest_plan_file.replace('\\', '/')  # 返回完整路径，统一使用正斜杠
                logger.info(f"读取计划文件: {latest_plan_file}")
                
                try:
                    with open(latest_plan_file, 'r', encoding='utf-8') as f:
                        plan_data = json.load(f)
                    logger.info(f"成功读取计划数据，包含 {len(plan_data) if plan_data else 0} 项")
                except Exception as e:
                    logger.error(f"读取计划文件失败: {e}")
            else:
                logger.warning("未找到灌溉计划文件")
        
        # 如果启用了多水泵方案对比，添加方案对比数据
        multi_pump_data = None
        if multi_pump_scenarios:
            try:
                logger.info("开始生成多水泵方案对比")
                config_path = os.path.join(os.path.dirname(__file__), "config.json")
                if os.path.exists(config_path):
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    
                    # 创建农场配置
                    cfg = farmcfg_from_json_select(config_data)
                    
                    # 从配置中获取触发条件
                    min_fields_trigger = config_data.get('irrigation_trigger_config', {}).get('min_fields_trigger', 1)
                    
                    # 生成多水泵方案
                    scenarios_result = generate_multi_pump_scenarios(cfg, min_fields_trigger=min_fields_trigger)
                    multi_pump_data = {
                        "scenarios": scenarios_result.get('scenarios', []),
                        "analysis": scenarios_result.get('analysis', {}),
                        "total_scenarios": scenarios_result.get('total_scenarios', 0)
                    }
                    logger.info(f"多水泵方案生成成功，共 {multi_pump_data['total_scenarios']} 个方案（触发阈值: {min_fields_trigger}个田块）")
                else:
                    logger.warning("配置文件不存在，跳过多水泵方案生成")
            except Exception as e:
                logger.warning(f"多水泵方案生成失败: {e}")
        
        # 清理备份
        if backup_dir:
            shutil.rmtree(backup_dir)
        
        # 准备响应数据
        response_data = {
            "success": True,
            "message": "灌溉计划生成成功",
            "data": plan_data,
            "plan_id": plan_id,
            "multi_pump_scenarios": multi_pump_data
        }
        
        # 将结果保存到缓存（仅当没有文件上传时）
        if not (files and files[0].filename):
            set_cache(cache_key, response_data)
            logger.info(f"灌溉计划结果已保存到缓存 - cache_key: {cache_key}")
        
        logger.info("灌溉计划生成完成")
        return IrrigationPlanResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        # 恢复备份文件
        if backup_dir:
            restore_files(backup_dir)
        
        logger.error(f"生成灌溉计划失败: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"服务器内部错误: {str(e)}"
        )

# ==================== 数据管理API ====================

@app.post("/api/data/cleanup")
async def cleanup_old_data(retention_days: int = 30):
    """清理旧数据"""
    try:
        global _scheduler
        if not _scheduler:
            raise HTTPException(status_code=500, detail="调度器未初始化")
        
        await _scheduler.cleanup_old_data(retention_days)
        
        return {
            "success": True,
            "message": f"成功清理 {retention_days} 天前的旧数据",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"清理旧数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理旧数据失败: {str(e)}")

# ==================== GeoJson API ====================

@app.get("/geojson/fields")
async def api_fields():
    """获取田块GeoJson数据"""
    try:
        p = _first_existing(LABELED_FIELDS, os.path.join(GEOJSON_DIR, FIELD_FILE))
        if not p:
            raise HTTPException(status_code=404, detail="未找到田块图层")
        
        gdf = read_geo_ensure_wgs84(p)
        return JSONResponse(content=json.loads(gdf.to_json()))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取田块GeoJson数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取田块数据失败: {str(e)}")

@app.get("/geojson/gates")
async def api_gates():
    """获取闸门GeoJson数据"""
    try:
        p = _first_existing(LABELED_GATES, os.path.join(GEOJSON_DIR, VALVE_FILE))
        if not p:
            raise HTTPException(status_code=404, detail="未找到闸门图层")
        
        gdf = read_geo_ensure_wgs84(p)
        return JSONResponse(content=json.loads(gdf.to_json()))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取闸门GeoJson数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取闸门数据失败: {str(e)}")

@app.get("/geojson")
async def api_geojson(type: Optional[str] = Query(None, description="数据类型: waterway/fields/gates")):
    """兼容旧接口：/geojson?type=waterway|fields|gates"""
    try:
        if not type:
            raise HTTPException(status_code=400, detail="type 参数必须为 waterway/fields/gates 之一")
        
        typ = type.lower().strip()
        
        if typ in ("fields", "field"):
            return await api_fields()
        
        if typ in ("gates", "gate", "valves", "valve"):
            return await api_gates()
        
        if typ in ("waterway", "segments", "lines"):
            p = _first_existing(LABELED_SEGMENT, os.path.join(GEOJSON_DIR, WATERWAY_FILE))
            if not p:
                raise HTTPException(status_code=404, detail="未找到水路图层")
            
            gdf = read_geo_ensure_wgs84(p)
            return JSONResponse(content=json.loads(gdf.to_json()))
        
        raise HTTPException(status_code=400, detail="type 参数必须为 waterway/fields/gates 之一")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取GeoJson数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取GeoJson数据失败: {str(e)}")

# ==================== 监控面板API ====================

@app.get("/api/monitoring/dashboard")
async def get_monitoring_dashboard(farm_id: Optional[str] = Query("default_farm", description="农场ID")):
    """获取监控面板数据"""
    try:
        global _scheduler, _waterlevel_manager, _status_manager
        
        # 获取系统状态
        system_status = {
            "scheduler_initialized": _scheduler is not None,
            "waterlevel_manager_initialized": _waterlevel_manager is not None,
            "status_manager_initialized": _status_manager is not None,
            "current_time": datetime.now().isoformat(),
            "uptime_seconds": (datetime.now() - _system_start_time).total_seconds()
        }
        
        # 获取执行状态
        execution_status = {}
        if _scheduler:
            try:
                status = _scheduler.get_execution_status()
                execution_status = {
                    "is_running": _scheduler.is_running,
                    "execution_id": status.get("execution_id"),
                    "status": status.get("status"),
                    "current_batch": status.get("current_batch"),
                    "total_batches": status.get("total_batches", 0),
                    "start_time": status.get("start_time"),
                    "last_water_level_update": status.get("last_water_level_update"),
                    "total_regenerations": status.get("total_regenerations", 0),
                    "active_fields": status.get("active_fields", []),
                    "completed_batches": status.get("completed_batches", []),
                    "error_message": status.get("error_message")
                }
            except Exception as e:
                logger.warning(f"获取执行状态失败: {e}")
                execution_status = {"error": str(e)}
        
        # 获取水位数据摘要
        water_level_summary = {}
        if _waterlevel_manager:
            try:
                summary = _waterlevel_manager.get_water_level_summary()
                water_level_summary = {
                    "total_fields": summary.get("total_fields", 0),
                    "fields_with_data": summary.get("fields_with_data", 0),
                    "last_update": summary.get("last_update"),
                    "average_level": summary.get("average_level", 0),
                    "quality_summary": summary.get("quality_summary", {}),
                    "field_summaries": summary.get("field_summaries", {})
                }
            except Exception as e:
                logger.warning(f"获取水位摘要失败: {e}")
                water_level_summary = {"error": str(e)}
        
        # 获取最近的执行历史
        recent_history = []
        if _status_manager:
            try:
                history = await _status_manager.get_recent_executions(limit=5)
                recent_history = history
            except Exception as e:
                logger.warning(f"获取执行历史失败: {e}")
                recent_history = []
        
        dashboard_data = {
            "farm_id": farm_id,
            "timestamp": datetime.now().isoformat(),
            "system_status": system_status,
            "execution_status": execution_status,
            "water_level_summary": water_level_summary,
            "recent_history": recent_history
        }
        
        return {
            "success": True,
            "message": "监控面板数据获取成功",
            "data": dashboard_data
        }
        
    except Exception as e:
        logger.error(f"获取监控面板数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取监控面板数据失败: {str(e)}")

# ==================== 根路径和文档 ====================

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "智能灌溉动态执行系统",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "docs_url": "/docs",
        "redoc_url": "/redoc"
    }

@app.post("/api/irrigation/multi-pump-scenarios", response_model=MultiPumpResponse)
async def generate_multi_pump_scenarios_api(request: MultiPumpRequest):
    """生成多水泵方案对比（独立API）"""
    try:
        logger.info(f"开始处理多水泵方案请求 - config_file: {request.config_file}")
        
        # 确定配置文件路径
        if os.path.isabs(request.config_file):
            config_path = request.config_file
        else:
            config_path = os.path.join(os.path.dirname(__file__), request.config_file)
        
        # 检查配置文件是否存在
        if not os.path.exists(config_path):
            logger.error(f"配置文件不存在: {config_path}")
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
        
        logger.info(f"触发阈值: {min_fields_trigger}个田块")
        
        # 生成多水泵方案
        scenarios_result = generate_multi_pump_scenarios(cfg, min_fields_trigger=min_fields_trigger)
        
        logger.info(f"多水泵方案生成成功，共 {scenarios_result.get('total_scenarios', 0)} 个方案")
        
        return MultiPumpResponse(
            scenarios=scenarios_result.get('scenarios', []),
            analysis=scenarios_result.get('analysis', {}),
            total_scenarios=scenarios_result.get('total_scenarios', 0)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"多水泵方案生成失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"多水泵方案生成失败: {str(e)}"
        )

# ==================== 灌溉计划优化API ====================

@app.post("/api/irrigation/plan-optimization", response_model=OptimizationResponse)
async def optimize_irrigation_plan(request: OptimizationRequest):
    """
    灌溉计划智能优化
    
    根据不同优化目标自动生成多个优化方案：
    - cost_minimization: 成本最小化（省电）
    - time_minimization: 时间最小化（省时）
    - balanced: 均衡优化
    - off_peak: 避峰用电
    - water_saving: 节水优化
    """
    try:
        logger.info(f"开始灌溉计划优化 - plan_id: {request.original_plan_id}")
        logger.info(f"优化目标: {request.optimization_goals}")
        
        # 导入批次重新生成服务来加载计划
        from batch_regeneration_api import BatchRegenerationService
        from intelligent_batch_optimizer import IntelligentBatchOptimizer
        
        service = BatchRegenerationService()
        
        # 加载原始计划
        try:
            original_plan = service.load_original_plan(request.original_plan_id)
            if not original_plan:
                raise HTTPException(status_code=404, detail=f"未找到计划: {request.original_plan_id}")
        except Exception as e:
            logger.error(f"加载原始计划失败: {e}")
            raise HTTPException(status_code=404, detail=f"加载原始计划失败: {str(e)}")
        
        # 创建优化器
        optimizer = IntelligentBatchOptimizer()
        
        # 生成优化方案
        result = optimizer.generate_optimized_scenarios(
            base_plan=original_plan,
            optimization_goals=request.optimization_goals,
            constraints=request.constraints
        )
        
        logger.info(f"成功生成 {result['total_scenarios']} 个优化方案")
        
        return OptimizationResponse(
            success=True,
            message=f"成功生成 {result['total_scenarios']} 个优化方案",
            total_scenarios=result["total_scenarios"],
            scenarios=result["scenarios"],
            comparison=result["comparison"],
            base_plan_summary=result["base_plan_summary"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"灌溉计划优化失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"灌溉计划优化失败: {str(e)}"
        )

@app.get("/api/info")
async def api_info():
    """API信息"""
    return {
        "title": "智能灌溉动态执行系统API",
        "description": "基于实时水位数据的智能灌溉批次动态执行系统",
        "version": "1.0.0",
        "features": [
            "动态批次执行管理",
            "实时水位数据获取和管理", 
            "智能计划重新生成",
            "执行状态监控和历史记录",
            "田块水位趋势分析",
            "多水泵方案对比分析",
            "灌溉计划智能优化"
        ],
        "endpoints": {
            "system": "/api/system/*",
            "execution": "/api/execution/*",
            "water_levels": "/api/water-levels/*",
            "regeneration": "/api/regeneration/*",
            "batches": "/api/batches/*",
            "irrigation": "/api/irrigation/*",
            "data": "/api/data/*"
        }
    }

if __name__ == "__main__":
    # 运行服务器
    logger.info("启动智能灌溉动态执行系统服务器...")
    
    uvicorn.run(
        "main_dynamic_execution_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )