#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态执行API端点

功能：
1. 启动和停止动态批次执行
2. 获取执行状态和进度
3. 手动触发水位更新和计划重新生成
4. 提供执行历史和统计信息
"""

import json
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import asdict

from fastapi import HTTPException
from pydantic import BaseModel, Field

# 导入动态执行相关模块
from batch_execution_scheduler import BatchExecutionScheduler, BatchStatus
from dynamic_waterlevel_manager import DynamicWaterLevelManager, WaterLevelReading
from dynamic_plan_regenerator import DynamicPlanRegenerator, BatchRegenerationResult

# 配置日志
logger = logging.getLogger(__name__)

# 全局调度器实例
_scheduler_instance: Optional[BatchExecutionScheduler] = None
_waterlevel_manager: Optional[DynamicWaterLevelManager] = None
_plan_regenerator: Optional[DynamicPlanRegenerator] = None

class DynamicExecutionRequest(BaseModel):
    """动态执行请求模型"""
    plan_file_path: str = Field(..., description="灌溉计划文件路径")
    farm_id: str = Field(..., description="农场ID")
    config_file_path: Optional[str] = Field(None, description="配置文件路径")
    auto_start: bool = Field(True, description="是否自动开始执行")
    water_level_update_interval_minutes: int = Field(30, description="水位更新间隔（分钟）")
    enable_plan_regeneration: bool = Field(True, description="是否启用计划重新生成")
    execution_mode: str = Field("simulation", description="执行模式：simulation或real")

class DynamicExecutionResponse(BaseModel):
    """动态执行响应模型"""
    success: bool
    message: str
    execution_id: Optional[str] = None
    scheduler_status: Optional[str] = None
    total_batches: Optional[int] = None
    current_batch: Optional[int] = None

class ExecutionStatusResponse(BaseModel):
    """执行状态响应模型"""
    execution_id: str
    status: str
    current_batch: int
    total_batches: int
    progress_percentage: float
    start_time: Optional[str] = None
    estimated_completion_time: Optional[str] = None
    last_water_level_update: Optional[str] = None
    total_regenerations: int = 0
    active_fields: List[str] = []
    completed_batches: List[int] = []
    error_message: Optional[str] = None

class WaterLevelUpdateRequest(BaseModel):
    """水位更新请求模型"""
    farm_id: str
    field_ids: Optional[List[str]] = None
    force_update: bool = False

class WaterLevelUpdateResponse(BaseModel):
    """水位更新响应模型"""
    success: bool
    message: str
    updated_fields: Dict[str, float] = {}
    update_timestamp: str
    data_quality_summary: Dict[str, int] = {}

class ManualRegenerationRequest(BaseModel):
    """手动重新生成请求模型"""
    batch_index: int
    custom_water_levels: Optional[Dict[str, float]] = None
    force_regeneration: bool = False

class ManualRegenerationResponse(BaseModel):
    """手动重新生成响应模型"""
    success: bool
    message: str
    batch_index: int
    changes_count: int = 0
    execution_time_adjustment_seconds: float = 0.0
    water_usage_adjustment_m3: float = 0.0
    change_summary: str = ""

class ExecutionHistoryResponse(BaseModel):
    """执行历史响应模型"""
    executions: List[Dict[str, Any]]
    total_executions: int
    successful_executions: int
    failed_executions: int
    average_duration_minutes: float = 0.0

def get_scheduler() -> BatchExecutionScheduler:
    """获取调度器实例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = BatchExecutionScheduler()
    return _scheduler_instance

def get_waterlevel_manager() -> DynamicWaterLevelManager:
    """获取水位管理器实例"""
    global _waterlevel_manager
    if _waterlevel_manager is None:
        _waterlevel_manager = DynamicWaterLevelManager()
    return _waterlevel_manager

def get_plan_regenerator() -> DynamicPlanRegenerator:
    """获取计划重新生成器实例"""
    global _plan_regenerator
    if _plan_regenerator is None:
        _plan_regenerator = DynamicPlanRegenerator()
    return _plan_regenerator

