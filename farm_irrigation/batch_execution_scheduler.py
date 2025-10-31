#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批次执行调度器 - 动态水位更新灌溉系统

功能：
1. 监控批次执行时机
2. 在每个批次开始前获取最新水位读数
3. 基于新水位重新计算批次执行内容
4. 控制实际的设备执行
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

# 导入现有模块
try:
    from waterlevel_api import fetch_waterlevels
except ImportError:
    try:
        from mock_waterlevel_api import fetch_waterlevels
    except ImportError:
        fetch_waterlevels = None

from farm_irr_full_device_modified import (
    farmcfg_from_json_select, 
    build_concurrent_plan, 
    plan_to_json
)
from dynamic_waterlevel_manager import DynamicWaterLevelManager
from dynamic_plan_regenerator import DynamicPlanRegenerator
from execution_status_manager import ExecutionStatusManager, ExecutionStatus, get_status_manager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BatchStatus(Enum):
    """批次状态枚举"""
    PENDING = "pending"          # 等待执行
    PREPARING = "preparing"      # 准备中（获取水位、重新计算）
    EXECUTING = "executing"      # 执行中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"           # 执行失败
    CANCELLED = "cancelled"     # 已取消

@dataclass
class BatchExecution:
    """批次执行信息"""
    batch_index: int
    original_start_time: float  # 原始开始时间（小时）
    original_duration: float    # 原始持续时间（小时）
    current_start_time: Optional[float] = None  # 当前开始时间
    current_duration: Optional[float] = None    # 当前持续时间
    status: BatchStatus = BatchStatus.PENDING
    original_plan: Optional[Dict[str, Any]] = None
    updated_plan: Optional[Dict[str, Any]] = None
    water_levels: Optional[Dict[str, float]] = None
    execution_log: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

