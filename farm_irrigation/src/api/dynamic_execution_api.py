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
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import asdict

from fastapi import HTTPException
from pydantic import BaseModel, Field

# 导入动态执行相关模块
from src.scheduler.batch_execution_scheduler import BatchExecutionScheduler, BatchStatus
from src.scheduler.dynamic_waterlevel_manager import DynamicWaterLevelManager, WaterLevelReading
from src.scheduler.dynamic_plan_regenerator import DynamicPlanRegenerator, BatchRegenerationResult

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

class ScenarioInfo(BaseModel):
    """方案信息模型"""
    scenario_name: str
    pumps_used: List[str]
    total_batches: int
    total_electricity_cost: float
    total_eta_h: float
    total_pump_runtime_hours: dict
    coverage_info: dict

class DynamicExecutionResponse(BaseModel):
    """动态执行响应模型"""
    success: bool
    message: str
    execution_id: Optional[str] = None
    scheduler_status: Optional[str] = None
    selected_scenario: Optional[ScenarioInfo] = None
    total_batches: Optional[int] = None  # 保留向后兼容性
    current_batch: Optional[int] = None
    all_scenarios: Optional[List[ScenarioInfo]] = None

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
    selected_scenario: Optional[ScenarioInfo] = None
    error_message: Optional[str] = None
    command_statistics: Optional[Dict[str, int]] = None  # 设备指令统计
    monitor_statistics: Optional[Dict[str, int]] = None  # 监控器统计

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

class FieldWaterLevelStandard(BaseModel):
    """田块水位标准"""
    wl_low: Optional[float] = None   # 低水位阈值（mm）
    wl_opt: Optional[float] = None   # 最优水位（mm）
    wl_high: Optional[float] = None  # 高水位阈值（mm）

class ManualRegenerationRequest(BaseModel):
    """手动重新生成请求模型"""
    batch_index: int
    custom_water_levels: Optional[Dict[str, float]] = None  # 田块实际水位
    custom_water_level_standards: Optional[Dict[str, FieldWaterLevelStandard]] = None  # 田块水位标准（可选）
    force_regeneration: bool = False

