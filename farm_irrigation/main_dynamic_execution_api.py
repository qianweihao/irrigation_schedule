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
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

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
    get_water_level_summary, get_field_trend_analysis
)

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

# 系统启动时间
_system_start_time = datetime.now()

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
        await _scheduler.stop_execution()
    
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
            database_path=request.database_path,
            log_path="execution_logs"
        )
        logger.info("执行状态管理器初始化完成")
        
        # 初始化水位管理器
        _waterlevel_manager = DynamicWaterLevelManager(
            config_path=request.config_path,
            cache_file_path=request.cache_file_path
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

# ==================== 计划重新生成API ====================

@app.post("/api/regeneration/manual", response_model=ManualRegenerationResponse)
async def manual_regeneration(request: ManualRegenerationRequest):
    """手动重新生成批次"""
    return await manual_regenerate_batch(request)

@app.get("/api/regeneration/summary/{farm_id}")
async def regeneration_summary(farm_id: str):
    """获取重新生成摘要"""
    try:
        global _plan_regenerator
        if not _plan_regenerator:
            raise HTTPException(status_code=500, detail="计划重新生成器未初始化")
        
        summary = _plan_regenerator.get_regeneration_summary()
        summary["farm_id"] = farm_id
        summary["query_time"] = datetime.now().isoformat()
        
        return summary
        
    except Exception as e:
        logger.error(f"获取重新生成摘要失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取重新生成摘要失败: {str(e)}")

# ==================== 批次管理API ====================

@app.get("/api/batches/{batch_index}/details")
async def get_batch_details(batch_index: int):
    """获取批次详细信息"""
    try:
        global _scheduler
        if not _scheduler:
            raise HTTPException(status_code=500, detail="调度器未初始化")
        
        details = await _scheduler.get_batch_details(batch_index)
        
        if not details:
            raise HTTPException(status_code=404, detail=f"批次 {batch_index} 不存在")
        
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
            "田块水位趋势分析"
        ],
        "endpoints": {
            "system": "/api/system/*",
            "execution": "/api/execution/*",
            "water_levels": "/api/water-levels/*",
            "regeneration": "/api/regeneration/*",
            "batches": "/api/batches/*",
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