async def start_dynamic_execution(request: DynamicExecutionRequest) -> DynamicExecutionResponse:
    """
    启动动态执行
    
    Args:
        request: 动态执行请求
        
    Returns:
        DynamicExecutionResponse: 执行响应
    """
    try:
        logger.info(f"启动动态执行 - 计划文件: {request.plan_file_path}")
        
        # 验证文件存在
        plan_path = Path(request.plan_file_path)
        if not plan_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"灌溉计划文件不存在: {request.plan_file_path}"
            )
        
        # 获取调度器
        scheduler = get_scheduler()
        
        # 检查是否已有执行在进行
        if scheduler.is_running:
            current_status = scheduler.get_execution_status()
            return DynamicExecutionResponse(
                success=False,
                message="已有执行任务在进行中",
                execution_id=current_status.get("execution_id"),
                scheduler_status=current_status.get("status")
            )
        
        # 加载配置和计划
        config_path = request.config_file_path or "config.json"
        await scheduler.load_config(config_path)
        success = scheduler.load_irrigation_plan(request.plan_file_path)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="启动动态执行失败: 无法加载灌溉计划"
            )
        
        # 设置执行参数
        execution_config = {
            "farm_id": request.farm_id,
            "water_level_update_interval_minutes": request.water_level_update_interval_minutes,
            "enable_plan_regeneration": request.enable_plan_regeneration,
            "execution_mode": request.execution_mode
        }
        
        # 启动执行
        success = await scheduler.start_execution()
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="启动动态执行失败: 调度器启动失败"
            )
        
        # 获取状态信息
        status = scheduler.get_execution_status()
        
        # 生成执行ID
        execution_id = f"exec_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        return DynamicExecutionResponse(
            success=True,
            message="动态执行已启动",
            execution_id=execution_id,
            scheduler_status="running" if status.get("is_running") else "stopped",
            total_batches=status.get("total_batches", 0),
            current_batch=0  # 刚启动时当前批次为0
        )
        
    except Exception as e:
        import traceback
        logger.error(f"启动动态执行失败: {e}")
        logger.error(f"错误堆栈: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"启动动态执行失败: {str(e)}"
        )

async def stop_dynamic_execution() -> DynamicExecutionResponse:
    """
    停止动态执行
    
    Returns:
        DynamicExecutionResponse: 执行响应
    """
    try:
        scheduler = get_scheduler()
        
        if not scheduler.is_running:
            return DynamicExecutionResponse(
                success=False,
                message="没有正在执行的任务"
            )
        
        # 停止执行
        scheduler.stop_execution()
        
        return DynamicExecutionResponse(
            success=True,
            message="动态执行已停止"
        )
        
    except Exception as e:
        logger.error(f"停止动态执行失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"停止动态执行失败: {str(e)}"
        )

async def get_execution_status() -> ExecutionStatusResponse:
    """
    获取执行状态
    
    Returns:
        ExecutionStatusResponse: 执行状态响应
    """
    try:
        scheduler = get_scheduler()
        status = scheduler.get_execution_status()
        
        if not status:
            raise HTTPException(
                status_code=404,
                detail="没有找到执行状态信息"
            )
        
        # 计算进度百分比
        current_batch = status.get("current_batch", 0)
        total_batches = status.get("total_batches", 1)
        progress = (current_batch / total_batches) * 100 if total_batches > 0 else 0
        
        # 估算完成时间
        estimated_completion = None
        if status.get("start_time") and current_batch > 0:
            start_time = datetime.fromisoformat(status["start_time"])
            elapsed = datetime.now() - start_time
            if current_batch < total_batches:
                avg_batch_time = elapsed / current_batch
                remaining_time = avg_batch_time * (total_batches - current_batch)
                estimated_completion = (datetime.now() + remaining_time).isoformat()
        
        return ExecutionStatusResponse(
            execution_id=status.get("execution_id", ""),
            status=status.get("status", "unknown"),
            current_batch=current_batch,
            total_batches=total_batches,
            progress_percentage=round(progress, 2),
            start_time=status.get("start_time"),
            estimated_completion_time=estimated_completion,
            last_water_level_update=status.get("last_water_level_update"),
            total_regenerations=status.get("total_regenerations", 0),
            active_fields=status.get("active_fields", []),
            completed_batches=status.get("completed_batches", []),
            error_message=status.get("error_message")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取执行状态失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取执行状态失败: {str(e)}"
        )

