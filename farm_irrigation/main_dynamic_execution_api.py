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
from pathlib import Path
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Form, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn
import geopandas as gpd
import requests

# 导入动态执行相关模块
from src.scheduler.batch_execution_scheduler import BatchExecutionScheduler
from src.scheduler.dynamic_waterlevel_manager import DynamicWaterLevelManager
from src.scheduler.dynamic_plan_regenerator import DynamicPlanRegenerator
from src.scheduler.execution_status_manager import ExecutionStatusManager

# 导入API模型和函数
from src.api.dynamic_execution_api import (
    DynamicExecutionRequest, DynamicExecutionResponse,
    ExecutionStatusResponse, WaterLevelUpdateRequest, WaterLevelUpdateResponse,
    ManualRegenerationRequest, ManualRegenerationResponse,
    ExecutionHistoryResponse,
    start_dynamic_execution, stop_dynamic_execution, get_execution_status,
    update_water_levels, manual_regenerate_batch, get_execution_history,
    get_water_level_summary, get_field_trend_analysis, get_water_level_history
)

# 导入批次重新生成相关模块
from src.api.batch_regeneration_api import (
    BatchModificationRequest, BatchRegenerationResponse,
    create_batch_regeneration_endpoint, generate_batch_cache_key
)

# 导入多水泵方案相关模块
from src.core.farm_irr_full_device_modified import farmcfg_from_json_select, generate_multi_pump_scenarios

# 导入硬件批量查询模块
from src.hardware.hw_batch_field_status import get_all_fields_device_status
from src.hardware.hw_device_self_check import (
    trigger_device_self_check,
    query_device_status,
    filter_successful_devices,
    get_device_status_summary
)

# 全局缓存和线程池
_cache = {}
_cache_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2)  # 限制并发数

# 配置日志
import os
# 基于项目根目录计算日志路径
_log_dir = os.path.join(os.path.dirname(__file__), 'data', 'execution_logs')
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(_log_dir, 'main_dynamic_execution.log'), encoding='utf-8'),
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

def clear_cache():
    """清除所有缓存"""
    with _cache_lock:
        _cache.clear()

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
    database_path: str = "data/execution_status.db"
    cache_file_path: str = "data/water_level_cache.json"

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
    scenario_name: Optional[str] = None
    field_modifications: Optional[List[FieldModification]] = []
    pump_assignments: Optional[List[PumpAssignment]] = []
    time_modifications: Optional[List[TimeModification]] = []
    regeneration_params: Optional[Dict[str, Any]] = {}

class BatchRegenerationResponse(BaseModel):
    """批次重新生成响应"""
    success: bool
    message: str
    scenario_name: Optional[str] = None  # 指定scenario时返回
    original_scenario: Optional[Dict[str, Any]] = None  # 指定scenario时返回
    modified_scenario: Optional[Dict[str, Any]] = None  # 指定scenario时返回
    original_plan: Optional[Dict[str, Any]] = None  # 未指定scenario时返回
    modified_plan: Optional[Dict[str, Any]] = None  # 未指定scenario时返回
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

class FieldDeviceStatusRequest(BaseModel):
    """田块设备状态查询请求模型"""
    farm_id: str = Field(..., description="农场ID")
    app_id: Optional[str] = Field(None, description="应用ID（如果为None，从环境变量或配置读取）")
    secret: Optional[str] = Field(None, description="密钥（如果为None，从环境变量或配置读取）")
    timeout: int = Field(30, description="请求超时时间（秒）")
    verbose: bool = Field(False, description="是否打印详细信息")

class FieldDeviceStatusResponse(BaseModel):
    """田块设备状态查询响应模型"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class DeviceSelfCheckRequest(BaseModel):
    """设备自检请求"""
    plan_id: Optional[str] = Field(None, description="灌溉计划ID或文件路径（留空则使用最新计划）")
    farm_id: str = Field(..., description="农场ID")
    scenario_name: Optional[str] = Field(None, description="方案名称（留空则使用默认方案）")
    wait_minutes: int = Field(5, description="初次等待时间（分钟），默认5分钟", ge=1, le=30)
    enable_polling: bool = Field(True, description="是否启用轮询模式（持续查询直到完成）")
    max_polling_attempts: int = Field(10, description="最大轮询次数", ge=1, le=50)
    polling_interval_seconds: int = Field(30, description="轮询间隔（秒）", ge=10, le=300)
    app_id: Optional[str] = Field(None, description="iLand平台应用ID")
    secret: Optional[str] = Field(None, description="iLand平台密钥")
    timeout: int = Field(30, description="API请求超时时间（秒）")
    auto_regenerate: bool = Field(True, description="是否自动重新生成计划")

class DeviceSelfCheckResponse(BaseModel):
    """设备自检响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class ScenarioReorderConfig(BaseModel):
    """单个scenario的顺序调整配置"""
    scenario_name: Optional[str] = None  # scenario名称，None表示所有scenario
    new_order: List[int]  # 新的批次执行顺序

class BatchReorderRequest(BaseModel):
    """批次顺序调整请求（支持多scenario）"""
    plan_id: str
    new_order: Optional[List[int]] = None  # 新的批次顺序（兼容旧版）
    scenario_name: Optional[str] = None  # 指定要调整的scenario名称（兼容旧版）
    reorder_configs: Optional[List[ScenarioReorderConfig]] = None  # 多scenario调整配置（新功能）

class BatchReorderResponse(BaseModel):
    """批次顺序调整响应"""
    success: bool
    message: str
    original_plan: Optional[Dict[str, Any]] = None
    reordered_plan: Optional[Dict[str, Any]] = None
    changes_summary: Dict[str, Any] = {}
    validation: Dict[str, Any] = {}
    output_file: Optional[str] = None

class FarmSwitchResponse(BaseModel):
    """农场切换响应模型"""
    success: bool
    message: str
    farm_id: str
    farm_name: str
    backup_path: Optional[str] = None
    files_processed: Dict[str, str] = {}
    config_path: Optional[str] = None
    validation: Dict[str, Any] = {}
    timestamp: str

# 系统启动时间
_system_start_time = datetime.now()

# 文件上传相关常量
GZP_FARM_DIR = os.path.join(os.path.dirname(__file__), "data", "gzp_farm")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data", "output")

# GeoJson相关常量
ROOT = os.path.abspath(os.path.dirname(__file__))
GEOJSON_DIR = os.path.join(ROOT, "data", "gzp_farm")
# 这些常量已弃用，改为动态从config.json获取farm_id
# VALVE_FILE = "港中坪阀门与节制闸_code.geojson"
# FIELD_FILE = "港中坪田块_code.geojson"
# WATERWAY_FILE = "港中坪水路_code.geojson"

# 标注后的文件（优先使用）
LABELED_DIR = os.path.join(ROOT, "data", "labeled_output")
LABELED_FIELDS = os.path.join(LABELED_DIR, "fields_labeled.geojson")
LABELED_GATES = os.path.join(LABELED_DIR, "gates_labeled.geojson")
LABELED_SEGMENT = os.path.join(LABELED_DIR, "segments_labeled.geojson")