class BatchExecutionScheduler:
    """批次执行调度器"""
    
    def __init__(self, 
                 config_path: str = "config.json",
                 farm_id: str = "default_farm",
                 enable_realtime_waterlevels: bool = True,
                 pre_execution_buffer_minutes: int = 5):
        """
        初始化调度器
        
        Args:
            config_path: 配置文件路径
            farm_id: 农场ID，用于获取水位数据
            enable_realtime_waterlevels: 是否启用实时水位获取
            pre_execution_buffer_minutes: 批次执行前的缓冲时间（分钟）
        """
        self.config_path = Path(config_path)
        self.farm_id = farm_id
        self.enable_realtime_waterlevels = enable_realtime_waterlevels
        self.pre_execution_buffer_minutes = pre_execution_buffer_minutes
        
        # 执行状态
        self.is_running = False
        self.current_plan: Optional[Dict[str, Any]] = None
        self.batch_executions: Dict[int, BatchExecution] = {}
        self.execution_start_time: Optional[datetime] = None
        
        # 回调函数
        self.device_control_callback: Optional[Callable] = None
        self.status_update_callback: Optional[Callable] = None
        
        # 初始化组件
        self.status_manager = get_status_manager()
        
        # 加载配置
        self._load_config()
    
    def get_farm_id(self) -> str:
        """获取农场ID"""
        return self.farm_id
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
                logger.info(f"配置文件加载成功: {self.config_path}")
            else:
                logger.error(f"配置文件不存在: {self.config_path}")
                self.config_data = {}
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self.config_data = {}
    
    async def load_config(self, config_path: str):
        """
        异步加载配置文件
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self._load_config()
    
    def load_irrigation_plan(self, plan_path: str) -> bool:
        """
        加载灌溉计划
        
        Args:
            plan_path: 计划文件路径
            
        Returns:
            bool: 是否加载成功
        """
        try:
            plan_file = Path(plan_path)
            if not plan_file.exists():
                logger.error(f"计划文件不存在: {plan_path}")
                return False
            
            with open(plan_file, 'r', encoding='utf-8') as f:
                self.current_plan = json.load(f)
            
            # 解析批次信息
            self._parse_batches()
            
            logger.info(f"灌溉计划加载成功: {plan_path}")
            logger.info(f"共有 {len(self.batch_executions)} 个批次")
            
            return True
            
        except Exception as e:
            logger.error(f"加载灌溉计划失败: {e}")
            return False
    
    def _parse_batches(self):
        """解析批次信息"""
        self.batch_executions.clear()
        
        if not self.current_plan:
            return
        
        batches = self.current_plan.get("batches", [])
        steps = self.current_plan.get("steps", [])
        
        for batch in batches:
            batch_index = batch.get("index")
            if batch_index is None:
                continue
            
            # 从steps中找到对应的时间信息
            start_time = 0.0
            duration = 1.0  # 默认1小时
            
            batch_label = f"批次 {batch_index}"
            for step in steps:
                if step.get("label") == batch_label:
                    start_time = step.get("t_start_h", 0.0)
                    end_time = step.get("t_end_h", 1.0)
                    duration = end_time - start_time
                    break
            
            # 创建批次执行对象
            batch_execution = BatchExecution(
                batch_index=batch_index,
                original_start_time=start_time,
                original_duration=duration,
                original_plan=batch.copy()
            )
            
            self.batch_executions[batch_index] = batch_execution
            
            logger.info(f"批次 {batch_index}: 开始时间 {start_time:.2f}h, 持续时间 {duration:.2f}h")
    
    async def start_execution(self) -> bool:
        """
        开始执行灌溉计划
        
        Returns:
            bool: 是否启动成功
        """
        if self.is_running:
            self.status_manager.log_warning("scheduler", "调度器已在运行中")
            return False
        
        if not self.current_plan or not self.batch_executions:
            self.status_manager.log_error("scheduler", "没有可执行的灌溉计划")
            return False
        
        self.is_running = True
        self.execution_start_time = datetime.now()
        
        # 更新状态
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.status_manager.start_execution(batch_id, len(self.batch_executions))
        self.status_manager.log_info("scheduler", "开始执行灌溉计划")
        self.status_manager.log_info("scheduler", f"执行开始时间: {self.execution_start_time}")
        
        try:
            # 启动主执行循环
            await self._execution_loop()
            
        except Exception as e:
            self.status_manager.log_error("scheduler", f"执行过程中发生错误: {e}")
            self.is_running = False
            return False
        
        return True
    
    async def _execution_loop(self):
        """主执行循环"""
        while self.is_running and self._has_pending_batches():
            current_time = datetime.now()
            elapsed_hours = (current_time - self.execution_start_time).total_seconds() / 3600
            
            # 检查需要准备的批次
            for batch_index, batch_exec in self.batch_executions.items():
                if batch_exec.status == BatchStatus.PENDING:
                    # 计算是否需要开始准备
                    time_to_start = batch_exec.original_start_time - elapsed_hours
                    buffer_hours = self.pre_execution_buffer_minutes / 60
                    
                    if time_to_start <= buffer_hours:
                        logger.info(f"开始准备批次 {batch_index}")
                        await self._prepare_batch(batch_exec)
            
            # 检查需要执行的批次
            for batch_index, batch_exec in self.batch_executions.items():
                if batch_exec.status == BatchStatus.PREPARING:
                    # 检查是否到了执行时间
                    time_to_start = batch_exec.original_start_time - elapsed_hours
                    
                    if time_to_start <= 0:
                        logger.info(f"开始执行批次 {batch_index}")
                        await self._execute_batch(batch_exec)
            
            # 检查正在执行的批次是否完成
            for batch_index, batch_exec in self.batch_executions.items():
                if batch_exec.status == BatchStatus.EXECUTING:
                    await self._check_batch_completion(batch_exec, elapsed_hours)
            
            # 等待一段时间后再次检查
            await asyncio.sleep(30)  # 每30秒检查一次
        
        logger.info("所有批次执行完成")
        self.is_running = False
    
    def _has_pending_batches(self) -> bool:
        """检查是否还有待执行的批次"""
        for batch_exec in self.batch_executions.values():
            if batch_exec.status in [BatchStatus.PENDING, BatchStatus.PREPARING, BatchStatus.EXECUTING]:
                return True
        return False
    
    async def _prepare_batch(self, batch_exec: BatchExecution):
        """
        准备批次执行
        
        Args:
            batch_exec: 批次执行对象
        """
        try:
            batch_exec.status = BatchStatus.PREPARING
            batch_exec.execution_log.append(f"开始准备批次 {batch_exec.batch_index}")
            
            # 1. 获取最新水位数据
            if self.enable_realtime_waterlevels:
                water_levels = await self._fetch_current_water_levels()
                batch_exec.water_levels = water_levels
                batch_exec.execution_log.append(f"获取到 {len(water_levels)} 个田块的水位数据")
            
            # 2. 基于新水位重新生成批次计划
            updated_plan = await self._regenerate_batch_plan(batch_exec)
            batch_exec.updated_plan = updated_plan
            
            # 3. 更新执行时间（如果需要）
            batch_exec.current_start_time = batch_exec.original_start_time
            batch_exec.current_duration = batch_exec.original_duration
            
            batch_exec.execution_log.append(f"批次 {batch_exec.batch_index} 准备完成")
            
            # 通知状态更新
            if self.status_update_callback:
                await self.status_update_callback(batch_exec)
                
        except Exception as e:
            batch_exec.status = BatchStatus.FAILED
            batch_exec.error_message = str(e)
            batch_exec.execution_log.append(f"准备批次失败: {e}")
            logger.error(f"准备批次 {batch_exec.batch_index} 失败: {e}")
    
    async def _fetch_current_water_levels(self) -> Dict[str, float]:
        """
        获取当前水位数据
        
        Returns:
            Dict[str, float]: 田块ID到水位的映射
        """
        water_levels = {}
        
        try:
            if callable(fetch_waterlevels):
                # 调用水位API获取数据
                realtime_rows = fetch_waterlevels(self.farm_id)
                
                if realtime_rows:
                    # 解析水位数据
                    for row in realtime_rows:
                        field_id = row.get("field_id") or row.get("sectionID") or row.get("id")
                        water_level = row.get("waterlevel_mm") or row.get("water_level")
                        
                        if field_id and water_level is not None:
                            try:
                                water_levels[str(field_id)] = float(water_level)
                            except (ValueError, TypeError):
                                continue
                
                logger.info(f"从API获取到 {len(water_levels)} 个水位数据")
            else:
                logger.warning("水位API不可用，使用配置文件中的默认水位")
                
        except Exception as e:
            logger.error(f"获取水位数据失败: {e}")
        
        return water_levels
    
    async def _regenerate_batch_plan(self, batch_exec: BatchExecution) -> Dict[str, Any]:
        """
        基于新水位重新生成批次计划
        
        Args:
            batch_exec: 批次执行对象
            
        Returns:
            Dict[str, Any]: 更新后的批次计划
        """
        try:
            # 准备自定义水位数据
            custom_waterlevels = None
            if batch_exec.water_levels:
                custom_waterlevels = json.dumps(batch_exec.water_levels)
            
            # 重新生成配置
            cfg = farmcfg_from_json_select(
                self.config_data,
                active_pumps=None,  # 使用默认水泵配置
                zone_ids=None,      # 使用默认区域配置
                use_realtime_wl=True,
                custom_waterlevels=custom_waterlevels
            )
            
            # 重新生成计划
            new_plan = build_concurrent_plan(cfg)
            new_plan_json = plan_to_json(new_plan)
            
            logger.info(f"批次 {batch_exec.batch_index} 计划重新生成完成")
            
            return new_plan_json
            
        except Exception as e:
            logger.error(f"重新生成批次计划失败: {e}")
            # 如果重新生成失败，返回原始计划
            return batch_exec.original_plan or {}
    
    async def _execute_batch(self, batch_exec: BatchExecution):
        """
        执行批次
        
        Args:
            batch_exec: 批次执行对象
        """
        try:
            batch_exec.status = BatchStatus.EXECUTING
            batch_exec.started_at = datetime.now()
            batch_exec.execution_log.append(f"开始执行批次 {batch_exec.batch_index}")
            
            # 使用更新后的计划或原始计划
            plan_to_execute = batch_exec.updated_plan or batch_exec.original_plan
            
            if plan_to_execute and self.device_control_callback:
                # 调用设备控制回调
                await self.device_control_callback(batch_exec, plan_to_execute)
            
            logger.info(f"批次 {batch_exec.batch_index} 开始执行")
            
            # 通知状态更新
            if self.status_update_callback:
                await self.status_update_callback(batch_exec)
                
        except Exception as e:
            batch_exec.status = BatchStatus.FAILED
            batch_exec.error_message = str(e)
            batch_exec.execution_log.append(f"执行批次失败: {e}")
            logger.error(f"执行批次 {batch_exec.batch_index} 失败: {e}")
    
    async def _check_batch_completion(self, batch_exec: BatchExecution, elapsed_hours: float):
        """
        检查批次是否完成
        
        Args:
            batch_exec: 批次执行对象
            elapsed_hours: 已执行时间（小时）
        """
        # 简单的时间基础完成检查
        expected_end_time = batch_exec.original_start_time + batch_exec.original_duration
        
        if elapsed_hours >= expected_end_time:
            batch_exec.status = BatchStatus.COMPLETED
            batch_exec.completed_at = datetime.now()
            batch_exec.execution_log.append(f"批次 {batch_exec.batch_index} 执行完成")
            
            logger.info(f"批次 {batch_exec.batch_index} 执行完成")
            
            # 通知状态更新
            if self.status_update_callback:
                await self.status_update_callback(batch_exec)
    
    def stop_execution(self) -> bool:
        """停止执行
        
        Returns:
            bool: 是否成功停止
        """
        if not self.is_running:
            self.status_manager.log_warning("scheduler", "调度器未在运行")
            return False
        
        try:
            self.is_running = False
            self.status_manager.cancel_execution()
            self.status_manager.log_info("scheduler", "执行已停止")
            
            return True
            
        except Exception as e:
            self.status_manager.log_error("scheduler", f"停止执行失败: {str(e)}")
            return False
    
    def get_execution_status(self) -> Dict[str, Any]:
        """
        获取执行状态
        
        Returns:
            Dict[str, Any]: 执行状态信息
        """
        status = {
            "is_running": self.is_running,
            "execution_start_time": self.execution_start_time.isoformat() if self.execution_start_time else None,
            "total_batches": len(self.batch_executions),
            "batches": {}
        }
        
        for batch_index, batch_exec in self.batch_executions.items():
            status["batches"][batch_index] = {
                "status": batch_exec.status.value,
                "original_start_time": batch_exec.original_start_time,
                "original_duration": batch_exec.original_duration,
                "current_start_time": batch_exec.current_start_time,
                "current_duration": batch_exec.current_duration,
                "started_at": batch_exec.started_at.isoformat() if batch_exec.started_at else None,
                "completed_at": batch_exec.completed_at.isoformat() if batch_exec.completed_at else None,
                "error_message": batch_exec.error_message,
                "execution_log": batch_exec.execution_log[-5:],  # 最近5条日志
                "water_levels_count": len(batch_exec.water_levels) if batch_exec.water_levels else 0
            }
        
        return status
    
    def set_device_control_callback(self, callback: Callable):
        """设置设备控制回调函数"""
        self.device_control_callback = callback
    
    def set_status_update_callback(self, callback: Callable):
        """设置状态更新回调函数"""
        self.status_update_callback = callback
    
    def get_current_plan(self) -> Optional[Dict[str, Any]]:
        """
        获取当前的灌溉计划
        
        Returns:
            Optional[Dict[str, Any]]: 当前计划，如果没有则返回None
        """
        return self.current_plan

    def get_execution_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取执行历史"""
        return self.status_manager.get_execution_history(limit=limit)
    
    def get_field_trend_analysis(self, field_id: int, days: int = 7) -> Dict[str, Any]:
        """获取田块水位趋势分析"""
        # 这里应该实现具体的趋势分析逻辑
        # 目前返回一个基本的响应
        return {
            "field_id": field_id,
            "days": days,
            "trend": "stable",
            "average_level": 0.0,
            "min_level": 0.0,
            "max_level": 0.0,
            "data_points": []
        }