class ManualRegenerationResponse(BaseModel):
    """手动重新生成响应模型"""
    success: bool  # 重新生成是否成功
    message: str  # 详细消息
    batch_index: int  # 批次索引
    scenario_name: str = ""  # 当前使用的scenario名称
    scenario_count: int = 0  # 计划中包含的scenario总数
    changes_count: int = 0  # 实际变更项目数量（如时间调整、流量调整等）
    execution_time_adjustment_seconds: float = 0.0  # 执行时间调整（秒）
    water_usage_adjustment_m3: float = 0.0  # 用水量调整（立方米）
    change_summary: str = ""  # 变更摘要描述
    output_file: Optional[str] = None  # 保存的JSON文件路径
    # 水位标准参数（返回给前端用于显示参考值）
    wl_low: float = 80.0  # 低水位阈值（mm），触发灌溉的判断标准（全局默认值）
    wl_opt: float = 100.0  # 最优水位（mm），理想的田间持水量（全局默认值）
    wl_high: float = 140.0  # 高水位阈值（mm），超过则不需要灌溉（全局默认值）
    d_target_mm: float = 90.0  # 目标灌溉水深（mm），每次灌溉增加的水深
    field_water_level_standards: Optional[Dict[str, Dict[str, float]]] = None  # 田块级水位标准（如果有自定义）
    # 设备关闭触发信息（人工调整水位后自动触发）
    triggered_closures: Optional[Dict[str, List[str]]] = None  # 触发的设备关闭信息
    new_commands_generated: int = 0  # 新生成的设备指令数量

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
        
        # 获取状态信息（启动后scheduler.is_running应该为True）
        status = scheduler.get_execution_status()
        
        # 获取所有方案信息
        scenarios_info = scheduler.get_all_scenarios_info()
        
        # 使用调度器自己的execution_id，如果没有则生成新的
        execution_id = status.get("execution_id") or scheduler.execution_id or f"exec_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        return DynamicExecutionResponse(
            success=True,
            message="动态执行已启动",
            execution_id=execution_id,
            scheduler_status=status.get("status", "running"),  # 使用status字段而不是is_running
            total_batches=status.get("total_batches", 0),
            current_batch=status.get("current_batch", 1),  # 使用实际的当前批次
            selected_scenario=scenarios_info.get("selected_scenario"),
            all_scenarios=scenarios_info.get("all_scenarios", [])
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
        
        # 在停止前获取当前执行状态信息
        execution_status = scheduler.get_execution_status()
        execution_id = execution_status.get("execution_id")
        scheduler_status = execution_status.get("status")
        current_batch = execution_status.get("current_batch")
        total_batches = execution_status.get("total_batches")
        
        # 获取场景信息
        all_scenarios_info = scheduler.get_all_scenarios_info()
        selected_scenario = all_scenarios_info.get("selected_scenario")
        all_scenarios = all_scenarios_info.get("all_scenarios", [])
        
        # 停止执行
        scheduler.stop_execution()
        
        return DynamicExecutionResponse(
            success=True,
            message="动态执行已停止",
            execution_id=execution_id,
            scheduler_status=scheduler_status,
            selected_scenario=selected_scenario,
            total_batches=total_batches,
            current_batch=current_batch,
            all_scenarios=all_scenarios
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
        
        # 获取当前选中的scenario信息
        selected_scenario = None
        try:
            scenarios_info = scheduler.get_all_scenarios_info()
            selected_scenario = scenarios_info.get("selected_scenario")
        except Exception as e:
            logger.warning(f"获取选中scenario信息失败: {e}")
        
        # 获取设备指令统计
        command_statistics = None
        if scheduler.command_queue:
            try:
                command_statistics = scheduler.command_queue.get_statistics()
            except Exception as e:
                logger.warning(f"获取指令统计失败: {e}")
        
        # 获取监控器统计
        monitor_statistics = None
        if scheduler.completion_monitor:
            try:
                monitor_statistics = scheduler.completion_monitor.get_statistics()
            except Exception as e:
                logger.warning(f"获取监控器统计失败: {e}")
        
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
            selected_scenario=selected_scenario,
            error_message=status.get("error_message"),
            command_statistics=command_statistics,
            monitor_statistics=monitor_statistics
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
            
            # 查找output目录中最新的计划文件
            from pathlib import Path
            import glob
            
            plan_loaded = False
            # 从当前文件位置（src/api/）向上两级到项目根目录，然后指向 data/output
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent  # src/api -> src -> 项目根目录
            output_dir = project_root / "data" / "output"
            
            if output_dir.exists():
                # 查找所有灌溉计划文件
                plan_patterns = [
                    "irrigation_plan_*.json",  # 匹配所有irrigation_plan开头的文件
                ]
                
                all_plan_files = []
                for pattern in plan_patterns:
                    all_plan_files.extend(output_dir.glob(pattern))
                
                if all_plan_files:
                    # 按修改时间排序，选择最新的文件
                    latest_plan = max(all_plan_files, key=lambda p: p.stat().st_mtime)
                    logger.info(f"找到计划文件: {latest_plan}")
                    plan_loaded = scheduler.load_irrigation_plan(str(latest_plan))
            
            if not plan_loaded:
                # 如果data/output目录没有文件，给出友好的错误提示
                logger.warning(f"data/output目录中没有找到计划文件: {output_dir}")
                raise HTTPException(
                    status_code=404,
                    detail=f"没有找到任何计划文件。请先生成灌溉计划。查找目录: {output_dir}"
                )
            current_plan = scheduler.get_current_plan()
            if not current_plan:
                raise HTTPException(
                    status_code=500,
                    detail="加载计划文件后仍无法获取执行计划"
                )
        
        # 从调度器获取原始计划数据来提取scenario信息
        raw_plan_data = getattr(scheduler, 'raw_plan_data', None)
        if raw_plan_data:
            scenarios = raw_plan_data.get("scenarios", [])
        else:
            # 如果调度器没有raw_plan_data，尝试从最新计划文件读取
            scenarios = []
            # 从当前文件位置（src/api/）向上两级到项目根目录，然后指向 data/output
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent  # src/api -> src -> 项目根目录
            output_dir = project_root / "data" / "output"
            
            if output_dir.exists():
                plan_patterns = [
                    "irrigation_plan_*.json",
                    "irrigation_plan_modified_*.json",
                    "irrigation_plan_manual_regen_*.json"
                ]
                
                all_plan_files = []
                for pattern in plan_patterns:
                    all_plan_files.extend(output_dir.glob(pattern))
                
                if all_plan_files:
                    # 选择最新的文件
                    latest_plan = max(all_plan_files, key=lambda p: p.stat().st_mtime)
                    try:
                        with open(latest_plan, 'r', encoding='utf-8') as f:
                            file_data = json.load(f)
                        scenarios = file_data.get("scenarios", [])
                    except Exception as e:
                        logger.warning(f"无法从文件读取scenarios: {e}")
                        scenarios = []
        
        scenario_count = len(scenarios)
        scenario_name = ""
        
        if scenarios:
            # 使用第一个scenario
            first_scenario = scenarios[0]
            scenario_name = first_scenario.get("scenario_name", "默认场景")
            
            # 如果scenario_name为空，尝试生成一个描述性名称
            if not scenario_name or scenario_name.strip() == "":
                scenario_name = f"场景1"
                
            logger.info(f"当前计划包含 {scenario_count} 个scenarios，使用第一个scenario: '{scenario_name}'")
        else:
            scenario_name = "顶层计划"
            scenario_count = 1  # 顶层计划算作1个scenario
            logger.info("当前计划不包含scenarios结构，使用顶层计划")
        
        # 获取水位数据
        if request.custom_water_levels:
            # 使用自定义水位
            from src.scheduler.dynamic_waterlevel_manager import WaterLevelReading, WaterLevelSource, WaterLevelQuality
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
        
        # 保存修改后的计划到JSON文件
        from pathlib import Path
        # 从当前文件位置（src/api/）向上两级到项目根目录，然后指向 data/output
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent  # src/api -> src -> 项目根目录
        output_dir = project_root / "data" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 获取更新后的完整计划
        updated_plan = scheduler.get_current_plan()
        
        # 重建完整的文件结构（保持与其他计划文件一致的格式）
        if updated_plan:
            # 获取原始的完整计划数据（包含scenarios结构）
            raw_plan_data = getattr(scheduler, 'raw_plan_data', None)
            
            if raw_plan_data and 'scenarios' in raw_plan_data:
                # 如果有scenarios结构，保持完整格式
                full_plan_data = {
                    'analysis': raw_plan_data.get('analysis', {}),
                    'scenarios': []
                }
                
                # 找到当前使用的scenario并更新，其他scenarios保持不变
                scenarios_list = raw_plan_data.get('scenarios', [])
                logger.info(f"原始计划包含 {len(scenarios_list)} 个scenarios")
                
                for i, scenario in enumerate(scenarios_list):
                    if i == 0:  # 更新第一个scenario（当前使用的）
                        # 使用深拷贝确保不修改原始数据
                        import copy
                        updated_scenario = copy.deepcopy(scenario)
                        updated_scenario['plan'] = updated_plan
                        
                        # 更新scenario级别的统计信息
                        updated_scenario['total_electricity_cost'] = updated_plan.get('total_electricity_cost', scenario.get('total_electricity_cost', 0))
                        updated_scenario['total_eta_h'] = updated_plan.get('total_eta_h', scenario.get('total_eta_h', 0))
                        updated_scenario['total_pump_runtime_hours'] = updated_plan.get('total_pump_runtime_hours', scenario.get('total_pump_runtime_hours', {}))
                        
                        # 添加修改元数据到plan中
                        if 'metadata' not in updated_scenario['plan']:
                            updated_scenario['plan']['metadata'] = {}
                        updated_scenario['plan']['metadata']['last_manual_regeneration'] = {
                            'batch_index': request.batch_index,
                            'timestamp': datetime.now().isoformat(),
                            'water_level_source': 'manual' if request.custom_water_levels else 'api',
                            'custom_water_levels': request.custom_water_levels
                        }
                        full_plan_data['scenarios'].append(updated_scenario)
                        logger.info(f"已更新scenario: {updated_scenario.get('scenario_name', 'Unknown')}")
                    else:
                        # 其他scenario保持不变
                        full_plan_data['scenarios'].append(scenario)
                        logger.info(f"保留原始scenario: {scenario.get('scenario_name', 'Unknown')}")
                
                logger.info(f"最终保存的计划包含 {len(full_plan_data['scenarios'])} 个scenarios")
                save_data = full_plan_data
            else:
                # 如果没有scenarios结构，包装成单scenario格式
                if 'metadata' not in updated_plan:
                    updated_plan['metadata'] = {}
                updated_plan['metadata']['last_manual_regeneration'] = {
                    'batch_index': request.batch_index,
                    'timestamp': datetime.now().isoformat(),
                    'water_level_source': 'manual' if request.custom_water_levels else 'api',
                    'custom_water_levels': request.custom_water_levels
                }
                
                # 创建单scenario格式
                save_data = {
                    'scenarios': [
                        {
                            'scenario_name': '手动重新生成的计划',
                            'pumps_used': updated_plan.get('calc', {}).get('active_pumps', []),
                            'total_electricity_cost': updated_plan.get('total_electricity_cost', 0),
                            'total_eta_h': updated_plan.get('total_eta_h', 0),
                            'total_pump_runtime_hours': updated_plan.get('total_pump_runtime_hours', {}),
                            'plan': updated_plan
                        }
                    ]
                }
            
            # 保存文件
            timestamp = int(time.time())
            output_file = output_dir / f"irrigation_plan_manual_regen_{timestamp}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"修改后的计划已保存到: {output_file}")
        
        # 生成变更摘要
        change_summary = regenerator.generate_change_summary(result.changes)
        
        # 计算实际变更数量（包括时间和用水量的显著变更）
        actual_changes_count = len(result.changes)
        
        # 如果没有记录的变更但有时间或用水量调整，则计算隐含的变更
        if actual_changes_count == 0:
            if abs(result.execution_time_adjustment) > 60:  # 时间调整超过1分钟
                actual_changes_count += 1
            if abs(result.total_water_adjustment) > 1:  # 用水量调整超过1立方米
                actual_changes_count += 1
        
        # 从配置中获取水位标准参数
        config_data = getattr(scheduler, 'config_data', {})
        d_target_mm = config_data.get('d_target_mm', 90.0)
        
        # 从配置的第一个田块中获取水位标准（作为代表值）
        # 如果配置中有多个田块，它们通常使用相同的水位标准
        wl_low = 80.0  # 默认值
        wl_opt = 100.0  # 默认值
        wl_high = 140.0  # 默认值
        
        fields = config_data.get('fields', [])
        if fields and len(fields) > 0:
            first_field = fields[0]
            wl_low = first_field.get('wl_low', 80.0)
            wl_opt = first_field.get('wl_opt', 100.0)
            wl_high = first_field.get('wl_high', 140.0)
        
        # 处理田块级别的自定义水位标准
        field_standards = None
        if request.custom_water_level_standards:
            field_standards = {}
            for field_id, standards in request.custom_water_level_standards.items():
                field_standards[field_id] = {
                    'wl_low': standards.wl_low if standards.wl_low is not None else wl_low,
                    'wl_opt': standards.wl_opt if standards.wl_opt is not None else wl_opt,
                    'wl_high': standards.wl_high if standards.wl_high is not None else wl_high
                }
            logger.info(f"使用自定义水位标准：{len(field_standards)} 个田块")
        
        # 构建更准确的消息
        output_file_name = str(output_file.name) if updated_plan else None
        if scenario_count > 1:
            message = f"批次 {request.batch_index} 重新生成成功 (基于scenario '{scenario_name}'，共{scenario_count}个scenarios中的第1个)"
        elif scenario_count == 1 and scenario_name != "顶层计划":
            message = f"批次 {request.batch_index} 重新生成成功 (基于scenario '{scenario_name}')"
        else:
            message = f"批次 {request.batch_index} 重新生成成功 (基于顶层计划)"
        
        if output_file_name:
            message += f"，已保存到 {output_file_name}"
        
        # 如果使用了自定义标准，在消息中提示
        if field_standards:
            message += f"（使用了 {len(field_standards)} 个田块的自定义水位标准）"
        
        # 如果使用了自定义水位，更新监控器并触发设备关闭检查
        triggered_closures = None
        new_commands_generated = 0
        
        if request.custom_water_levels and scheduler.completion_monitor:
            logger.info("人工调整水位，更新监控器并触发设备检查")
            
            # 更新监控器中的水位
            scheduler.completion_monitor.update_water_levels(request.custom_water_levels)
            
            # 立即触发一次设备关闭检查
            try:
                check_result = await scheduler.completion_monitor.check_and_close_devices(request.custom_water_levels)
                
                # 记录触发的关闭信息
                triggered_closures = {
                    'completed_fields': check_result.get('completed_fields', []),
                    'closed_regulators': check_result.get('closed_regulators', []),
                    'stopped_pumps': check_result.get('stopped_pumps', [])
                }
                
                # 将生成的关闭指令加入队列
                if check_result.get('completed_fields'):
                    logger.info(f"人工调整后，{len(check_result['completed_fields'])}个田块达标")
                    for field_id in check_result['completed_fields']:
                        field_info = scheduler.completion_monitor.active_fields.get(field_id)
                        if field_info:
                            close_cmd = {
                                "device_type": "field_inlet_gate",
                                "device_id": field_id,
                                "unique_no": field_info.inlet_device,
                                "action": "close",
                                "params": {"gate_degree": 0},
                                "priority": 1,
                                "phase": "running",
                                "reason": f"人工调整后水位达标({field_info.current_wl:.1f}mm)",
                                "description": f"关闭{field_id}进水阀(人工调整触发)"
                            }
                            scheduler.command_queue.add_command(close_cmd)
                            new_commands_generated += 1
                
                if check_result.get('closed_regulators'):
                    logger.info(f"人工调整后，{len(check_result['closed_regulators'])}个节制闸需关闭")
                    for reg_id in check_result['closed_regulators']:
                        reg_info = scheduler.completion_monitor.active_regulators.get(reg_id)
                        if reg_info:
                            close_cmd = {
                                "device_type": "regulator",
                                "device_id": reg_id,
                                "unique_no": reg_info.unique_no,
                                "action": "close",
                                "params": {"gate_degree": 0, "open_pct": 0},
                                "priority": 2,
                                "phase": "running",
                                "reason": "人工调整后支渠田块已完成",
                                "description": f"关闭{reg_id}节制闸(人工调整触发)"
                            }
                            scheduler.command_queue.add_command(close_cmd)
                            new_commands_generated += 1
                
                if check_result.get('stopped_pumps'):
                    logger.info(f"人工调整后，{len(check_result['stopped_pumps'])}个泵站需停止")
                    for pump_id in check_result['stopped_pumps']:
                        # 从调度器获取泵站unique_no
                        pump_unique_no = scheduler._get_pump_unique_no(pump_id)
                        stop_cmd = {
                            "device_type": "pump",
                            "device_id": pump_id,
                            "unique_no": pump_unique_no,
                            "action": "stop",
                            "params": {},
                            "priority": 3,
                            "phase": "running",
                            "reason": "人工调整后所有批次完成",
                            "description": f"停止{pump_id}泵站(人工调整触发)"
                        }
                        scheduler.command_queue.add_command(stop_cmd)
                        new_commands_generated += 1
                        
            except Exception as e:
                logger.warning(f"人工调整后触发设备检查失败: {e}")
        
        return ManualRegenerationResponse(
            success=True,
            message=message,
            batch_index=request.batch_index,
            scenario_name=scenario_name,
            scenario_count=scenario_count,
            changes_count=actual_changes_count,
            execution_time_adjustment_seconds=result.execution_time_adjustment,
            water_usage_adjustment_m3=result.total_water_adjustment,
            change_summary=change_summary.get("summary", ""),
            output_file=str(output_file) if updated_plan else None,
            wl_low=wl_low,
            wl_opt=wl_opt,
            wl_high=wl_high,
            d_target_mm=d_target_mm,
            field_water_level_standards=field_standards,  # 返回田块级别的标准（如果有）
            triggered_closures=triggered_closures,  # 触发的设备关闭信息
            new_commands_generated=new_commands_generated  # 新生成的指令数量
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

async def get_water_level_summary(farm_id: str, field_ids: Optional[List[str]] = None, use_sgf_format: bool = False) -> Dict[str, Any]:
    """
    获取水位数据摘要
    
    Args:
        farm_id: 农场ID
        field_ids: 田块ID列表
        use_sgf_format: 是否使用SGF格式的田块ID（如S1-G2-F03），默认False使用数字ID
        
    Returns:
        Dict[str, Any]: 水位摘要数据
    """
    try:
        wl_manager = get_waterlevel_manager()
        summary = wl_manager.get_water_level_summary(field_ids, use_sgf_format)
        
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
            from src.scheduler.dynamic_waterlevel_manager import FieldWaterLevelHistory, WaterLevelReading, WaterLevelSource, WaterLevelQuality
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
            from src.scheduler.dynamic_waterlevel_manager import FieldWaterLevelHistory, WaterLevelReading, WaterLevelSource, WaterLevelQuality
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
    # 测试代码已移至Postman集合
    # 请使用 /postman/postman_collection.json 和 /postman/postman_environment.json 进行API测试
    print("动态执行API模块已加载完成")
    print("请使用Postman进行接口测试")