def get_current_farm_geojson_files() -> Dict[str, str]:
    """
    动态获取当前农场的GeoJSON文件名
    
    Returns:
        dict: {'fields': 'xxx_fields_code.geojson', 'gates': '...', 'segments': '...'}
    """
    try:
        # 方法1: 从auto_config_params.yaml读取
        import yaml
        yaml_path = os.path.join(ROOT, "auto_config_params.yaml")
        if os.path.exists(yaml_path):
            with open(yaml_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if 'default_filenames' in config:
                    return {
                        'fields': config['default_filenames'].get('fields', ''),
                        'gates': config['default_filenames'].get('gates', ''),
                        'segments': config['default_filenames'].get('segments', '')
                    }
        
        # 方法2: 从config.json读取farm_id并构造文件名
        config_path = os.path.join(ROOT, "config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                farm_id = config.get('farm_id', '13944136728576')
                return {
                    'fields': f"{farm_id}_fields_code.geojson",
                    'gates': f"{farm_id}_gates_code.geojson",
                    'segments': f"{farm_id}_segments_code.geojson"
                }
        
        # 兜底：返回港中坪农场文件名
        return {
            'fields': "13944136728576_fields_code.geojson",
            'gates': "13944136728576_gates_code.geojson", 
            'segments': "13944136728576_segments_code.geojson"
        }
    except Exception as e:
        logger.error(f"获取农场GeoJSON文件名失败: {e}")
        # 返回港中坪农场作为兜底
        return {
            'fields': "13944136728576_fields_code.geojson",
            'gates': "13944136728576_gates_code.geojson",
            'segments': "13944136728576_segments_code.geojson"
        }

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
        output_dir = script_dir / "data" / "output"
    else:
        output_dir = Path(output_dir_path)
    
    if not output_dir.exists():
        logger.warning(f"输出目录不存在: {output_dir}")
        return None
    
    # 查找完整计划文件（包括所有irrigation_plan开头的文件）
    plan_patterns = [
        "irrigation_plan_*.json",  # 匹配所有irrigation_plan开头的文件
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

# 农场切换辅助函数
def detect_shp_file_type(filename: str) -> Optional[str]:
    """根据文件名自动检测SHP文件类型"""
    name_lower = filename.lower()
    
    # 关键词匹配
    keywords = {
        'fields': ['田块', '地块', 'field', 'plot', '田', 'tian'],
        'segments': ['水路', '渠道', 'canal', 'segment', '水', 'shui', 'line'],
        'gates': ['阀门', '闸门', 'gate', 'valve', '闸', 'zha', '阀', 'fa']
    }
    
    for file_type, kw_list in keywords.items():
        if any(kw in name_lower for kw in kw_list):
            return file_type
    
    return None

def convert_shp_to_geojson(shp_path: str, output_path: str) -> bool:
    """转换单个SHP文件为GeoJSON"""
    try:
        gdf = gpd.read_file(shp_path)
        gdf.to_file(output_path, driver='GeoJSON')
        return True
    except Exception as e:
        logger.error(f"转换失败 {shp_path}: {e}")
        return False

def update_yaml_config(farm_id: str, farm_name: str, geojson_files: Dict[str, str]) -> bool:
    """更新auto_config_params.yaml配置"""
    try:
        import yaml
        yaml_path = os.path.join(os.path.dirname(__file__), "auto_config_params.yaml")
        
        with open(yaml_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 更新配置
        config['default_farm_id'] = farm_id
        config['default_filenames'] = {
            'segments': geojson_files['segments'],
            'gates': geojson_files['gates'],
            'fields': geojson_files['fields']
        }
        
        # 确保file_search_paths包含正确的路径
        if 'file_search_paths' not in config:
            config['file_search_paths'] = {}
        if 'data_paths' not in config['file_search_paths']:
            config['file_search_paths']['data_paths'] = []
        
        # 添加data/gzp_farm路径（如果不存在）
        data_paths = config['file_search_paths']['data_paths']
        if 'data/gzp_farm' not in data_paths:
            data_paths.insert(0, 'data/gzp_farm')  # 放在最前面，优先搜索
        
        # 使用正确的YAML写入配置，确保中文正确保存
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(
                config, 
                f, 
                allow_unicode=True,  # 允许Unicode字符
                sort_keys=False,     # 保持键的顺序
                default_flow_style=False  # 使用块样式而不是流样式
            )
        
        logger.info(f"YAML配置已更新，搜索路径: {config['file_search_paths']['data_paths']}")
        return True
    except Exception as e:
        logger.error(f"更新YAML配置失败: {e}")
        return False

def update_farm_id_mapping(farm_id: str, farm_name: str) -> bool:
    """更新farm_id_mapping.json"""
    try:
        mapping_file = os.path.join(GZP_FARM_DIR, "farm_id_mapping.json")
        
        # 读取现有映射
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
        else:
            mapping = {}
        
        # 添加新农场
        mapping[farm_id] = farm_name
        
        # 保存
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        
        return True
    except Exception as e:
        logger.error(f"更新农场映射失败: {e}")
        return False

def generate_config_from_geojson() -> bool:
    """调用auto_to_config.py生成config.json"""
    try:
        import subprocess
        
        # 获取项目根目录
        project_root = os.path.dirname(__file__)
        
        # 设置环境变量，确保可以正确导入模块和处理中文
        env = os.environ.copy()
        env['PYTHONPATH'] = project_root
        env['PYTHONIOENCODING'] = 'utf-8'  # 强制Python使用UTF-8编码
        env['PYTHONUTF8'] = '1'  # Python 3.7+ 启用UTF-8模式
        
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "src/converter/auto_to_config.py"],  # 添加 -X utf8 参数
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',  # 忽略编码错误，防止中文输出导致崩溃
            timeout=60,
            env=env  # 传入修改后的环境变量
        )
        
        if result.returncode == 0:
            logger.info("config.json 生成成功")
            return True
        else:
            # 尝试使用GBK解码stderr（Windows中文环境）
            stderr_msg = result.stderr
            if not stderr_msg and result.stderr:
                try:
                    stderr_msg = result.stderr.encode('latin1').decode('gbk', errors='ignore')
                except:
                    stderr_msg = result.stderr
            logger.error(f"config.json 生成失败: {stderr_msg}")
            return False
    except Exception as e:
        logger.error(f"生成config.json出错: {e}")
        return False

def validate_generated_config(farm_id: str) -> Dict[str, Any]:
    """验证生成的config.json"""
    try:
        config_file = os.path.join(os.path.dirname(__file__), "config.json")
        
        if not os.path.exists(config_file):
            return {"valid": False, "error": "config.json不存在"}
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 验证农场ID
        if config.get('farm_id') != farm_id:
            return {
                "valid": False, 
                "error": f"农场ID不匹配: 期望 {farm_id}, 实际 {config.get('farm_id')}"
            }
        
        # 统计信息
        return {
            "valid": True,
            "farm_id": config['farm_id'],
            "fields_count": len(config.get('fields', [])),
            "segments_count": len(config.get('segments', [])),
            "gates_count": len(config.get('gates', [])),
            "pumps_count": len(config.get('pumps', [])),
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}

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
        # 如果路径是相对路径，基于项目根目录计算
        if request.database_path and not os.path.isabs(request.database_path):
            db_path = os.path.join(os.path.dirname(__file__), request.database_path)
        else:
            db_path = request.database_path
        
        log_path = os.path.join(os.path.dirname(__file__), "data", "execution_logs")
        
        _status_manager = ExecutionStatusManager(
            db_path=db_path,
            log_path=log_path
        )
        logger.info("执行状态管理器初始化完成")
        
        # 初始化水位管理器
        # 如果路径是相对路径，基于项目根目录计算
        config_path = request.config_path
        if config_path and not os.path.isabs(config_path):
            config_path = os.path.join(os.path.dirname(__file__), config_path)
        
        cache_file = request.cache_file_path
        if cache_file and not os.path.isabs(cache_file):
            cache_file = os.path.join(os.path.dirname(__file__), cache_file)
        
        _waterlevel_manager = DynamicWaterLevelManager(
            config_path=config_path,
            cache_file=cache_file
        )
        logger.info("水位管理器初始化完成")
        
        # 初始化计划重新生成器
        # 如果路径是相对路径，基于项目根目录计算
        config_path = request.config_path
        if config_path and not os.path.isabs(config_path):
            config_path = os.path.join(os.path.dirname(__file__), config_path)
        
        _plan_regenerator = DynamicPlanRegenerator(
            config_path=config_path
        )
        logger.info("计划重新生成器初始化完成")
        
        # 初始化批次执行调度器
        # 如果路径是相对路径，基于项目根目录计算
        config_path = request.config_path
        if config_path and not os.path.isabs(config_path):
            config_path = os.path.join(os.path.dirname(__file__), config_path)
        
        _scheduler = BatchExecutionScheduler(
            config_path=config_path,
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
async def water_level_summary(
    farm_id: str, 
    field_ids: Optional[str] = None,
    use_sgf_format: bool = Query(False, description="是否使用SGF格式的田块ID（如S1-G2-F03）")
):
    """
    获取水位数据摘要
    
    参数:
    - farm_id: 农场ID
    - field_ids: 田块ID列表，用逗号分隔（可选）
    - use_sgf_format: 是否使用SGF格式的田块ID，默认False使用数字ID
    """
    field_id_list = field_ids.split(",") if field_ids else None
    return await get_water_level_summary(farm_id, field_id_list, use_sgf_format)

@app.get("/api/water-levels/trend/{field_id}")
async def field_trend_analysis(field_id: str, hours: int = 48):
    """获取田块水位趋势分析"""
    return await get_field_trend_analysis(field_id, hours)

@app.get("/api/water-levels/history")
async def water_level_history(farm_id: str, field_id: str, hours: int = 24):
    """获取田块水位历史数据"""
    return await get_water_level_history(farm_id, field_id, hours)

@app.get("/api/water-levels/targets")
async def get_water_level_targets(
    farm_id: str = Query(..., description="农场ID"),
    field_id: Optional[str] = Query(None, description="田块ID（可选，不提供则返回所有田块）")
):
    """
    获取田块的目标水位值
    
    返回所有田块或指定田块的水位标准参数：
    - wl_low: 低水位阈值（mm），触发灌溉的判断标准
    - wl_opt: 最优水位（mm），灌溉的目标水位
    - wl_high: 高水位阈值（mm），超过则不需要灌溉
    - d_target_mm: 目标灌溉水深（mm）
    
    参数:
    - farm_id: 农场ID
    - field_id: 田块ID（可选）
    """
    try:
        logger.info(f"获取水位目标值 - farm_id: {farm_id}, field_id: {field_id}")
        
        # 读取配置文件获取全局水位标准
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        # 获取全局水位标准（从config.json或使用默认值）
        global_wl_low = config_data.get('wl_low', 30.0)
        global_wl_opt = config_data.get('wl_opt', 80.0)
        global_wl_high = config_data.get('wl_high', 140.0)
        
        # 读取田块数据
        from src.core.farm_irr_full_device_modified import farmcfg_from_json_select
        
        try:
            cfg = farmcfg_from_json_select(config_data)
        except Exception as e:
            logger.error(f"加载农场配置失败: {e}")
            raise HTTPException(status_code=500, detail=f"加载农场配置失败: {str(e)}")
        
        # 构建响应数据
        response_data = {
            "success": True,
            "farm_id": farm_id,
            "global_standards": {
                "wl_low": global_wl_low,
                "wl_opt": global_wl_opt,
                "wl_high": global_wl_high,
                "description": "全局默认水位标准"
            },
            "fields": {}
        }
        
        # 如果指定了field_id，只返回该田块的数据
        if field_id:
            if field_id in cfg.fields:
                field = cfg.fields[field_id]
                response_data["fields"][field_id] = {
                    "wl_low": field.wl_low,
                    "wl_opt": field.wl_opt,
                    "wl_high": field.wl_high,
                    "area_mu": field.area_mu,
                    "segment_id": field.segment_id,
                    "source": "field_config" if (field.wl_low != global_wl_low or field.wl_opt != global_wl_opt or field.wl_high != global_wl_high) else "global_default"
                }
            else:
                raise HTTPException(status_code=404, detail=f"田块不存在: {field_id}")
        else:
            # 返回所有田块的数据
            for fid, field in cfg.fields.items():
                response_data["fields"][fid] = {
                    "wl_low": field.wl_low,
                    "wl_opt": field.wl_opt,
                    "wl_high": field.wl_high,
                    "area_mu": field.area_mu,
                    "segment_id": field.segment_id,
                    "source": "field_config" if (field.wl_low != global_wl_low or field.wl_opt != global_wl_opt or field.wl_high != global_wl_high) else "global_default"
                }
        
        response_data["total_fields"] = len(response_data["fields"])
        response_data["timestamp"] = datetime.now().isoformat()
        
        logger.info(f"成功获取 {response_data['total_fields']} 个田块的水位目标值")
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取水位目标值失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取水位目标值失败: {str(e)}")

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
        from src.api.batch_regeneration_api import BatchRegenerationService
        
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
            try:
                modified_plan = service.apply_field_modifications(
                    modified_plan,
                    request.field_modifications,
                    request.scenario_name  # 传递scenario_name
                )
                
                # 从tracking信息中获取修改统计
                tracking = modified_plan.get('modification_tracking', {}).get('field_modifications', {})
                
                for mod in request.field_modifications:
                    modifications_summary["field_modifications"].append({
                        "field_id": mod.field_id,
                        "action": mod.action,
                        "scenarios_affected": tracking.get('modified_scenarios', []),
                        "result": "success"
                    })
                    modifications_summary["total_changes"] += 1
            except Exception as e:
                logger.warning(f"田块修改失败: {e}")
                modifications_summary["field_modifications"].append({
                    "error": str(e)
                })
        
        # 处理水泵分配修改
        if request.pump_assignments:
            try:
                modified_plan = service.apply_pump_modifications(
                    modified_plan, 
                    request.pump_assignments,
                    request.scenario_name  # 传递scenario_name
                )
                
                # 从tracking信息中获取修改统计
                tracking = modified_plan.get('modification_tracking', {}).get('pump_modifications', {})
                
                for assignment in request.pump_assignments:
                    modifications_summary["pump_assignments"].append({
                        "batch_index": assignment.batch_index,
                        "pump_ids": assignment.pump_ids,
                        "scenarios_affected": tracking.get('modified_scenarios', []),
                        "result": "success"
                    })
                    modifications_summary["total_changes"] += 1
            except Exception as e:
                logger.warning(f"水泵分配修改失败: {e}")
                modifications_summary["pump_assignments"].append({
                    "error": str(e)
                })
        
        # 处理时间修改
        if request.time_modifications:
            try:
                # 使用apply_time_modifications批量处理所有时间修改（包含级联更新）
                modified_plan = service.apply_time_modifications(
                    modified_plan, 
                    request.time_modifications,
                    request.scenario_name  # 传递scenario_name
                )
                
                # 从tracking信息中获取修改统计
                tracking = modified_plan.get('modification_tracking', {}).get('time_modifications', {})
                
                # 记录修改摘要
                for time_mod in request.time_modifications:
                    modifications_summary["time_modifications"].append({
                        "batch_index": time_mod.batch_index,
                        "start_time_h": time_mod.start_time_h,
                        "duration_h": time_mod.duration_h,
                        "scenarios_affected": tracking.get('modified_scenarios', []),
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
        # 如果指定了scenario_name，只返回该scenario的数据
        if request.scenario_name:
            # 提取指定scenario的数据
            original_scenario = None
            modified_scenario = None
            
            # 从原始计划中提取指定scenario
            for scenario in original_plan.get('scenarios', []):
                if scenario.get('scenario_name') == request.scenario_name:
                    original_scenario = scenario
                    break
            
            # 从修改后的计划中提取指定scenario
            for scenario in modified_plan.get('scenarios', []):
                if scenario.get('scenario_name') == request.scenario_name:
                    modified_scenario = scenario
                    break
            
            response_data = {
                "success": True,
                "message": f"批次计划重新生成成功，共进行了 {modifications_summary['total_changes']} 项修改",
                "modified_plan_path": output_file,
                "scenario_name": request.scenario_name,
                "original_scenario": original_scenario,
                "modified_scenario": modified_scenario,
                "modifications_summary": modifications_summary
            }
        else:
            # 未指定scenario_name，返回完整计划
            response_data = {
                "success": True,
                "message": f"批次计划重新生成成功，共进行了 {modifications_summary['total_changes']} 项修改",
                "modified_plan_path": output_file,
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

@app.get("/api/regeneration/scenarios")
async def get_available_scenarios(plan_id: Optional[str] = None):
    """
    获取计划中所有可用的scenarios
    
    Args:
        plan_id: 计划ID或文件路径（可选，不提供则使用最新的计划文件）
        
    Returns:
        包含所有scenario信息的响应
    """
    try:
        from src.api.batch_regeneration_api import BatchRegenerationService
        service = BatchRegenerationService()
        
        # 如果没有提供plan_id，使用最新的计划文件
        if not plan_id:
            plan_id = service._find_latest_plan_file()
            if not plan_id:
                raise HTTPException(status_code=404, detail="未找到任何计划文件")
        
        result = service.get_available_scenarios(plan_id)
        
        return {
            "success": True,
            "message": f"成功获取 {result['total_scenarios']} 个scenario信息",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取可用scenarios失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取可用scenarios失败: {str(e)}")

@app.post("/api/regeneration/clear-cache")
async def clear_regeneration_cache():
    """
    清除批次重新生成和计划生成的所有缓存
    
    使用场景：
    - 需要强制重新生成计划时
    - 调试时需要查看实时结果
    - 缓存数据异常时
    
    Returns:
        清除结果信息
    """
    try:
        clear_cache()
        logger.info("所有缓存已清除")
        
        return {
            "success": True,
            "message": "所有缓存已清除",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除缓存失败: {str(e)}")

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
                    # 如果data/output目录没有文件，尝试查找data/output目录中的任何计划文件
                    logger.warning("data/output目录中没有找到计划文件")
                    data_output_dir = Path(__file__).parent / "data" / "output"
                    if data_output_dir.exists():
                        import glob
                        all_plans = glob.glob(str(data_output_dir / "*.json"))
                        if all_plans:
                            # 使用最新的文件
                            latest = max(all_plans, key=lambda x: Path(x).stat().st_mtime)
                            logger.info(f"尝试加载最新计划文件: {latest}")
                            _scheduler.load_irrigation_plan(latest)
                            plan = _scheduler.get_current_plan()
                            if plan:
                                logger.info(f"成功加载计划文件: {latest}")
                    
            except Exception as load_error:
                logger.error(f"加载计划文件失败: {load_error}")
                raise HTTPException(status_code=404, detail="当前没有执行计划，且无法加载任何计划文件。请先生成灌溉计划。")
        
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
        from src.optimizer.batch_adjustment_service import BatchAdjustmentService
        
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

@app.post("/api/batch/reorder", response_model=BatchReorderResponse)
async def reorder_batches(request: BatchReorderRequest):
    """
    批次顺序调整接口
    
    调整批次的执行顺序，通过修改批次的开始时间来实现。
    批次索引保持不变，但执行顺序会按照新顺序重新安排。
    
    - **plan_id**: 计划ID或文件路径
    - **new_order**: 新的批次执行顺序列表，例如 [2, 1, 3] 表示批次2先执行，然后批次1，最后批次3
    - **scenario_name**: 可选，指定要调整的scenario名称（如"P2单独使用"、"全部水泵(P1+P2)组合使用"等）
                        如果不指定，则调整所有scenario（要求所有scenario批次数量相同）
    
    ⚠️ 重要：不同scenario可能有不同数量的批次
    - P1单独使用：可能有10个批次
    - P2单独使用：可能有10个批次  
    - P1+P2组合使用：可能有5个批次（双泵流量大）
    
    建议：明确指定scenario_name参数，避免批次数量不匹配的错误
    
    使用场景：
    - 调整批次执行的先后顺序以优化资源利用
    - 根据紧急程度调整灌溉优先级
    - 适应临时的时间安排变化
    
    返回包含原始计划、重新排序后计划和变更摘要的响应。
    """
    try:
        logger.info(f"开始批次顺序调整 - plan_id: {request.plan_id}")
        logger.info(f"新顺序: {request.new_order}")
        
        # 导入批次调整服务
        from src.optimizer.batch_adjustment_service import BatchAdjustmentService
        
        # 创建服务实例
        service = BatchAdjustmentService()
        
        # 转换reorder_configs为字典格式
        reorder_configs = None
        if request.reorder_configs:
            reorder_configs = [
                {
                    "scenario_name": config.scenario_name,
                    "new_order": config.new_order
                }
                for config in request.reorder_configs
            ]
        
        # 执行批次顺序调整
        result = service.reorder_batches(
            plan_id=request.plan_id,
            new_order=request.new_order,
            scenario_name=request.scenario_name,
            reorder_configs=reorder_configs
        )
        
        logger.info(f"批次顺序调整完成 - {result['message']}")
        
        return BatchReorderResponse(
            success=result["success"],
            message=result["message"],
            original_plan=result["original_plan"],
            reordered_plan=result["reordered_plan"],
            changes_summary=result["changes_summary"],
            validation=result["validation"],
            output_file=result.get("output_file")
        )
        
    except ValueError as ve:
        logger.error(f"批次顺序调整验证失败: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except FileNotFoundError as fnf:
        logger.error(f"计划文件未找到: {fnf}")
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as e:
        logger.error(f"批次顺序调整失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"批次顺序调整失败: {str(e)}")

# ==================== 灌溉计划生成API ====================

@app.post("/api/irrigation/plan-generation", response_model=IrrigationPlanResponse)
async def generate_irrigation_plan(request: IrrigationPlanRequest):
    """生成灌溉计划（支持多水泵方案对比和缓存）"""
    try:
        logger.info(f"开始生成灌溉计划 - farm_id: {request.farm_id}")
        logger.info(f"请求参数: output_dir={request.output_dir}, config_path={request.config_path}, multi_pump_scenarios={request.multi_pump_scenarios}")
        
        # 生成缓存键
        logger.info("步骤1: 生成缓存键...")
        cache_key = generate_cache_key(
            farm_id=request.farm_id,
            target_depth_mm=90.0,  # 默认值
            pumps="",
            zones="",
            merge_waterlevels=True,
            print_summary=True,
            multi_pump_scenarios=request.multi_pump_scenarios or False
        )
        logger.info(f"缓存键生成成功: {cache_key}")
        
        # 尝试从缓存获取结果
        logger.info("步骤2: 检查缓存...")
        cached_result = get_from_cache(cache_key)
        if cached_result:
            logger.info(f"从缓存返回灌溉计划结果 - cache_key: {cache_key}")
            return IrrigationPlanResponse(**cached_result)
        logger.info("缓存未命中，继续执行...")
        
        # 导入pipeline模块
        logger.info("步骤3: 导入pipeline模块...")
        try:
            from src.core.pipeline import IrrigationPipeline
            logger.info("pipeline模块导入成功")
        except ImportError as e:
            logger.error(f"导入pipeline模块失败: {e}")
            raise HTTPException(status_code=500, detail="系统模块导入失败")
        
        # 设置默认参数
        logger.info("步骤4: 设置默认参数...")
        output_dir = request.output_dir or os.path.join(os.path.dirname(__file__), "data", "output")
        config_path = request.config_path or os.path.join(os.path.dirname(__file__), "config.json")
        logger.info(f"output_dir: {output_dir}")
        logger.info(f"config_path: {config_path}")
        
        # 确保输出目录存在
        logger.info("步骤5: 确保输出目录存在...")
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"输出目录已创建/确认: {output_dir}")
        
        # 构建pipeline参数
        logger.info("步骤6: 构建pipeline参数...")
        
        # 关键：传递 config_file 参数，告诉 pipeline 使用现有配置（不重新生成）
        # 这确保了 Rice 决策的配置不会被覆盖
        kwargs = {
            'input_dir': os.path.join(os.path.dirname(__file__), "data", "gzp_farm"),
            'output_dir': output_dir,
            'config_file': config_path,  # 总是传递 config_file，跳过配置生成步骤
            'merge_waterlevels': True,
            'print_summary': True,
            'multi_pump_scenarios': request.multi_pump_scenarios or False
        }
        
        logger.info(f"Pipeline参数: {kwargs}")
        
        # 运行灌溉计划生成
        logger.info("步骤7: 创建Pipeline实例...")
        try:
            pipeline = IrrigationPipeline()
            logger.info("Pipeline实例创建成功")
            logger.info("步骤8: 运行Pipeline...")
            success = pipeline.run_pipeline(**kwargs)
            logger.info(f"Pipeline执行结果: success={success}")
        except Exception as pipeline_error:
            logger.error(f"Pipeline执行异常: {pipeline_error}")
            import traceback
            logger.error(traceback.format_exc())
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
                
                # 创建农场配置（启用实时水位，如果API可用）
                cfg = farmcfg_from_json_select(config_data, use_realtime_wl=True)
                
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
            from src.core.pipeline import IrrigationPipeline
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
                    
                    # 创建农场配置（启用实时水位，如果API可用）
                    cfg = farmcfg_from_json_select(config_data, use_realtime_wl=True)
                    
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
    """获取田块GeoJson数据（动态适配当前农场）"""
    try:
        geojson_files = get_current_farm_geojson_files()
        field_file = geojson_files.get('fields', '')
        
        p = _first_existing(LABELED_FIELDS, os.path.join(GEOJSON_DIR, field_file))
        if not p:
            raise HTTPException(status_code=404, detail=f"未找到田块图层，尝试的文件: {field_file}")
        
        gdf = read_geo_ensure_wgs84(p)
        return JSONResponse(content=json.loads(gdf.to_json()))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取田块GeoJson数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取田块数据失败: {str(e)}")

@app.get("/geojson/gates")
async def api_gates():
    """获取闸门GeoJson数据（动态适配当前农场）"""
    try:
        geojson_files = get_current_farm_geojson_files()
        gates_file = geojson_files.get('gates', '')
        
        p = _first_existing(LABELED_GATES, os.path.join(GEOJSON_DIR, gates_file))
        if not p:
            raise HTTPException(status_code=404, detail=f"未找到闸门图层，尝试的文件: {gates_file}")
        
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
            geojson_files = get_current_farm_geojson_files()
            segments_file = geojson_files.get('segments', '')
            
            p = _first_existing(LABELED_SEGMENT, os.path.join(GEOJSON_DIR, segments_file))
            if not p:
                raise HTTPException(status_code=404, detail=f"未找到水路图层，尝试的文件: {segments_file}")
            
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

@app.get("/api/hardware/fields-device-status", response_model=FieldDeviceStatusResponse)
async def get_fields_device_status(
    farm_id: str,
    app_id: Optional[str] = None,
    secret: Optional[str] = None,
    iot_app_id: Optional[str] = None,
    iot_secret: Optional[str] = None,
    timeout: int = 30,
    verbose: bool = False
):
    """
    根据农场ID获取所有田块对应设备的状态
    
    完整流程：
    1. 根据农场ID获取农场名称（从 farm_id_mapping.json）
    2. 根据农场名称查找CSV文件，提取田块ID列表
    3. 对每个田块ID，获取其设备映射（田块ID -> 设备编码 -> 设备信息 -> uniqueNo）
    4. 对每个设备的uniqueNo，查询设备状态（闸门开度等）
    
    Args:
        farm_id: 农场ID（如：13944136728576 港中坪）
        app_id: iLand平台应用ID（用于查询设备信息，默认YJY）
        secret: iLand平台密钥（默认test005）
        iot_app_id: IoT平台应用ID（用于查询设备状态，默认siotextend）
        iot_secret: IoT平台密钥（用于查询设备状态）
        timeout: 请求超时时间（秒）
        verbose: 是否打印详细信息
        
    Returns:
        FieldDeviceStatusResponse: 所有田块设备状态
    """
    try:
        logger.info(f"开始查询农场 {farm_id} 的所有田块设备状态")
        
        # 从环境变量或配置获取 app_id 和 secret（如果未提供）
        if not app_id:
            app_id = os.environ.get("ILAND_APP_ID") or "YJY"
        if not secret:
            secret = os.environ.get("ILAND_SECRET") or "test005"
        if not iot_app_id:
            iot_app_id = os.environ.get("IOT_APP_ID") or "siotextend"
        if not iot_secret:
            iot_secret = os.environ.get("IOT_SECRET") or "!iWu$fyUgOSH+mc_nSirKpL%+zZ%)%cL"
        
        logger.info(f"使用 iLand app_id: {app_id[:4]}... (已隐藏)")
        logger.info(f"使用 IoT app_id: {iot_app_id[:4]}... (已隐藏)")
        
        # 调用批量查询函数
        result = get_all_fields_device_status(
            app_id=app_id,
            secret=secret,
            farm_id=farm_id,
            iot_app_id=iot_app_id,
            iot_secret=iot_secret,
            timeout=timeout,
            verbose=verbose
        )
        
        if result.get("success"):
            logger.info(f"✅ 成功查询农场 {farm_id} 的设备状态，共 {result.get('total_fields', 0)} 个田块")
            return FieldDeviceStatusResponse(
                success=True,
                message=f"成功获取 {result.get('farm_name', '')} 农场所有田块设备状态",
                data=result
            )
        else:
            error_msg = result.get("error", "未知错误")
            logger.error(f"❌ 查询失败: {error_msg}")
            return FieldDeviceStatusResponse(
                success=False,
                message="查询失败",
                data=result,
                error=error_msg
            )
            
    except Exception as e:
        logger.error(f"查询田块设备状态失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"查询田块设备状态失败: {str(e)}"
        )

@app.post("/api/hardware/device-self-check-workflow", response_model=DeviceSelfCheckResponse)
async def device_self_check_workflow(request: DeviceSelfCheckRequest):
    """
    设备自检完整工作流
    
    工作流程：
    1. 获取当前灌溉计划，提取需要灌溉的田块
    2. 通过田块ID获取设备unique_no列表
    3. 调用设备自检接口
    4. 等待指定时间（默认5分钟）
    5. 查询设备状态（支持轮询模式，持续查询直到完成）
    6. 过滤自检成功的设备，找到对应田块
    7. 移除自检失败的田块，重新生成灌溉计划
    8. 返回新计划中需要灌溉的设备ID列表
    
    轮询模式：
    - enable_polling=True: 持续查询设备状态，直到所有设备完成自检或达到最大次数
    - enable_polling=False: 只查询一次（可能有设备还在自检中）
    
    注意：已移除预检查步骤，直接对所有iLand平台返回的设备触发自检
    """
    try:
        logger.info(f"========== 开始设备自检工作流 ==========")
        logger.info(f"农场ID: {request.farm_id}, 等待时间: {request.wait_minutes}分钟")
        
        # 从环境变量或请求中获取认证信息
        app_id = request.app_id or os.environ.get("ILAND_APP_ID") or "YJY"
        secret = request.secret or os.environ.get("ILAND_SECRET") or "test005"
        
        # 步骤1: 获取灌溉计划中的田块列表
        logger.info("步骤1: 获取当前灌溉计划...")
        
        from pathlib import Path
        if request.plan_id:
            plan_file = request.plan_id if os.path.isabs(request.plan_id) else os.path.join(OUTPUT_DIR, request.plan_id)
        else:
            plan_files = sorted(Path(OUTPUT_DIR).glob("irrigation_plan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not plan_files:
                return DeviceSelfCheckResponse(
                    success=False,
                    message="未找到灌溉计划文件",
                    error="请先生成灌溉计划"
                )
            plan_file = str(plan_files[0])
        
        logger.info(f"使用计划文件: {plan_file}")
        
        with open(plan_file, 'r', encoding='utf-8') as f:
            plan_data = json.load(f)
        
        # 提取需要灌溉的田块ID列表
        irrigation_fields = set()
        scenarios_to_check = []
        
        if request.scenario_name:
            scenarios_to_check = [s for s in plan_data.get("scenarios", []) if s.get("scenario_name") == request.scenario_name]
        else:
            scenarios_to_check = plan_data.get("scenarios", [])[:1]  # 使用第一个scenario
        
        if not scenarios_to_check:
            return DeviceSelfCheckResponse(
                success=False,
                message=f"未找到方案: {request.scenario_name or '默认方案'}",
                error="请检查方案名称或计划文件"
            )
        
        for scenario in scenarios_to_check:
            # 注意：田块数据在 plan.batches 路径下
            batches = scenario.get("plan", {}).get("batches", [])
            for batch in batches:
                for field in batch.get("fields", []):
                    irrigation_fields.add(field.get("id"))
        
        logger.info(f"找到需要灌溉的田块: {len(irrigation_fields)} 个")
        
        if not irrigation_fields:
            return DeviceSelfCheckResponse(
                success=False,
                message="灌溉计划中没有田块",
                error="计划文件可能为空或格式不正确"
            )
        
        # 步骤2: 获取田块对应的设备unique_no
        logger.info("步骤2: 获取田块对应的设备unique_no...")
        
        fields_device_status = get_all_fields_device_status(
            app_id=app_id,
            secret=secret,
            farm_id=request.farm_id,
            timeout=request.timeout,
            verbose=False
        )
        
        if not fields_device_status.get("success"):
            return DeviceSelfCheckResponse(
                success=False,
                message="获取田块设备信息失败",
                error=fields_device_status.get("error")
            )
        
        # 建立田块ID到设备unique_no的映射
        field_to_devices = {}
        device_to_field = {}
        all_unique_nos = []
        
        for field in fields_device_status.get("fields", []):
            # 优先使用 section_code (S-G-F格式)，如果没有则使用 field_id
            section_code = field.get("section_code")
            field_id = section_code if section_code else field.get("field_id")
            
            # 匹配灌溉计划中的田块
            if field_id not in irrigation_fields:
                continue
            
            devices = field.get("devices", [])
            device_unique_nos = []
            
            for device in devices:
                unique_no = device.get("unique_no")
                if unique_no:
                    device_unique_nos.append(unique_no)
                    all_unique_nos.append(unique_no)
                    device_to_field[unique_no] = field_id
            
            field_to_devices[field_id] = device_unique_nos
            
            logger.debug(f"田块 {field_id}: 找到 {len(device_unique_nos)} 个设备")
        
        logger.info(f"需要自检的设备总数: {len(all_unique_nos)}")
        
        if not all_unique_nos:
            return DeviceSelfCheckResponse(
                success=False,
                message="未找到需要自检的设备",
                error="灌溉田块可能没有关联设备"
            )
        
        # 步骤3: 触发设备自检（已移除预检查步骤）
        logger.info("步骤3: 触发设备自检...")
        
        check_result = trigger_device_self_check(all_unique_nos, timeout=request.timeout)
        
        if not check_result.get("success"):
            return DeviceSelfCheckResponse(
                success=False,
                message="触发设备自检失败",
                error=check_result.get("error")
            )
        
        accepted_devices = check_result.get("accepted_no_list", [])
        logger.info(f"✅ 自检任务已接受，设备数: {len(accepted_devices)}")
        
        # 步骤4: 等待设备自检完成
        wait_seconds = request.wait_minutes * 60
        logger.info(f"步骤4: 等待 {request.wait_minutes} 分钟，让设备完成自检...")
        
        await asyncio.sleep(wait_seconds)
        
        # 步骤5: 查询设备状态（支持轮询）
        logger.info("步骤5: 查询设备自检状态...")
        
        devices_status = []
        if request.enable_polling:
            # 轮询模式：持续查询直到所有设备完成或达到最大次数
            logger.info(f"🔄 启用轮询模式，最多尝试 {request.max_polling_attempts} 次，间隔 {request.polling_interval_seconds} 秒")
            
            for attempt in range(1, request.max_polling_attempts + 1):
                logger.info(f"📊 第 {attempt}/{request.max_polling_attempts} 次查询...")
                
                status_result = query_device_status(all_unique_nos, timeout=request.timeout)
                
                if not status_result.get("success"):
                    logger.warning(f"⚠️ 查询失败: {status_result.get('error')}")
                    if attempt == request.max_polling_attempts:
                        return DeviceSelfCheckResponse(
                            success=False,
                            message="查询设备状态失败",
                            error=status_result.get("error")
                        )
                    await asyncio.sleep(request.polling_interval_seconds)
                    continue
                
                devices_status = status_result.get("devices", [])
                summary = get_device_status_summary(devices_status)
                
                logger.info(f"状态统计: 成功={len(summary['successful'])}, 自检中={len(summary['checking'])}, 失败={len(summary['failed'])}")
                
                # 如果没有设备还在自检中，就退出轮询
                if not summary['checking']:
                    logger.info(f"✅ 所有设备已完成自检（成功+失败）")
                    break
                
                # 如果不是最后一次尝试，等待后继续
                if attempt < request.max_polling_attempts:
                    logger.info(f"还有 {len(summary['checking'])} 个设备在自检中，{request.polling_interval_seconds}秒后重试...")
                    await asyncio.sleep(request.polling_interval_seconds)
                else:
                    logger.warning(f"⚠️ 已达到最大轮询次数，仍有 {len(summary['checking'])} 个设备在自检中")
        else:
            # 单次查询模式
            status_result = query_device_status(all_unique_nos, timeout=request.timeout)
            
            if not status_result.get("success"):
                return DeviceSelfCheckResponse(
                    success=False,
                    message="查询设备状态失败",
                    error=status_result.get("error")
                )
            
            devices_status = status_result.get("devices", [])
        
        # 步骤6: 过滤自检成功的设备
        logger.info("步骤6: 过滤自检成功的设备...")
        
        successful_devices = filter_successful_devices(devices_status)
        failed_devices = [d["no"] for d in devices_status if d.get("status") not in ["check_success", "checking"]]
        checking_devices = [d["no"] for d in devices_status if d.get("status") == "checking"]
        
        # 将还在自检中的设备也视为失败（因为超时了）
        if checking_devices:
            logger.warning(f"⚠️ 有 {len(checking_devices)} 个设备超时仍在自检中，将被视为失败")
            failed_devices.extend(checking_devices)
        
        logger.info(f"自检成功: {len(successful_devices)} 个设备, 失败: {len(failed_devices)} 个设备")
        
        # 找到自检失败的田块
        failed_fields = set()
        for device_no in failed_devices:
            field_id = device_to_field.get(device_no)
            if field_id:
                failed_fields.add(field_id)
        
        logger.info(f"需要移除的田块（设备自检失败）: {len(failed_fields)} 个")
        
        # 步骤7: 重新生成灌溉计划
        new_plan_file = None
        final_device_list = []
        
        if request.auto_regenerate and failed_fields:
            logger.info("步骤7: 重新生成灌溉计划，排除自检失败的田块...")
            
            try:
                modified_plan = json.loads(json.dumps(plan_data))
                
                for scenario in modified_plan.get("scenarios", []):
                    if request.scenario_name and scenario.get("scenario_name") != request.scenario_name:
                        continue
                    
                    # 注意：田块数据在 plan.batches 路径下
                    plan = scenario.get("plan", {})
                    if "batches" in plan:
                        for batch in plan["batches"]:
                            batch["fields"] = [f for f in batch.get("fields", []) if f.get("id") not in failed_fields]
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_plan_file = os.path.join(OUTPUT_DIR, f"irrigation_plan_selfcheck_{timestamp}.json")
                with open(new_plan_file, 'w', encoding='utf-8') as f:
                    json.dump(modified_plan, f, ensure_ascii=False, indent=2)
                
                logger.info(f"✅ 新计划已生成: {new_plan_file}")
                
                # 从新计划中提取设备列表
                successful_fields = irrigation_fields - failed_fields
                for field_id in successful_fields:
                    final_device_list.extend(field_to_devices.get(field_id, []))
                
            except Exception as e:
                logger.error(f"重新生成计划失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            successful_fields = irrigation_fields - failed_fields
            for field_id in successful_fields:
                final_device_list.extend(field_to_devices.get(field_id, []))
        
        # 步骤8: 返回结果
        logger.info("步骤8: 整理结果...")
        
        result_data = {
            "total_devices": len(all_unique_nos),
            "successful_devices": len(successful_devices),
            "failed_devices": len(failed_devices),
            "total_fields": len(irrigation_fields),
            "successful_fields": len(irrigation_fields) - len(failed_fields),
            "failed_fields": len(failed_fields),
            "failed_field_ids": list(failed_fields),
            "device_status_details": devices_status,
            "final_device_list": final_device_list,
            "new_plan_file": new_plan_file,
            "original_plan_file": plan_file
        }
        
        logger.info(f"========== 设备自检工作流完成 ==========")
        logger.info(f"总设备: {len(all_unique_nos)}, 成功: {len(successful_devices)}, 失败: {len(failed_devices)}")
        logger.info(f"总田块: {len(irrigation_fields)}, 保留: {len(irrigation_fields) - len(failed_fields)}, 移除: {len(failed_fields)}")
        
        return DeviceSelfCheckResponse(
            success=True,
            message=f"设备自检完成，{len(successful_devices)}/{len(all_unique_nos)} 个设备自检成功",
            data=result_data
        )
        
    except Exception as e:
        logger.error(f"设备自检工作流失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"设备自检工作流失败: {str(e)}"
        )

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
        from src.api.batch_regeneration_api import BatchRegenerationService
        from src.optimizer.intelligent_batch_optimizer import IntelligentBatchOptimizer
        
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

# ==================== Rice 智能决策集成 API ====================

class UpdateConfigFromRiceRequest(BaseModel):
    """独立配置更新请求（基于Rice决策）"""
    farm_id: str = Field(..., description="农场ID")
    rice_api_url: str = Field(
        default="http://rice-backend:5000/v1/rice_irrigation",  # Docker 容器名访问
        description="Rice API地址"
    )

class UpdateConfigFromRiceResponse(BaseModel):
    """独立配置更新响应"""
    success: bool
    message: str
    decision_count: int = Field(default=0, description="总决策数量")
    irrigate_count: int = Field(default=0, description="需要灌溉的田块数量")
    config_backup: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class RiceIntegrationRequest(BaseModel):
    """Rice智能决策集成请求（一体化：更新配置+生成计划）"""
    farm_id: str = Field(..., description="农场ID")
    rice_api_url: str = Field(
        "http://rice-backend:5000/v1/rice_irrigation",  # Docker 容器名访问
        description="Rice API地址"
    )
    pumps: str = Field("P1,P2", description="启用的水泵")
    time_constraints: bool = Field(False, description="是否启用时间约束")
    auto_execute: bool = Field(False, description="是否自动执行")

class RiceIntegrationResponse(BaseModel):
    """Rice智能决策集成响应"""
    success: bool
    message: str
    decision_count: int = 0
    irrigate_count: int = 0
    plan_file: Optional[str] = None
    execution_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

@app.post("/api/irrigation/update-config-from-rice", response_model=UpdateConfigFromRiceResponse)
async def update_config_from_rice(request: UpdateConfigFromRiceRequest):
    """
    独立的配置更新接口：从 Rice 获取决策并更新 config.json
    
    **设计理念**:
    - 职责单一：只负责配置更新，不生成计划
    - 灵活复用：更新后可调用任意接口（计划生成、批次重生成、执行等）
    - RESTful 设计：符合单一职责原则
    
    **工作流程**:
    1. 调用 Rice API 获取智能灌溉决策
    2. 映射田块ID (sectionID → field_id)
    3. 备份当前 config.json
    4. 更新 config.json 中的水位参数：
       - wl_mm: 当前水位（Rice 提供）
       - wl_low: current + 1（强制触发灌溉）
       - wl_opt: Rice 目标水位
    5. 返回更新详情和备份路径
    
    **后续使用**:
    更新配置后，可以调用以下任意接口：
    - /api/irrigation/plan-generation（生成计划）
    - /api/regeneration/batch（批次重新生成）
    - /api/execution/plan（执行计划）
    - /api/water-levels/targets（查看水位目标）
    
    **示例**:
    ```bash
    # 1. 先更新配置
    curl -X POST "http://localhost:8000/api/irrigation/update-config-from-rice" \\
      -H "Content-Type: application/json" \\
      -d '{"farm_id": "13944136728576"}'
    
    # 2. 再生成计划（使用 Rice 配置）
    curl -X POST "http://localhost:8000/api/irrigation/plan-generation" \\
      -H "Content-Type: application/json" \\
      -d '{"farm_id": "13944136728576"}'
    ```
    
    **与一体化接口的区别**:
    - 一体化接口 (/generate-from-rice): 更新配置 + 生成计划（一键式）
    - 独立接口 (本接口): 只更新配置（更灵活）
    """
    try:
        logger.info(f"开始更新配置 - 基于 Rice 决策, farm_id: {request.farm_id}")
        
        # ===== 步骤1: 调用 Rice API =====
        logger.info(f"步骤1: 调用 Rice API: {request.rice_api_url}")
        
        try:
            response = requests.get(
                request.rice_api_url,
                params={"farm_id": request.farm_id, "debug": "0"},
                timeout=30
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail=f"Rice API 返回错误: {response.status_code}"
                )
            
            rice_decisions = response.json()
            logger.info(f"✓ 成功获取 Rice 决策，共 {len(rice_decisions)} 项")
            
        except requests.exceptions.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="无法连接到 Rice 服务，请确保 Rice API 已启动 (python app.py)"
            )
        except requests.exceptions.Timeout:
            raise HTTPException(
                status_code=504,
                detail="Rice API 响应超时（30秒）"
            )
        
        # ===== 步骤2: 加载 config.json 并映射 ID =====
        logger.info("步骤2: 加载配置并映射 ID...")
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 构建 sectionID → field_id 映射
        section_to_field = {}
        for field in config.get('fields', []):
            section_id = field.get('sectionID')
            field_id = field.get('id')
            if section_id and field_id:
                section_to_field[section_id] = field_id
        
        logger.info(f"✓ 成功映射 {len(section_to_field)} 个田块")
        
        # ===== 步骤3: 转换 Rice 决策为 field_id 格式 =====
        logger.info("步骤3: 转换 Rice 决策...")
        
        field_targets = {}
        custom_waterlevels = {}
        skipped = []
        
        for section_id, decision in rice_decisions.items():
            if section_id == 'log':
                continue
            
            action = decision.get('action', 'none')
            if action != 'irrigate':
                continue
            
            # 映射到 field_id
            field_id = section_to_field.get(section_id)
            if not field_id:
                skipped.append(section_id)
                continue
            
            # 提取关键参数
            current_wl = decision.get('current_waterlevel', 0)
            target_wl = decision.get('target', 50)
            
            field_targets[field_id] = target_wl
            custom_waterlevels[field_id] = current_wl
        
        logger.info(f"✓ 转换完成：{len(custom_waterlevels)} 个田块需要灌溉")
        if skipped:
            logger.warning(f"跳过 {len(skipped)} 个未映射的 section: {skipped[:5]}...")
        
        # ===== 步骤4: 备份并修改 config.json =====
        logger.info("步骤4: 备份并更新 config.json...")
        
        # 确保备份目录存在
        backup_dir = os.path.join(os.path.dirname(__file__), "data", "config_backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        # 备份原始配置
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f"config_backup_{timestamp}.json")
        
        import shutil
        shutil.copy2(config_path, backup_path)
        logger.info(f"✓ 原始配置已备份: {backup_path}")
        
        # 记录修改详情
        rice_modifications = {
            "timestamp": timestamp,
            "source": "rice_smart_irrigation",
            "farm_id": request.farm_id,
            "modified_fields": {}
        }
        
        # 直接修改 config.json 中的字段
        modified_count = 0
        for field in config['fields']:
            field_id = field['id']
            if field_id in field_targets:
                original_wl_low = field.get('wl_low', 30.0)
                original_wl_opt = field.get('wl_opt', 80.0)
                original_wl_mm = field.get('wl_mm', 0)
                
                field['wl_mm'] = custom_waterlevels[field_id]
                field['wl_low'] = custom_waterlevels[field_id] + 1  # 强制触发
                field['wl_opt'] = field_targets[field_id]           # Rice 的目标
                
                rice_modifications["modified_fields"][field_id] = {
                    "original": {
                        "wl_low": original_wl_low,
                        "wl_opt": original_wl_opt,
                        "wl_mm": original_wl_mm
                    },
                    "rice_decision": {
                        "wl_low": field['wl_low'],
                        "wl_opt": field['wl_opt'],
                        "wl_mm": field['wl_mm']
                    }
                }
                modified_count += 1
                logger.info(f"  田块 {field_id}: wl_low={original_wl_low}→{field['wl_low']}, wl_opt={original_wl_opt}→{field['wl_opt']}")
            else:
                # Rice 说不灌溉的田块 - 设置很高的阈值
                field['wl_low'] = 999
        
        # 添加 Rice 元数据到配置
        config['_rice_integration'] = rice_modifications
        
        # 保存修改后的配置
        logger.info(f"准备写入配置文件: {config_path}")
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info(f"✓ config.json 已成功更新（修改 {modified_count} 个田块）")
            logger.info(f"✓ 备份文件: {backup_path}")
        except Exception as write_error:
            logger.error(f"❌ 写入配置文件失败: {write_error}")
            raise
        
        # ===== 返回结果 =====
        return UpdateConfigFromRiceResponse(
            success=True,
            message=f"成功！config.json 已基于 Rice 决策更新（{len(custom_waterlevels)} 个田块）",
            decision_count=len(rice_decisions) - 1 if 'log' in rice_decisions else len(rice_decisions),
            irrigate_count=len(custom_waterlevels),
            config_backup=backup_path.replace('\\', '/'),
            details={
                "skipped_sections": skipped,
                "mapping_count": len(section_to_field),
                "converted_count": len(custom_waterlevels),
                "rice_modifications": rice_modifications,
                "next_steps": [
                    "可以调用 /api/irrigation/plan-generation 生成计划",
                    "可以调用 /api/regeneration/batch 重新生成批次",
                    "可以调用 /api/water-levels/targets 查看更新后的水位",
                    "可以调用 /api/irrigation/restore-config 恢复原配置"
                ]
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"更新配置失败: {str(e)}"
        )

@app.post("/api/irrigation/generate-from-rice", response_model=RiceIntegrationResponse)
async def generate_plan_from_rice_decisions(request: RiceIntegrationRequest):
    """
    基于 Rice 智能决策生成灌溉计划（一体化接口）
    
    **架构说明**:
    - rice_smart_irrigation: 独立服务，提供智能决策 API
    - farm_irrigation: 独立服务，负责计划生成和执行
    - 两个服务通过 HTTP API 通信，完全解耦
    
    **工作流程**:
    1. 调用 Rice API 获取智能决策 (HTTP)
    2. 映射田块ID (section_id → field_id)
    3. 更新 config.json（内部调用配置更新逻辑）
    4. 调用现有的计划生成接口
    5. (可选) 自动启动执行
    
    **示例**:
    ```bash
    curl -X POST "http://localhost:8000/api/irrigation/generate-from-rice" \\
      -H "Content-Type: application/json" \\
      -d '{
        "farm_id": "13944136728576",
        "rice_api_url": "http://localhost:5000/v1/rice_irrigation",
        "pumps": "P1,P2"
      }'
    ```
    
    **与独立接口的区别**:
    - 独立接口 (/update-config-from-rice): 只更新配置（更灵活）
    - 一体化接口 (本接口): 更新配置 + 生成计划（一键式）
    
    **与传统方法的区别**:
    - 传统: 基于固定阈值 (wl_low/wl_opt)
    - Rice集成: 基于生育期、天气、农事操作的动态决策
    """
    try:
        logger.info(f"开始基于 Rice 决策生成计划 - farm_id: {request.farm_id}")
        
        # ===== 步骤1: 调用 Rice API =====
        logger.info(f"调用 Rice API: {request.rice_api_url}")
        
        try:
            import requests
            response = requests.get(
                request.rice_api_url,
                params={'farm_id': request.farm_id},
                timeout=30
            )
            response.raise_for_status()
            rice_decisions = response.json()
            
            # 统计决策
            irrigate_fields = {}
            for section_id, decision in rice_decisions.items():
                if section_id == 'log':
                    continue
                if decision.get('action') == 'irrigate':
                    irrigate_fields[section_id] = decision
            
            logger.info(f"✓ 获取到 {len(irrigate_fields)} 个灌溉决策")
            
        except requests.exceptions.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="无法连接到 Rice API，请确保 rice_smart_irrigation 服务正在运行"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"调用 Rice API 失败: {str(e)}"
            )
        
        if not irrigate_fields:
            return RiceIntegrationResponse(
                success=True,
                message="Rice 决策获取成功，但没有需要灌溉的田块",
                decision_count=len(rice_decisions) - 1 if 'log' in rice_decisions else len(rice_decisions),
                irrigate_count=0
            )
        
        # ===== 步骤2: 映射田块ID =====
        logger.info("加载田块映射...")
        
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 建立映射: section_id → field_id
        section_to_field = {}
        for field in config.get('fields', []):
            section_id = str(field.get('sectionID'))
            if section_id:
                section_to_field[section_id] = field.get('id')
        
        # ===== 步骤3: 构造参数 =====
        logger.info("构造自定义水位参数...")
        
        custom_waterlevels = {}
        field_targets = {}
        skipped = []
        
        for section_id, decision in irrigate_fields.items():
            if section_id not in section_to_field:
                skipped.append(section_id)
                logger.warning(f"田块 {section_id} 未找到映射，跳过")
                continue
            
            field_id = section_to_field[section_id]
            current_wl = decision.get('current_waterlevel')
            target_wl = decision.get('target')
            
            if current_wl is not None and target_wl is not None:
                custom_waterlevels[field_id] = current_wl
                field_targets[field_id] = target_wl
        
        logger.info(f"✓ 成功转换 {len(custom_waterlevels)} 个田块")
        
        # ===== 步骤4: 备份并修改 config.json =====
        logger.info("备份并更新 config.json...")
        
        # 备份原始配置（保存到 data/config_backup 目录）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = os.path.join(os.path.dirname(__file__), "data", "config_backup")
        os.makedirs(backup_dir, exist_ok=True)  # 确保备份目录存在
        
        backup_path = os.path.join(
            backup_dir,
            f"config_backup_{timestamp}.json"
        )
        
        import shutil
        shutil.copy2(config_path, backup_path)
        logger.info(f"✓ 原始配置已备份: {backup_path}")
        
        # 记录修改详情
        rice_modifications = {
            "timestamp": timestamp,
            "source": "rice_smart_irrigation",
            "farm_id": request.farm_id,
            "modified_fields": {}
        }
        
        # 直接修改 config.json 中的字段
        for field in config['fields']:
            field_id = field['id']
            if field_id in field_targets:
                # Rice 说要灌溉的田块
                original_wl_low = field.get('wl_low', 30.0)
                original_wl_opt = field.get('wl_opt', 80.0)
                
                field['wl_mm'] = custom_waterlevels[field_id]
                field['wl_low'] = custom_waterlevels[field_id] + 1  # 强制触发
                field['wl_opt'] = field_targets[field_id]           # Rice 的目标
                
                # 记录修改
                rice_modifications["modified_fields"][field_id] = {
                    "original": {
                        "wl_low": original_wl_low,
                        "wl_opt": original_wl_opt,
                        "wl_mm": field.get('wl_mm', 0)
                    },
                    "rice_decision": {
                        "wl_low": field['wl_low'],
                        "wl_opt": field['wl_opt'],
                        "wl_mm": field['wl_mm']
                    }
                }
                logger.info(f"  田块 {field_id}: wl_low={original_wl_low}→{field['wl_low']}, wl_opt={original_wl_opt}→{field['wl_opt']}")
            else:
                # Rice 说不灌溉的田块 - 设置很高的阈值
                field['wl_low'] = 999
        
        # 添加 Rice 元数据到配置
        config['_rice_integration'] = rice_modifications
        
        # 保存修改后的配置
        logger.info(f"准备写入配置文件: {config_path}")
        logger.info(f"修改的田块数量: {len(rice_modifications['modified_fields'])}")
        
        # 调试：检查第一个田块的修改
        if len(rice_modifications['modified_fields']) > 0:
            first_field_id = list(rice_modifications['modified_fields'].keys())[0]
            first_field_data = rice_modifications['modified_fields'][first_field_id]
            logger.info(f"示例田块 {first_field_id}:")
            logger.info(f"  原值: wl_low={first_field_data['original']['wl_low']}, wl_opt={first_field_data['original']['wl_opt']}")
            logger.info(f"  新值: wl_low={first_field_data['rice_decision']['wl_low']}, wl_opt={first_field_data['rice_decision']['wl_opt']}")
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info(f"✓ config.json 已成功写入（备份: {backup_path}）")
            
            # 验证写入
            with open(config_path, 'r', encoding='utf-8') as f:
                verify_config = json.load(f)
            
            # 检查是否包含 _rice_integration
            if '_rice_integration' in verify_config:
                logger.info("✓ 验证成功: _rice_integration 元数据已写入")
            else:
                logger.error("❌ 验证失败: _rice_integration 元数据未找到")
            
            # 检查第一个田块
            if len(rice_modifications['modified_fields']) > 0:
                first_field_id = list(rice_modifications['modified_fields'].keys())[0]
                verify_field = next((f for f in verify_config['fields'] if f['id'] == first_field_id), None)
                if verify_field:
                    logger.info(f"✓ 验证田块 {first_field_id}: wl_low={verify_field['wl_low']}, wl_opt={verify_field['wl_opt']}")
                else:
                    logger.error(f"❌ 验证失败: 田块 {first_field_id} 未找到")
                    
        except Exception as write_error:
            logger.error(f"❌ 写入配置文件失败: {write_error}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        
        # ===== 步骤5: 调用现有的计划生成接口 =====
        logger.info("调用计划生成...")
        
        # 使用更新后的 config.json
        plan_request = IrrigationPlanRequest(
            farm_id=request.farm_id,
            config_path=config_path,  # 使用修改后的 config.json
            output_dir=os.path.join(os.path.dirname(__file__), "data", "output")
        )
        
        plan_response = await generate_irrigation_plan(plan_request)
        
        if not plan_response.success:
            raise HTTPException(
                status_code=500,
                detail=f"计划生成失败: {plan_response.message}"
            )
        
        # ===== 重要：计划生成后再次写入配置 =====
        # 因为 generate_irrigation_plan 可能会重新加载/保存 config.json
        logger.info("计划生成完成，再次写入 Rice 配置...")
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("✓ Rice 配置已再次写入（确保不被覆盖）")
            
            # 最终验证
            with open(config_path, 'r', encoding='utf-8') as f:
                final_verify = json.load(f)
            
            if '_rice_integration' in final_verify:
                logger.info("✓ 最终验证成功: config.json 包含 Rice 配置")
                
                # 检查一个示例田块
                if len(rice_modifications['modified_fields']) > 0:
                    sample_field_id = list(rice_modifications['modified_fields'].keys())[0]
                    sample_field = next((f for f in final_verify['fields'] if f['id'] == sample_field_id), None)
                    if sample_field:
                        expected_wl_opt = rice_modifications['modified_fields'][sample_field_id]['rice_decision']['wl_opt']
                        actual_wl_opt = sample_field['wl_opt']
                        if actual_wl_opt == expected_wl_opt:
                            logger.info(f"✓ 田块验证成功: {sample_field_id} wl_opt={actual_wl_opt}")
                        else:
                            logger.warning(f"⚠️ 田块验证异常: {sample_field_id} 期望wl_opt={expected_wl_opt}, 实际={actual_wl_opt}")
            else:
                logger.error("❌ 最终验证失败: _rice_integration 元数据丢失")
                
        except Exception as final_write_error:
            logger.error(f"❌ 最终写入失败: {final_write_error}")
            # 不抛出异常，因为计划已经生成成功
        
        # ===== 步骤6: (可选) 自动执行 =====
        execution_id = None
        
        if request.auto_execute and plan_response.plan_id:
            logger.info("启动自动执行...")
            
            try:
                exec_request = DynamicExecutionRequest(
                    plan_file=plan_response.plan_id,
                    farm_id=request.farm_id
                )
                exec_response = await start_dynamic_execution(exec_request)
                execution_id = exec_response.execution_id
                logger.info(f"✓ 执行已启动: {execution_id}")
            except Exception as e:
                logger.error(f"执行启动失败: {e}")
        
        # ===== 返回结果 =====
        return RiceIntegrationResponse(
            success=True,
            message=f"成功！基于 Rice 智能决策生成灌溉计划（{len(custom_waterlevels)} 个田块），config.json 已更新",
            decision_count=len(rice_decisions) - 1 if 'log' in rice_decisions else len(rice_decisions),
            irrigate_count=len(custom_waterlevels),
            plan_file=plan_response.plan_id,
            execution_id=execution_id,
            details={
                "skipped_sections": skipped,
                "mapping_count": len(section_to_field),
                "converted_count": len(custom_waterlevels),
                "config_backup": backup_path,
                "rice_modifications": rice_modifications,
                "note": "config.json 已被 Rice 决策更新，原始配置已备份"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"基于 Rice 决策生成计划失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"生成失败: {str(e)}"
        )

@app.post("/api/irrigation/restore-config")
async def restore_config_from_backup(
    backup_file: str = Query(..., description="备份文件名（如 config_backup_20251120_123456.json）")
):
    """
    从备份恢复 config.json
    
    用于在使用 Rice 决策后恢复到原始配置。
    
    **使用示例**:
    ```bash
    curl -X POST "http://localhost:8000/api/irrigation/restore-config?backup_file=config_backup_20251120_123456.json"
    ```
    """
    try:
        logger.info(f"尝试从备份恢复配置: {backup_file}")
        
        # 构建备份文件路径（备份文件在 data/config_backup 目录）
        backup_dir = os.path.join(os.path.dirname(__file__), "data", "config_backup")
        backup_path = os.path.join(backup_dir, backup_file)
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        
        # 检查备份文件是否存在
        if not os.path.exists(backup_path):
            raise HTTPException(
                status_code=404,
                detail=f"备份文件不存在: {backup_file}"
            )
        
        # 备份当前的 config.json（以防万一）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        current_backup = os.path.join(
            backup_dir,
            f"config_before_restore_{timestamp}.json"
        )
        
        import shutil
        shutil.copy2(config_path, current_backup)
        logger.info(f"✓ 当前配置已备份: {current_backup}")
        
        # 恢复备份
        shutil.copy2(backup_path, config_path)
        logger.info(f"✓ 配置已从备份恢复")
        
        return {
            "success": True,
            "message": "配置已成功恢复",
            "restored_from": backup_file,
            "current_config_backup": current_backup,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复配置失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"恢复配置失败: {str(e)}"
        )

@app.get("/api/irrigation/list-backups")
async def list_config_backups():
    """
    列出所有配置备份文件
    
    **使用示例**:
    ```bash
    curl "http://localhost:8000/api/irrigation/list-backups"
    ```
    """
    try:
        # 备份文件保存在 data/config_backup 目录
        backup_dir = os.path.join(os.path.dirname(__file__), "data", "config_backup")
        
        # 如果目录不存在，返回空列表
        if not os.path.exists(backup_dir):
            return {
                "success": True,
                "total_backups": 0,
                "backups": [],
                "timestamp": datetime.now().isoformat()
            }
        
        # 查找所有备份文件
        import glob
        backup_files = glob.glob(os.path.join(backup_dir, "config_backup_*.json"))
        
        backups = []
        for backup_path in sorted(backup_files, reverse=True):  # 最新的在前
            filename = os.path.basename(backup_path)
            stat = os.stat(backup_path)
            
            backups.append({
                "filename": filename,
                "path": backup_path,
                "size_bytes": stat.st_size,
                "created_time": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        
        return {
            "success": True,
            "total_backups": len(backups),
            "backups": backups,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"列出备份文件失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"列出备份文件失败: {str(e)}"
        )

@app.post("/api/farm/switch", response_model=FarmSwitchResponse)
async def switch_farm_with_upload(
    farm_id: str = Form(..., description="农场ID"),
    farm_name: str = Form(..., description="农场名称"),
    auto_generate_plan: bool = Form(False, description="是否自动生成灌溉计划"),
    skip_backup: bool = Form(False, description="是否跳过备份（谨慎使用）"),
    files: List[UploadFile] = File(..., description="SHP文件及配套文件（.shp, .dbf, .shx等）")
):
    """
    农场一键切换API - 上传SHP文件自动完成所有配置
    
    功能：
    1. 自动检测文件类型（田块、水路、闸门）
    2. 备份当前配置
    3. 转换SHP为GeoJSON
    4. 更新所有配置文件
    5. 生成config.json
    6. 验证配置完整性
    7. 可选：自动生成灌溉计划
    
    使用示例（Postman）：
    - Method: POST
    - URL: http://localhost:8000/api/farm/switch
    - Body: form-data
        - farm_id: "新农场ID"
        - farm_name: "新农场名称"
        - auto_generate_plan: false
        - files: [选择所有SHP相关文件]
    """
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = None
    
    try:
        logger.info(f"========== 开始农场切换流程 ==========")
        logger.info(f"农场ID: {farm_id}, 农场名称: {farm_name}")
        logger.info(f"上传文件数量: {len(files)}")
        
        # ========== 步骤1: 验证文件 ==========
        if not files or len(files) == 0:
            raise HTTPException(status_code=400, detail="未上传任何文件")
        
        # 检查文件扩展名
        uploaded_files = {}
        for file in files:
            if file.filename:
                ext = os.path.splitext(file.filename)[1].lower()
                base_name = os.path.splitext(file.filename)[0]
                
                if base_name not in uploaded_files:
                    uploaded_files[base_name] = []
                uploaded_files[base_name].append(ext)
                
                logger.info(f"  上传文件: {file.filename}")
        
        # 验证每组文件都有必需的扩展名
        required_exts = {'.shp', '.dbf', '.shx'}
        shp_groups = {}
        
        for base_name, exts in uploaded_files.items():
            ext_set = set(exts)
            if '.shp' in ext_set:  # 这是一个SHP文件组
                if not required_exts.issubset(ext_set):
                    raise HTTPException(
                        status_code=400,
                        detail=f"SHP文件组 {base_name} 缺少必需文件（需要.shp, .dbf, .shx）"
                    )
                shp_groups[base_name] = exts
        
        if len(shp_groups) < 3:
            raise HTTPException(
                status_code=400,
                detail=f"需要至少3组SHP文件（田块、水路、闸门），当前只有 {len(shp_groups)} 组"
            )
        
        logger.info(f"找到 {len(shp_groups)} 组SHP文件")
        
        # ========== 步骤2: 自动检测文件类型 ==========
        detected_files = {'fields': None, 'segments': None, 'gates': None}
        
        for base_name in shp_groups.keys():
            file_type = detect_shp_file_type(base_name)
            if file_type and not detected_files[file_type]:
                detected_files[file_type] = base_name
                logger.info(f"检测到 {file_type}: {base_name}")
        
        # 验证是否检测到所有类型
        missing_types = [k for k, v in detected_files.items() if v is None]
        if missing_types:
            raise HTTPException(
                status_code=400,
                detail=f"无法自动识别文件类型: {', '.join(missing_types)}。请确保文件名包含关键词（田块/field, 水路/canal, 阀门/gate）"
            )
        
        # ========== 步骤3: 备份当前配置 ==========
        if not skip_backup:
            logger.info("备份当前配置...")
            backup_base = os.path.join(os.path.dirname(__file__), "data", "farm_backups")
            os.makedirs(backup_base, exist_ok=True)
            backup_path = os.path.join(backup_base, f"backup_{timestamp}")
            os.makedirs(backup_path, exist_ok=True)
            
            # 备份config.json
            config_file = os.path.join(os.path.dirname(__file__), "config.json")
            if os.path.exists(config_file):
                shutil.copy2(config_file, os.path.join(backup_path, "config.json"))
            
            # 备份GeoJSON文件
            if os.path.exists(GZP_FARM_DIR):
                for filename in os.listdir(GZP_FARM_DIR):
                    if filename.endswith('_code.geojson'):
                        src = os.path.join(GZP_FARM_DIR, filename)
                        dst = os.path.join(backup_path, filename)
                        shutil.copy2(src, dst)
            
            logger.info(f"备份完成: {backup_path}")
        
        # ========== 步骤4: 保存上传的SHP文件 ==========
        logger.info("保存上传的SHP文件...")
        os.makedirs(GZP_FARM_DIR, exist_ok=True)
        
        saved_shp_files = {}
        
        for file in files:
            if file.filename:
                # 保存到gzp_farm目录
                file_path = os.path.join(GZP_FARM_DIR, file.filename)
                content = await file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                await file.seek(0)
                
                # 记录主SHP文件
                if file.filename.endswith('.shp'):
                    base_name = os.path.splitext(file.filename)[0]
                    for file_type, detected_base in detected_files.items():
                        if detected_base == base_name:
                            saved_shp_files[file_type] = file.filename
        
        logger.info(f"SHP文件保存完成: {saved_shp_files}")
        
        # ========== 步骤5: 转换为GeoJSON ==========
        logger.info("转换SHP为GeoJSON...")
        geojson_files = {}
        
        # 文件类型到英文名称的映射
        type_to_english = {
            'fields': 'fields',
            'segments': 'segments',  
            'gates': 'gates'
        }
        
        for file_type, shp_filename in saved_shp_files.items():
            shp_path = os.path.join(GZP_FARM_DIR, shp_filename)
            # 使用安全的英文文件名，避免中文编码问题
            geojson_filename = f"{farm_id}_{type_to_english[file_type]}_code.geojson"
            geojson_path = os.path.join(GZP_FARM_DIR, geojson_filename)
            
            if not convert_shp_to_geojson(shp_path, geojson_path):
                raise HTTPException(
                    status_code=500,
                    detail=f"转换失败: {shp_filename} → {geojson_filename}"
                )
            
            geojson_files[file_type] = geojson_filename
            logger.info(f"  转换成功: {shp_filename} → {geojson_filename}")
        
        # ========== 步骤6: 更新配置文件 ==========
        logger.info("更新配置文件...")
        
        # 更新auto_config_params.yaml
        if not update_yaml_config(farm_id, farm_name, geojson_files):
            raise HTTPException(status_code=500, detail="更新YAML配置失败")
        
        # 更新farm_id_mapping.json
        if not update_farm_id_mapping(farm_id, farm_name):
            raise HTTPException(status_code=500, detail="更新农场映射失败")
        
        # 保存文件名映射（用于追溯原始中文文件名）
        file_mapping = {
            'farm_id': farm_id,
            'farm_name': farm_name,
            'original_files': saved_shp_files,  # 原始上传的文件名（可能是中文）
            'generated_files': geojson_files,    # 生成的英文文件名
            'timestamp': timestamp
        }
        mapping_file = os.path.join(GZP_FARM_DIR, f"{farm_id}_file_mapping.json")
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(file_mapping, f, ensure_ascii=False, indent=2)
        logger.info(f"文件映射已保存: {mapping_file}")
        
        logger.info("配置文件更新完成")
        
        # ========== 步骤7: 生成config.json ==========
        logger.info("生成config.json...")
        if not generate_config_from_geojson():
            raise HTTPException(status_code=500, detail="生成config.json失败")
        
        # ========== 步骤8: 验证配置 ==========
        logger.info("验证配置...")
        validation = validate_generated_config(farm_id)
        
        if not validation.get("valid"):
            raise HTTPException(
                status_code=500,
                detail=f"配置验证失败: {validation.get('error')}"
            )
        
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        
        logger.info("========== 农场切换成功 ==========")
        
        # ========== 可选：自动生成灌溉计划 ==========
        plan_file = None
        if auto_generate_plan:
            logger.info("自动生成灌溉计划...")
            try:
                # 调用灌溉计划生成
                plan_request = IrrigationPlanRequest(
                    farm_id=farm_id,
                    config_path=config_path,
                    scenario_name=f"{farm_name}_initial"
                )
                plan_response = await generate_irrigation_plan(plan_request)
                logger.info(f"灌溉计划生成完成: {plan_response.message}")
            except Exception as e:
                logger.warning(f"自动生成计划失败: {e}")
        
        # 返回响应
        response_message = f"农场切换成功！已切换到 {farm_name}"
        if any(ord(c) > 127 for name in saved_shp_files.values() for c in name):
            response_message += "\n💡 提示：已将中文文件名转换为英文格式以确保跨平台兼容性"
        
        return FarmSwitchResponse(
            success=True,
            message=response_message,
            farm_id=farm_id,
            farm_name=farm_name,
            backup_path=backup_path,
            files_processed=saved_shp_files,  # 显示原始上传的文件名
            config_path=config_path,
            validation=validation,
            timestamp=timestamp
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"农场切换失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"农场切换失败: {str(e)}")

@app.get("/api/irrigation/rice-status")
async def check_rice_service_status(
    rice_api_url: str = "http://rice-backend:5000/v1/rice_irrigation"  # Docker 容器名访问
):
    """
    检查 Rice 服务状态
    
    用于验证 rice_smart_irrigation 服务是否可用
    
    **使用示例**:
    ```bash
    curl "http://localhost:8000/api/irrigation/rice-status"
    ```
    """
    try:
        import requests
        
        response = requests.get(
            rice_api_url,
            params={'farm_id': '13944136728576'},  # 测试用
            timeout=30
        )
        
        return {
            "success": response.status_code == 200,
            "status_code": response.status_code,
            "message": "Rice 服务正常" if response.status_code == 200 else "Rice 服务异常",
            "rice_api_url": rice_api_url,
            "timestamp": datetime.now().isoformat()
        }
    
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "message": "无法连接到 Rice 服务，请确保服务正在运行",
            "rice_api_url": rice_api_url,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"检查失败: {str(e)}",
            "rice_api_url": rice_api_url,
            "timestamp": datetime.now().isoformat()
        }

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
            "灌溉计划智能优化",
            "Rice智能决策集成（解耦架构）"
        ],
        "endpoints": {
            "system": "/api/system/*",
            "execution": "/api/execution/*",
            "water_levels": "/api/water-levels/*",
            "regeneration": "/api/regeneration/*",
            "batches": "/api/batches/*",
            "irrigation": "/api/irrigation/*",
            "data": "/api/data/*",
            "rice_integration": {
                "update_config": "/api/irrigation/update-config-from-rice",
                "generate": "/api/irrigation/generate-from-rice",
                "status": "/api/irrigation/rice-status",
                "restore": "/api/irrigation/restore-config",
                "list_backups": "/api/irrigation/list-backups"
            }
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