# 示例设备控制回调函数
async def example_device_control_callback(batch_exec: BatchExecution, plan: Dict[str, Any]):
    """
    示例设备控制回调函数
    
    Args:
        batch_exec: 批次执行对象
        plan: 执行计划
    """
    logger.info(f"执行批次 {batch_exec.batch_index} 的设备控制")
    
    # 这里应该实现实际的设备控制逻辑
    # 例如：启动水泵、开关阀门等
    
    # 模拟执行时间
    await asyncio.sleep(1)
    
    batch_exec.execution_log.append("设备控制命令已发送")

# 示例状态更新回调函数
async def example_status_update_callback(batch_exec: BatchExecution):
    """
    示例状态更新回调函数
    
    Args:
        batch_exec: 批次执行对象
    """
    logger.info(f"批次 {batch_exec.batch_index} 状态更新: {batch_exec.status.value}")

if __name__ == "__main__":
    # 示例用法
    async def main():
        # 创建调度器
        scheduler = BatchExecutionScheduler(
            config_path="config.json",
            farm_id="gzp_farm",
            enable_realtime_waterlevels=True,
            pre_execution_buffer_minutes=5
        )
        
        # 设置回调函数
        scheduler.set_device_control_callback(example_device_control_callback)
        scheduler.set_status_update_callback(example_status_update_callback)
        
        # 加载灌溉计划
        if scheduler.load_irrigation_plan("output/irrigation_plan_latest.json"):
            # 开始执行
            await scheduler.start_execution()
        else:
            logger.error("无法加载灌溉计划")
    
    # 运行示例
    asyncio.run(main())