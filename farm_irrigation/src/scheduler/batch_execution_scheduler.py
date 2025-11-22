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
    from src.api.waterlevel_api import fetch_waterlevels
except ImportError:
    try:
        from mock_waterlevel_api import fetch_waterlevels
    except ImportError:
        fetch_waterlevels = None

from src.core.farm_irr_full_device_modified import (
    farmcfg_from_json_select, 
    build_concurrent_plan, 
    plan_to_json
)
from .dynamic_waterlevel_manager import DynamicWaterLevelManager
from .dynamic_plan_regenerator import DynamicPlanRegenerator
from .execution_status_manager import ExecutionStatusManager, ExecutionStatus, get_status_manager

# 配置日志（修复编码问题）
import os
# 基于项目根目录计算日志路径
_log_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'execution_logs')
_log_dir = os.path.abspath(_log_dir)
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(_log_dir, 'batch_execution_scheduler.log'), encoding='utf-8')
    ]
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
                 config_path: str = None,
                 farm_id: str = "default_farm",
                 enable_realtime_waterlevels: bool = True,
                 pre_execution_buffer_minutes: int = 5,
                 app_id: str = None,
                 secret: str = None):
        """
        初始化调度器
        
        Args:
            config_path: 配置文件路径（如果为None，则基于项目根目录计算）
            farm_id: 农场ID，用于获取水位数据
            enable_realtime_waterlevels: 是否启用实时水位获取
            pre_execution_buffer_minutes: 批次执行前的缓冲时间（分钟）
            app_id: iLand平台应用ID
            secret: iLand平台密钥
        """
        # 如果未指定路径，基于项目根目录计算
        if config_path is None:
            project_root = Path(__file__).parent.parent.parent
            config_path = str(project_root / "config.json")
        
        self.config_path = Path(config_path)
        self.farm_id = farm_id
        self.enable_realtime_waterlevels = enable_realtime_waterlevels
        self.pre_execution_buffer_minutes = pre_execution_buffer_minutes
        
        # iLand平台认证
        import os
        self.app_id = app_id or os.getenv("ILAND_APP_ID", "")
        self.secret = secret or os.getenv("ILAND_SECRET", "")
        
        # 执行状态
        self.is_running = False
        self.execution_id: Optional[str] = None
        self.execution_status: str = "idle"  # idle, running, completed, error
        self.current_plan: Optional[Dict[str, Any]] = None
        self.raw_plan_data: Optional[Dict[str, Any]] = None  # 存储原始完整计划数据
        self.selected_scenario_name: Optional[str] = None  # 当前选中的方案名称
        self.batch_executions: Dict[int, BatchExecution] = {}
        self.execution_start_time: Optional[datetime] = None
        self.current_batch_index: int = 0
        self.total_regenerations: int = 0
        self.last_water_level_update: Optional[str] = None
        self.error_message: Optional[str] = None
        
        # 回调函数
        self.device_control_callback: Optional[Callable] = None
        self.status_update_callback: Optional[Callable] = None
        
        # 初始化组件
        self.status_manager = get_status_manager()
        
        # 设备指令队列
        from .device_command_queue import DeviceCommandQueue
        self.command_queue = DeviceCommandQueue()
        
        # 田块完成度监控器（延迟初始化）
        self.completion_monitor = None
        
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
                raw_data = json.load(f)
            
            # 保存原始完整数据
            self.raw_plan_data = raw_data
            
            # 检查文件结构并提取实际的计划数据
            if "scenarios" in raw_data and raw_data["scenarios"]:
                # 新格式：使用第一个scenario的plan
                selected_scenario = raw_data["scenarios"][0]
                self.current_plan = selected_scenario["plan"]
                self.selected_scenario_name = selected_scenario.get("scenario_name", "Unknown")
                logger.info(f"使用scenarios格式，选择第一个scenario: {self.selected_scenario_name}")
            elif "batches" in raw_data and "steps" in raw_data:
                # 旧格式：直接使用根级别的数据
                self.current_plan = raw_data
                self.selected_scenario_name = "Default Plan"
                logger.info("使用传统格式的计划文件")
            else:
                logger.error(f"无法识别的计划文件格式: {plan_path}")
                return False

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
        
        # 设置执行状态
        self.is_running = True
        self.execution_start_time = datetime.now()
        self.execution_id = f"exec_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.execution_status = "running"
        self.current_batch_index = 0
        self.error_message = None
        
        # 更新状态
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        # 使用update_execution_status而不是不存在的start_execution方法
        self.status_manager.update_execution_status(
            farm_id=batch_id,
            batch_index=1,  # 开始执行时使用批次1
            status=ExecutionStatus.RUNNING,
            total_batches=len(self.batch_executions),
            current_batch=0
        )
        self.status_manager.log_info("scheduler", f"开始执行灌溉计划，执行ID: {self.execution_id}")
        self.status_manager.log_info("scheduler", f"执行开始时间: {self.execution_start_time}")
        
        try:
            # 在后台启动主执行循环，不阻塞当前调用
            import asyncio
            asyncio.create_task(self._execution_loop())
            
        except Exception as e:
            self.status_manager.log_error("scheduler", f"启动执行循环失败: {e}")
            self.is_running = False
            self.execution_status = "error"
            self.error_message = str(e)
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
        
        # 执行完成，更新状态
        logger.info("所有批次执行完成")
        self.is_running = False
        self.execution_status = "completed"
    
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
                
                # 更新最后水位更新时间
                self.last_water_level_update = datetime.now().isoformat()
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
            
            # 更新重新生成计数
            self.total_regenerations += 1
            
            logger.info(f"批次 {batch_exec.batch_index} 计划重新生成完成")
            
            return new_plan_json
            
        except Exception as e:
            logger.error(f"重新生成批次计划失败: {e}")
            # 如果重新生成失败，返回原始计划
            return batch_exec.original_plan or {}
    
    async def _execute_batch(self, batch_exec: BatchExecution):
        """
        执行批次（增强版 - 集成实时监控）
        
        Args:
            batch_exec: 批次执行对象
        """
        try:
            batch_exec.status = BatchStatus.EXECUTING
            batch_exec.started_at = datetime.now()
            batch_exec.execution_log.append(f"开始执行批次 {batch_exec.batch_index}")
            
            # 更新当前批次索引
            self.current_batch_index = batch_exec.batch_index
            
            # 使用更新后的计划或原始计划
            plan_to_execute = batch_exec.updated_plan or batch_exec.original_plan
            
            # 1. 生成启动指令并加入队列
            start_commands = self._generate_batch_start_commands(plan_to_execute, batch_exec.batch_index)
            for cmd in start_commands:
                cmd['phase'] = 'start'
                self.command_queue.add_command(cmd)
            
            logger.info(f"批次 {batch_exec.batch_index} 已生成 {len(start_commands)} 条启动指令")
            
            # 2. 初始化监控器
            self._initialize_batch_monitoring(plan_to_execute, batch_exec.batch_index)
            
            # 3. 启动实时监控循环
            await self._monitor_batch_until_completion(batch_exec)
            
            logger.info(f"批次 {batch_exec.batch_index} 执行完成")
            
            # 通知状态更新
            if self.status_update_callback:
                await self.status_update_callback(batch_exec)
                
        except Exception as e:
            batch_exec.status = BatchStatus.FAILED
            batch_exec.error_message = str(e)
            batch_exec.execution_log.append(f"执行批次失败: {e}")
            self.error_message = str(e)
            self.execution_status = "error"
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
        # 计算当前批次和完成的批次
        completed_batches = []
        active_fields = []
        
        for batch_index, batch_exec in self.batch_executions.items():
            if batch_exec.status == BatchStatus.COMPLETED:
                completed_batches.append({
                    "batch_index": batch_index,
                    "completed_at": batch_exec.completed_at.isoformat() if batch_exec.completed_at else None,
                    "duration": batch_exec.current_duration
                })
            elif batch_exec.status == BatchStatus.EXECUTING:
                self.current_batch_index = batch_index
                # 从批次执行中提取活跃字段信息
                if hasattr(batch_exec, 'execution_plan') and batch_exec.execution_plan:
                    for field_id, field_data in batch_exec.execution_plan.items():
                        active_fields.append({
                            "field_id": field_id,
                            "status": "running",
                            "start_time": batch_exec.started_at.isoformat() if batch_exec.started_at else None
                        })
        
        return {
            "execution_id": self.execution_id or "",
            "status": self.execution_status,
            "current_batch": self.current_batch_index,
            "total_batches": len(self.batch_executions),
            "start_time": self.execution_start_time.isoformat() if self.execution_start_time else None,
            "last_water_level_update": self.last_water_level_update,
            "total_regenerations": self.total_regenerations,
            "active_fields": active_fields,
            "completed_batches": completed_batches,
            "error_message": self.error_message
        }
    
    def get_all_scenarios_info(self) -> Dict[str, Any]:
        """
        获取所有scenarios的信息
        
        Returns:
            Dict[str, Any]: 包含所有方案信息的字典
        """
        if not self.raw_plan_data:
            return {
                "selected_scenario": None,
                "all_scenarios": [],
                "total_scenarios": 0
            }
        
        all_scenarios = []
        selected_scenario = None
        
        # 检查是否有scenarios结构
        if "scenarios" in self.raw_plan_data and self.raw_plan_data["scenarios"]:
            for scenario in self.raw_plan_data["scenarios"]:
                scenario_info = {
                    "scenario_name": scenario.get("scenario_name", "Unknown"),
                    "pumps_used": scenario.get("pumps_used", []),
                    "total_batches": len(scenario.get("plan", {}).get("batches", [])),
                    "total_electricity_cost": scenario.get("total_electricity_cost", 0.0),
                    "total_eta_h": scenario.get("total_eta_h", 0.0),
                    "total_pump_runtime_hours": scenario.get("total_pump_runtime_hours", 0.0),
                    "coverage_info": scenario.get("coverage_info", {})
                }
                all_scenarios.append(scenario_info)
                
                # 检查是否是当前选中的方案
                if scenario.get("scenario_name") == self.selected_scenario_name:
                    selected_scenario = scenario_info
        else:
            # 旧格式，只有一个默认方案
            scenario_info = {
                "scenario_name": "Default Plan",
                "pumps_used": [],
                "total_batches": len(self.raw_plan_data.get("batches", [])),
                "total_electricity_cost": 0.0,
                "total_eta_h": 0.0,
                "total_pump_runtime_hours": 0.0,
                "coverage_info": {}
            }
            all_scenarios.append(scenario_info)
            selected_scenario = scenario_info
        
        return {
            "selected_scenario": selected_scenario,
            "all_scenarios": all_scenarios,
            "total_scenarios": len(all_scenarios)
        }
    
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

    async def update_batch_plan(self, batch_index: int, new_commands: List[Dict[str, Any]]) -> bool:
        """
        更新指定批次的执行计划
        
        Args:
            batch_index: 批次索引
            new_commands: 新的执行命令列表
            
        Returns:
            bool: 更新是否成功
        """
        try:
            if batch_index < 0 or batch_index >= len(self.batch_executions):
                logger.error(f"批次索引 {batch_index} 超出范围")
                return False
            
            batch_exec = self.batch_executions[batch_index]
            
            # 只允许更新未开始或准备中的批次
            if batch_exec.status not in [BatchStatus.PENDING, BatchStatus.PREPARING]:
                logger.error(f"批次 {batch_index} 状态为 {batch_exec.status.value}，无法更新")
                return False
            
            # 更新批次的执行命令
            batch_exec.regenerated_commands = new_commands
            batch_exec.execution_log.append(f"批次计划已更新，新命令数量: {len(new_commands)}")
            
            # 更新状态管理器
            await self.status_manager.update_execution_status(
                farm_id=self.farm_id,
                batch_id=f"batch_{batch_index}",
                status="plan_updated",
                progress=0,
                message=f"批次 {batch_index} 计划已更新"
            )
            
            logger.info(f"批次 {batch_index} 计划更新成功")
            return True
            
        except Exception as e:
            logger.error(f"更新批次 {batch_index} 计划失败: {e}")
            return False

    def get_execution_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取执行历史
        
        Args:
            limit: 返回记录数限制
            
        Returns:
            List[Dict[str, Any]]: 执行历史列表
        """
        try:
            # 从状态管理器获取执行历史
            logs = self.status_manager.get_execution_logs(
                farm_id=self.farm_id,
                limit=limit
            )
            
            # 转换为API响应格式
            history = []
            for log in logs:
                history_item = {
                    "execution_id": log.get("batch_id", ""),
                    "farm_id": self.farm_id,
                    "status": log.get("status", "unknown"),
                    "start_time": log.get("timestamp", ""),
                    "end_time": log.get("end_time", ""),
                    "total_batches": len(self.batch_executions) if self.batch_executions else 0,
                    "completed_batches": log.get("progress", 0),
                    "error_message": log.get("error_message", ""),
                    "message": log.get("message", "")
                }
                history.append(history_item)
            
            return history
            
        except Exception as e:
            logger.error(f"获取执行历史失败: {e}")
            return []
    
    def get_field_trend_analysis(self, field_id: str, days: int = 7) -> Dict[str, Any]:
        """
        获取田块水位趋势分析
        
        Args:
            field_id: 田块ID
            days: 分析天数
            
        Returns:
            Dict[str, Any]: 趋势分析结果
        """
        try:
            # 从水位管理器获取趋势分析
            if hasattr(self, 'waterlevel_manager') and self.waterlevel_manager:
                analysis = self.waterlevel_manager.get_field_trend_analysis(field_id, days * 24)  # 转换为小时
                return analysis
            else:
                # 返回基本的响应
                return {
                    "field_id": field_id,
                    "analysis_period_days": days,
                    "trend_direction": "stable",
                    "average_level_mm": 0.0,
                    "min_level_mm": 0.0,
                    "max_level_mm": 0.0,
                    "data_points_count": 0,
                    "confidence": 0.0,
                    "last_update": datetime.now().isoformat(),
                    "message": "水位管理器未初始化，返回默认数据"
                }
                
        except Exception as e:
            logger.error(f"获取田块 {field_id} 趋势分析失败: {e}")
            return {
                "field_id": field_id,
                "analysis_period_days": days,
                "error": str(e),
                "message": "趋势分析失败"
            }

    async def get_batch_details(self, batch_index: int) -> Optional[Dict[str, Any]]:
        """
        获取批次详细信息
        
        Args:
            batch_index: 批次索引
            
        Returns:
            Optional[Dict[str, Any]]: 批次详细信息
        """
        try:
            if batch_index < 0 or batch_index >= len(self.batch_executions):
                return None
            
            batch_exec = self.batch_executions[batch_index]
            
            # 获取批次详细信息
            details = await self.status_manager.get_batch_details(f"batch_{batch_index}")
            
            # 构建响应
            batch_details = {
                "batch_index": batch_index,
                "status": batch_exec.status.value,
                "start_time": batch_exec.start_time.isoformat() if batch_exec.start_time else None,
                "duration_minutes": batch_exec.duration_minutes,
                "original_commands_count": len(batch_exec.original_commands) if batch_exec.original_commands else 0,
                "regenerated_commands_count": len(batch_exec.regenerated_commands) if batch_exec.regenerated_commands else 0,
                "water_levels_count": len(batch_exec.water_levels) if batch_exec.water_levels else 0,
                "execution_log": batch_exec.execution_log,
                "database_details": details
            }
            
            return batch_details
            
        except Exception as e:
            logger.error(f"获取批次 {batch_index} 详细信息失败: {e}")
            return None

    def get_farm_id(self) -> str:
        """获取农场ID"""
        return self.farm_id

    async def cleanup_old_data(self, retention_days: int = 30):
        """
        清理旧数据
        
        Args:
            retention_days: 数据保留天数
        """
        try:
            await self.status_manager.cleanup_old_data(retention_days)
            logger.info(f"清理 {retention_days} 天前的旧数据完成")
        except Exception as e:
            logger.error(f"清理旧数据失败: {e}")
    
    def _generate_batch_start_commands(self, plan: Dict[str, Any], batch_index: int) -> List[Dict]:
        """
        生成批次启动指令
        
        Args:
            plan: 批次计划（可能是完整计划或单个批次）
            batch_index: 批次索引
        
        Returns:
            List[Dict]: 指令列表
        """
        commands = []
        
        # 提取步骤和田块列表 - 兼容两种格式
        steps_list = []
        fields_list = []
        
        # 格式1：plan直接包含steps和fields（单个批次格式）
        if 'steps' in plan:
            steps_list = plan.get('steps', [])
        if 'fields' in plan and plan['fields']:
            fields_list = plan['fields']
        
        # 格式2：plan包含batches数组（完整计划格式）
        if 'batches' in plan:
            # 从batches中找到对应批次
            for batch in plan['batches']:
                if batch.get('index') == batch_index:
                    fields_list = batch.get('fields', [])
                    break
            # 从steps中找到对应批次的step
            all_steps = plan.get('steps', [])
            batch_label = f"批次 {batch_index}"
            for step in all_steps:
                if step.get('label') == batch_label:
                    steps_list = [step]
                    break
        
        # 1. 泵站启动指令
        for step in steps_list:
            pumps_on = step.get('sequence', {}).get('pumps_on', [])
            for pump_id in pumps_on:
                # 从配置数据中查找泵站的unique_no
                pump_unique_no = self._get_pump_unique_no(pump_id)
                commands.append({
                    "device_type": "pump",
                    "device_id": pump_id,
                    "unique_no": pump_unique_no,
                    "action": "start",
                    "params": {},
                    "priority": 1,
                    "description": f"启动{pump_id}泵站"
                })
        
        # 2. 节制闸开启指令
        for step in steps_list:
            gates_set = step.get('sequence', {}).get('gates_set', [])
            for gate in gates_set:
                if gate.get('open_pct', 0) > 0:
                    commands.append({
                        "device_type": "regulator",
                        "device_id": gate['id'],
                        "unique_no": gate.get('unique_no'),
                        "action": "open",
                        "params": {"open_pct": gate['open_pct'], "gate_degree": gate['open_pct']},
                        "priority": 2,
                        "description": f"开启{gate['id']}节制闸({gate['open_pct']}%)"
                    })
        
        # 3. 田块进水阀开启指令
        for field in fields_list:
            commands.append({
                "device_type": "field_inlet_gate",
                "device_id": field['id'],
                "unique_no": field.get('inlet_unique_no'),
                "action": "open",
                "params": {"gate_degree": 100},
                "priority": 3,
                "description": f"开启{field['id']}进水阀"
            })
        
        # 按优先级排序
        commands.sort(key=lambda x: x['priority'])
        
        return commands
    
    def _get_pump_unique_no(self, pump_id: str) -> Optional[str]:
        """
        从配置数据中获取泵站的unique_no
        
        Args:
            pump_id: 泵站ID（如 "P1"）
        
        Returns:
            Optional[str]: 泵站的unique_no，如果找不到则返回None
        """
        try:
            pumps = self.config_data.get('pumps', [])
            for pump in pumps:
                if pump.get('id') == pump_id:
                    return pump.get('unique_no')
            
            logger.warning(f"未找到泵站 {pump_id} 的unique_no")
            return None
        except Exception as e:
            logger.error(f"获取泵站unique_no失败: {e}")
            return None
    
    def _initialize_batch_monitoring(self, plan: Dict[str, Any], batch_index: int):
        """
        初始化批次监控
        
        Args:
            plan: 批次计划（可能是完整计划或单个批次）
            batch_index: 批次索引
        """
        # 延迟初始化监控器
        if self.completion_monitor is None:
            from .field_completion_monitor import FieldCompletionMonitor
            self.completion_monitor = FieldCompletionMonitor(
                config_data=self.config_data,
                app_id=self.app_id,
                secret=self.secret,
                check_interval=30
            )
        
        # 提取田块信息 - 兼容两种格式
        batch_fields = []
        fields_list = []
        
        # 格式1：plan直接包含fields（单个批次格式）
        if 'fields' in plan and plan['fields']:
            fields_list = plan['fields']
        # 格式2：plan包含batches数组（完整计划格式）
        elif 'batches' in plan:
            for batch in plan['batches']:
                if batch.get('index') == batch_index:
                    fields_list = batch.get('fields', [])
                    break
        
        for field in fields_list:
            batch_fields.append({
                'id': field['id'],
                'segment_id': field.get('segment_id', ''),
                'inlet_gid': field.get('inlet_G_id', ''),
                'wl_mm': field.get('wl_mm', 0.0),
                'wl_opt': field.get('wl_opt', 50.0),
                'wl_high': field.get('wl_high', 80.0),
                'inlet_unique_no': field.get('inlet_unique_no', ''),
                'outlet_unique_no': field.get('outlet_unique_no', None)
            })
        
        # 提取节制闸信息
        batch_regulators = []
        for step in plan.get('steps', []):
            for gate in step.get('sequence', {}).get('gates_set', []):
                if gate.get('open_pct', 0) > 0:
                    segment_id = self._extract_segment_from_gate_id(gate['id'])
                    batch_regulators.append({
                        'id': gate['id'],
                        'type': gate.get('type', 'branch-g'),
                        'segment_id': segment_id,
                        'unique_no': gate.get('unique_no', None),
                        'open_pct': gate['open_pct']
                    })
        
        # 提取泵站信息
        batch_pumps = []
        for step in plan.get('steps', []):
            pumps_on = step.get('sequence', {}).get('pumps_on', [])
            batch_pumps.extend(pumps_on)
        
        # 去重
        batch_pumps = list(set(batch_pumps))
        
        # 初始化监控器
        self.completion_monitor.initialize_batch(
            batch_fields=batch_fields,
            batch_regulators=batch_regulators,
            batch_pumps=batch_pumps
        )
        
        logger.info(f"批次 {batch_index} 监控初始化完成: "
                   f"{len(batch_fields)}田块, {len(batch_regulators)}节制闸, {len(batch_pumps)}泵站")
    
    async def _monitor_batch_until_completion(self, batch_exec: BatchExecution):
        """
        实时监控直到批次完成
        
        Args:
            batch_exec: 批次执行对象
        """
        check_count = 0
        max_duration_hours = batch_exec.original_duration * 2  # 超时保护：预计时间的2倍
        max_checks = int(max_duration_hours * 3600 / 30)  # 每30秒检查一次
        no_data_count = 0  # 无水位数据计数器
        
        logger.info(f"批次 {batch_exec.batch_index} 开始实时监控（预计 {batch_exec.original_duration:.2f}h）")
        logger.info(f"💡 提示：系统将每30秒检查一次水位，自动关闭达标设备")
        
        while check_count < max_checks:
            check_count += 1
            
            # 1. 获取最新水位
            latest_wl = await self._fetch_current_water_levels()
            
            if not latest_wl:
                no_data_count += 1
                # 只在第1次和每10次时输出警告，避免日志过多
                if no_data_count == 1:
                    logger.warning(f"⚠️ 未获取到实时水位数据，将使用配置文件中的初始水位继续监控")
                elif no_data_count % 10 == 0:
                    logger.debug(f"已尝试 {no_data_count} 次，仍未获取到水位数据")
                await asyncio.sleep(30)
                continue
            else:
                # 成功获取数据后重置计数器
                if no_data_count > 0:
                    logger.info(f"✅ 已恢复水位数据获取")
                    no_data_count = 0
            
            # 2. 检查并生成关闭指令
            result = await self.completion_monitor.check_and_close_devices(latest_wl)
            
            # 3. 将关闭指令加入队列
            if result['completed_fields']:
                for field_id in result['completed_fields']:
                    field_info = self.completion_monitor.active_fields.get(field_id)
                    if field_info:
                        close_cmd = {
                            "device_type": "field_inlet_gate",
                            "device_id": field_id,
                            "unique_no": field_info.inlet_device,
                            "action": "close",
                            "params": {"gate_degree": 0},
                            "priority": 1,
                            "phase": "running",
                            "reason": f"水位达标({field_info.current_wl:.1f}mm)",
                            "description": f"关闭{field_id}进水阀"
                        }
                        self.command_queue.add_command(close_cmd)
            
            if result['closed_regulators']:
                for reg_id in result['closed_regulators']:
                    reg_info = self.completion_monitor.active_regulators.get(reg_id)
                    if reg_info:
                        close_cmd = {
                            "device_type": "regulator",
                            "device_id": reg_id,
                            "unique_no": reg_info.unique_no,
                            "action": "close",
                            "params": {"gate_degree": 0, "open_pct": 0},
                            "priority": 2,
                            "phase": "running",
                            "reason": f"支渠{reg_info.segment_id}所有田块已完成",
                            "description": f"关闭{reg_id}节制闸"
                        }
                        self.command_queue.add_command(close_cmd)
            
            if result['stopped_pumps']:
                for pump_id in result['stopped_pumps']:
                    pump_unique_no = self._get_pump_unique_no(pump_id)
                    stop_cmd = {
                        "device_type": "pump",
                        "device_id": pump_id,
                        "unique_no": pump_unique_no,
                        "action": "stop",
                        "params": {},
                        "priority": 3,
                        "phase": "running",
                        "reason": "所有批次完成",
                        "description": f"停止{pump_id}泵站"
                    }
                    self.command_queue.add_command(stop_cmd)
            
            # 4. 检查是否完成
            if result['all_completed']:
                batch_exec.status = BatchStatus.COMPLETED
                batch_exec.completed_at = datetime.now()
                
                actual_duration = (batch_exec.completed_at - batch_exec.started_at).total_seconds() / 3600
                logger.info(f"✅ 批次 {batch_exec.batch_index} 完成！")
                logger.info(f"  预计时间: {batch_exec.original_duration:.2f}h")
                logger.info(f"  实际时间: {actual_duration:.2f}h")
                logger.info(f"  完成田块: {len(result['completed_fields'])}")
                break
            
            # 5. 显示进度
            if self.completion_monitor:
                stats = self.completion_monitor.get_statistics()
                progress = (stats['completed_fields'] / stats['total_fields']) * 100 if stats['total_fields'] > 0 else 0
                logger.info(f"批次 {batch_exec.batch_index} 进度: {progress:.0f}% "
                           f"({stats['completed_fields']}/{stats['total_fields']} 田块)")
            
            # 6. 等待30秒后继续
            await asyncio.sleep(30)
        
        # 超时保护
        if check_count >= max_checks:
            logger.warning(f"批次 {batch_exec.batch_index} 超时（已检查{check_count}次），强制完成")
            batch_exec.status = BatchStatus.COMPLETED
            batch_exec.completed_at = datetime.now()
    
    @staticmethod
    def _extract_segment_from_gate_id(gate_id: str) -> str:
        """从闸门ID提取支渠ID，如 S3-G2 → S3"""
        if '-G' in gate_id:
            return gate_id.split('-G')[0]
        return gate_id
    
    async def _fetch_current_water_levels(self) -> Dict[str, float]:
        """
        获取当前最新水位数据
        
        Returns:
            Dict[str, float]: 田块ID到水位(mm)的映射
        """
        try:
            from src.api.waterlevel_api import fetch_waterlevels
            
            # 调用水位API获取最新数据（只需要farm_id）
            response = fetch_waterlevels(farm_id=self.farm_id)
            
            if not response:
                # 使用DEBUG级别，避免过多警告信息
                logger.debug(f"水位API未返回数据（farm_id={self.farm_id}），将使用配置文件中的初始水位")
                return {}
            
            # 解析水位数据
            water_levels = {}
            for item in response:
                # waterlevel_api 返回格式: {"sectionID": str, "sectionCode": str, "waterlevel_mm": float}
                section_code = item.get('sectionCode')
                wl_mm = item.get('waterlevel_mm')
                if section_code and wl_mm is not None:
                    water_levels[section_code] = wl_mm
            
            logger.info(f"✅ 获取到 {len(water_levels)} 个田块的实时水位数据")
            return water_levels
            
        except Exception as e:
            logger.debug(f"获取水位数据异常: {e}，将使用配置文件中的初始水位")
            return {}

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