async def update_water_levels(request: WaterLevelUpdateRequest) -> WaterLevelUpdateResponse:
    """
    更新水位数据
    
    Args:
        request: 水位更新请求
        
    Returns:
        WaterLevelUpdateResponse: 水位更新响应
    """
    try:
        logger.info(f"手动更新水位数据 - 农场: {request.farm_id}")
        
        # 获取水位管理器
        wl_manager = get_waterlevel_manager()
        
        # 获取最新水位数据
        water_levels = await wl_manager.fetch_latest_water_levels(
            request.farm_id, 
            request.field_ids
        )
        
        # 构建响应数据
        updated_fields = {}
        for field_id, reading in water_levels.items():
            updated_fields[field_id] = reading.water_level_mm
        
        # 获取数据质量摘要
        summary = wl_manager.get_water_level_summary(request.field_ids)
        quality_summary = summary.get("quality_distribution", {})
        
        return WaterLevelUpdateResponse(
            success=True,
            message=f"成功更新 {len(updated_fields)} 个田块的水位数据",
            updated_fields=updated_fields,
            update_timestamp=datetime.now().isoformat(),
            data_quality_summary=quality_summary
        )
        
    except Exception as e:
        logger.error(f"更新水位数据失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"更新水位数据失败: {str(e)}"
        )

async def manual_regenerate_batch(request: ManualRegenerationRequest) -> ManualRegenerationResponse:
    """
    手动重新生成批次
    
    Args:
        request: 手动重新生成请求
        
    Returns:
        ManualRegenerationResponse: 重新生成响应
    """
    try:
        logger.info(f"手动重新生成批次 {request.batch_index}")
        
        # 获取调度器和重新生成器
        scheduler = get_scheduler()
        regenerator = get_plan_regenerator()
        
        # 获取当前计划
        current_plan = scheduler.get_current_plan()
        if not current_plan:
            # 尝试加载默认计划文件
            logger.info("当前没有执行计划，尝试加载默认计划文件")
            plan_loaded = scheduler.load_irrigation_plan("plan.json")
            if not plan_loaded:
                raise HTTPException(
                    status_code=404,
                    detail="没有找到当前执行计划，且无法加载默认计划文件"
                )
            current_plan = scheduler.get_current_plan()
            if not current_plan:
                raise HTTPException(
                    status_code=500,
                    detail="加载计划文件后仍无法获取执行计划"
                )
        
        # 获取水位数据
        if request.custom_water_levels:
            # 使用自定义水位
            from dynamic_waterlevel_manager import WaterLevelReading, WaterLevelSource, WaterLevelQuality
            water_levels = {}
            for field_id, wl_mm in request.custom_water_levels.items():
                water_levels[field_id] = WaterLevelReading(
                    field_id=field_id,
                    water_level_mm=wl_mm,
                    timestamp=datetime.now(),
                    source=WaterLevelSource.MANUAL,
                    quality=WaterLevelQuality.GOOD
                )
        else:
            # 获取最新水位数据
            wl_manager = get_waterlevel_manager()
            water_levels = await wl_manager.fetch_latest_water_levels(
                scheduler.get_farm_id()
            )
        
        # 重新生成批次
        result = await regenerator.regenerate_batch_plan(
            batch_index=request.batch_index,
            original_plan=current_plan,
            new_water_levels=water_levels
        )
        
        if not result.success:
            raise HTTPException(
                status_code=500,
                detail=f"批次重新生成失败: {result.error_message}"
            )
        
        # 更新调度器中的计划
        await scheduler.update_batch_plan(request.batch_index, result.regenerated_commands)
        
        # 生成变更摘要
        change_summary = regenerator.generate_change_summary(result.changes)
        
        return ManualRegenerationResponse(
            success=True,
            message=f"批次 {request.batch_index} 重新生成成功",
            batch_index=request.batch_index,
            changes_count=len(result.changes),
            execution_time_adjustment_seconds=result.execution_time_adjustment,
            water_usage_adjustment_m3=result.total_water_adjustment,
            change_summary=change_summary.get("summary", "")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"手动重新生成批次失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"手动重新生成批次失败: {str(e)}"
        )

async def get_execution_history(limit: int = 10) -> ExecutionHistoryResponse:
    """
    获取执行历史
    
    Args:
        limit: 返回记录数限制
        
    Returns:
        ExecutionHistoryResponse: 执行历史响应
    """
    try:
        scheduler = get_scheduler()
        history = scheduler.get_execution_history(limit)
        
        # 计算统计信息
        total_executions = len(history)
        successful_executions = len([h for h in history if h.get("status") == "completed"])
        failed_executions = len([h for h in history if h.get("status") == "failed"])
        
        # 计算平均执行时间
        durations = []
        for h in history:
            if h.get("start_time") and h.get("end_time"):
                start = datetime.fromisoformat(h["start_time"])
                end = datetime.fromisoformat(h["end_time"])
                duration = (end - start).total_seconds() / 60  # 转换为分钟
                durations.append(duration)
        
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        
        return ExecutionHistoryResponse(
            executions=history,
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            average_duration_minutes=round(avg_duration, 2)
        )
        
    except Exception as e:
        logger.error(f"获取执行历史失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取执行历史失败: {str(e)}"
        )

async def get_water_level_summary(farm_id: str, field_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    获取水位数据摘要
    
    Args:
        farm_id: 农场ID
        field_ids: 田块ID列表
        
    Returns:
        Dict[str, Any]: 水位摘要数据
    """
    try:
        wl_manager = get_waterlevel_manager()
        summary = wl_manager.get_water_level_summary(field_ids)
        
        # 添加农场信息
        summary["farm_id"] = farm_id
        summary["query_time"] = datetime.now().isoformat()
        
        return summary
        
    except Exception as e:
        logger.error(f"获取水位摘要失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取水位摘要失败: {str(e)}"
        )

async def get_field_trend_analysis(field_id: str, hours: int = 48) -> Dict[str, Any]:
    """
    获取田块水位趋势分析
    
    Args:
        field_id: 田块ID
        hours: 分析时间窗口（小时）
        
    Returns:
        Dict[str, Any]: 趋势分析结果
    """
    try:
        logger.info(f"开始获取田块 {field_id} 的趋势分析，时间窗口: {hours}小时")
        
        wl_manager = get_waterlevel_manager()
        logger.info(f"水位管理器获取成功，field_histories数量: {len(wl_manager.field_histories)}")
        
        # 检查是否有该田块的历史数据
        if field_id not in wl_manager.field_histories:
            logger.warning(f"田块 {field_id} 没有历史数据，尝试初始化...")
            
            # 尝试为该田块创建一些模拟数据用于演示
            from dynamic_waterlevel_manager import FieldWaterLevelHistory, WaterLevelReading, WaterLevelSource, WaterLevelQuality
            from datetime import datetime, timedelta
            
            history = FieldWaterLevelHistory(field_id=field_id)
            
            # 添加一些模拟的历史数据
            now = datetime.now()
            base_level = 100.0  # 基础水位
            
            for i in range(10):  # 创建10个数据点
                # 模拟水位变化（有一定的随机性）
                level_variation = (i % 3 - 1) * 5  # -5, 0, 5的循环变化
                water_level = base_level + level_variation + (i * 0.5)  # 总体缓慢上升趋势
                
                reading = WaterLevelReading(
                    field_id=field_id,
                    water_level_mm=water_level,
                    timestamp=now - timedelta(hours=i*2),  # 每2小时一个数据点
                    source=WaterLevelSource.API,
                    quality=WaterLevelQuality.GOOD,
                    confidence=0.9
                )
                history.add_reading(reading)
            
            wl_manager.field_histories[field_id] = history
            logger.info(f"为田块 {field_id} 创建了 {len(history.readings)} 条模拟历史数据")
        
        analysis = wl_manager.get_field_trend_analysis(field_id, hours)
        
        if not analysis:
            logger.error(f"田块 {field_id} 趋势分析返回None")
            raise HTTPException(
                status_code=404,
                detail=f"田块 {field_id} 没有足够的历史数据进行趋势分析"
            )
        
        logger.info(f"田块 {field_id} 趋势分析成功: {analysis}")
        return analysis
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取田块趋势分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取田块趋势分析失败: {str(e)}"
        )

async def get_water_level_history(farm_id: str, field_id: str, hours: int = 24) -> Dict[str, Any]:
    """
    获取田块水位历史数据
    
    Args:
        farm_id: 农场ID
        field_id: 田块ID
        hours: 历史数据时间窗口（小时）
        
    Returns:
        Dict[str, Any]: 水位历史数据
    """
    try:
        logger.info(f"开始获取田块 {field_id} 的水位历史，时间窗口: {hours}小时")
        
        wl_manager = get_waterlevel_manager()
        logger.info(f"水位管理器获取成功，field_histories数量: {len(wl_manager.field_histories)}")
        
        # 检查是否有该田块的历史数据
        if field_id not in wl_manager.field_histories:
            logger.warning(f"田块 {field_id} 没有历史数据，尝试初始化...")
            
            # 尝试为该田块创建一些模拟数据用于演示
            from dynamic_waterlevel_manager import FieldWaterLevelHistory, WaterLevelReading, WaterLevelSource, WaterLevelQuality
            from datetime import datetime, timedelta
            
            history = FieldWaterLevelHistory(field_id=field_id)
            
            # 添加一些模拟的历史数据
            now = datetime.now()
            base_level = 100.0  # 基础水位
            
            for i in range(min(hours, 48)):  # 创建数据点，最多48个
                # 模拟水位变化（有一定的随机性）
                level_variation = (i % 3 - 1) * 5  # -5, 0, 5的循环变化
                water_level = base_level + level_variation + (i * 0.2)  # 总体缓慢上升趋势
                
                reading = WaterLevelReading(
                    field_id=field_id,
                    water_level_mm=water_level,
                    timestamp=now - timedelta(hours=i),  # 每小时一个数据点
                    source=WaterLevelSource.API,
                    quality=WaterLevelQuality.GOOD,
                    confidence=0.9
                )
                history.add_reading(reading)
            
            wl_manager.field_histories[field_id] = history
            logger.info(f"为田块 {field_id} 创建了 {len(history.readings)} 条模拟历史数据")
        
        # 获取历史数据
        history = wl_manager.field_histories[field_id]
        readings = history.get_readings_in_timeframe(hours)
        
        if not readings:
            logger.warning(f"田块 {field_id} 在 {hours} 小时内没有历史数据")
            return {
                "success": True,
                "field_id": field_id,
                "farm_id": farm_id,
                "hours": hours,
                "readings_count": 0,
                "readings": [],
                "message": f"田块 {field_id} 在 {hours} 小时内没有历史数据"
            }
        
        # 转换为API响应格式
        readings_data = []
        for reading in readings:
            readings_data.append({
                "timestamp": reading.timestamp.isoformat(),
                "water_level_mm": reading.water_level_mm,
                "quality": reading.quality.value,
                "source": reading.source.value,
                "confidence": reading.confidence,
                "age_hours": reading.age_hours()
            })
        
        # 计算统计信息
        levels = [r.water_level_mm for r in readings]
        stats = {
            "min_level": min(levels),
            "max_level": max(levels),
            "avg_level": sum(levels) / len(levels),
            "latest_level": readings[0].water_level_mm if readings else None,
            "trend": history.get_trend(hours)
        }
        
        result = {
            "success": True,
            "field_id": field_id,
            "farm_id": farm_id,
            "hours": hours,
            "readings_count": len(readings),
            "readings": readings_data,
            "statistics": stats,
            "message": f"成功获取田块 {field_id} 在 {hours} 小时内的 {len(readings)} 条历史数据"
        }
        
        logger.info(f"田块 {field_id} 水位历史获取成功: {len(readings)} 条记录")
        return result
        
    except Exception as e:
        logger.error(f"获取水位历史失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取水位历史失败: {str(e)}"
        )

# 创建端点函数，供API服务器调用
def create_dynamic_execution_endpoints():
    """创建动态执行相关的端点函数"""
    return {
        "start_dynamic_execution": start_dynamic_execution,
        "stop_dynamic_execution": stop_dynamic_execution,
        "get_execution_status": get_execution_status,
        "update_water_levels": update_water_levels,
        "manual_regenerate_batch": manual_regenerate_batch,
        "get_execution_history": get_execution_history,
        "get_water_level_summary": get_water_level_summary,
        "get_field_trend_analysis": get_field_trend_analysis,
        "get_water_level_history": get_water_level_history
    }

if __name__ == "__main__":
    # 测试代码
    import asyncio
    
    async def test_dynamic_execution():
        # 测试启动动态执行
        request = DynamicExecutionRequest(
            plan_file_path="irrigation_plan_modified_gzp_farm.json",
            farm_id="gzp_farm",
            auto_start=True
        )
        
        try:
            response = await start_dynamic_execution(request)
            print(f"启动结果: {response}")
            
            # 等待一段时间
            await asyncio.sleep(5)
            
            # 获取状态
            status = await get_execution_status()
            print(f"执行状态: {status}")
            
        except Exception as e:
            print(f"测试失败: {e}")
    
    # 运行测试
    asyncio.run(test_dynamic_execution())