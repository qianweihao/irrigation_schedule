#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态计划重新生成器

功能：
1. 基于新的水位数据重新计算灌溉计划
2. 智能调整批次执行内容
3. 保持计划的连续性和一致性
4. 提供计划变更分析和影响评估
"""

import json
import logging
import copy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

# 导入相关模块
from dynamic_waterlevel_manager import WaterLevelReading, DynamicWaterLevelManager

# 配置日志
logger = logging.getLogger(__name__)

class PlanChangeType(Enum):
    """计划变更类型"""
    NO_CHANGE = "no_change"           # 无变更
    DURATION_ADJUSTED = "duration_adjusted"     # 持续时间调整
    FLOW_RATE_ADJUSTED = "flow_rate_adjusted"   # 流量调整
    TIMING_SHIFTED = "timing_shifted"           # 时间偏移
    FIELD_ADDED = "field_added"                 # 田块添加
    FIELD_REMOVED = "field_removed"             # 田块移除
    BATCH_SPLIT = "batch_split"                 # 批次分割
    BATCH_MERGED = "batch_merged"               # 批次合并
    CANCELLED = "cancelled"                     # 取消执行

class PlanChangeImpact(Enum):
    """计划变更影响级别"""
    MINIMAL = "minimal"       # 最小影响
    MODERATE = "moderate"     # 中等影响
    SIGNIFICANT = "significant"  # 重大影响
    CRITICAL = "critical"     # 关键影响

@dataclass
class PlanChange:
    """计划变更记录"""
    change_type: PlanChangeType
    impact_level: PlanChangeImpact
    field_id: str
    batch_index: int
    old_value: Any
    new_value: Any
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class BatchRegenerationResult:
    """批次重新生成结果"""
    batch_index: int
    success: bool
    original_commands: List[Dict[str, Any]]
    regenerated_commands: List[Dict[str, Any]]
    changes: List[PlanChange]
    water_level_changes: Dict[str, Tuple[float, float]]  # field_id -> (old_wl, new_wl)
    execution_time_adjustment: float = 0.0  # 执行时间调整（秒）
    total_water_adjustment: float = 0.0     # 总用水量调整（立方米）
    error_message: Optional[str] = None

class DynamicPlanRegenerator:
    """动态计划重新生成器"""
    
    def __init__(self, 
                 config_path: str = "config.json",
                 plan_template_path: str = "irrigation_plan_template.json",
                 regeneration_rules: Optional[Dict[str, Any]] = None):
        """
        初始化计划重新生成器
        
        Args:
            config_path: 配置文件路径
            plan_template_path: 计划模板路径
            regeneration_rules: 重新生成规则配置
        """
        self.config_path = Path(config_path)
        self.plan_template_path = Path(plan_template_path)
        
        # 重新生成规则
        self.regeneration_rules = regeneration_rules or {
            "water_level_threshold_mm": 10,      # 水位变化阈值
            "max_duration_adjustment_ratio": 0.5, # 最大持续时间调整比例
            "max_flow_rate_adjustment_ratio": 0.3, # 最大流量调整比例
            "min_irrigation_duration_minutes": 5,  # 最小灌溉持续时间
            "max_irrigation_duration_minutes": 180, # 最大灌溉持续时间
            "water_level_target_mm": 50,          # 目标水位
            "water_level_tolerance_mm": 5,        # 水位容差
            "enable_smart_scheduling": True,       # 启用智能调度
            "enable_flow_optimization": True,     # 启用流量优化
            "enable_timing_optimization": True    # 启用时间优化
        }
        
        # 数据存储
        self.config_data: Dict[str, Any] = {}
        self.plan_template: Dict[str, Any] = {}
        self.field_configs: Dict[str, Dict[str, Any]] = {}
        
        # 加载配置
        self._load_config()
        self._load_plan_template()
        self._build_field_configs()
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
                logger.info(f"配置文件加载成功: {self.config_path}")
            else:
                logger.warning(f"配置文件不存在: {self.config_path}")
                self.config_data = {}
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self.config_data = {}
    
    def _load_plan_template(self):
        """加载计划模板"""
        try:
            if self.plan_template_path.exists():
                with open(self.plan_template_path, 'r', encoding='utf-8') as f:
                    self.plan_template = json.load(f)
                logger.info(f"计划模板加载成功: {self.plan_template_path}")
            else:
                logger.warning(f"计划模板不存在: {self.plan_template_path}")
                self.plan_template = {}
        except Exception as e:
            logger.error(f"加载计划模板失败: {e}")
            self.plan_template = {}
    
    def _build_field_configs(self):
        """构建田块配置映射"""
        self.field_configs = {}
        
        fields = self.config_data.get("fields", [])
        for field in fields:
            field_id = str(field.get("id", ""))
            if field_id:
                self.field_configs[field_id] = field
    
    async def regenerate_batch_plan(self, 
                                   batch_index: int,
                                   original_plan: Dict[str, Any],
                                   new_water_levels: Dict[str, WaterLevelReading],
                                   execution_context: Optional[Dict[str, Any]] = None) -> BatchRegenerationResult:
        """
        重新生成批次计划
        
        Args:
            batch_index: 批次索引
            original_plan: 原始计划
            new_water_levels: 新的水位数据
            execution_context: 执行上下文
            
        Returns:
            BatchRegenerationResult: 重新生成结果
        """
        try:
            logger.info(f"开始重新生成批次 {batch_index} 的计划")
            
            # 提取原始命令
            logger.debug("提取原始命令...")
            original_commands = self._extract_batch_commands(original_plan, batch_index)
            logger.debug(f"提取到 {len(original_commands)} 个原始命令: {original_commands}")
            
            # 分析水位变化
            logger.debug("分析水位变化...")
            water_level_changes = self._analyze_water_level_changes(original_commands, new_water_levels)
            logger.debug(f"水位变化: {water_level_changes}")
            
            # 重新生成命令
            logger.debug("重新生成命令...")
            regenerated_commands, regeneration_changes = await self._regenerate_commands(
                original_commands, 
                new_water_levels, 
                water_level_changes
            )
            logger.debug(f"重新生成的命令: {regenerated_commands}")
            
            # 分析变更
            logger.debug("分析计划变更...")
            changes = self._analyze_plan_changes(original_commands, regenerated_commands)
            
            # 合并重新生成过程中的变更
            changes.extend(regeneration_changes)
            
            # 计算调整量
            time_adjustment = self._calculate_time_adjustment(original_commands, regenerated_commands)
            water_adjustment = self._calculate_water_adjustment(original_commands, regenerated_commands)
            
            result = BatchRegenerationResult(
                batch_index=batch_index,
                success=True,
                original_commands=original_commands,
                regenerated_commands=regenerated_commands,
                changes=changes,
                water_level_changes=water_level_changes,
                execution_time_adjustment=time_adjustment,
                total_water_adjustment=water_adjustment
            )
            
            logger.info(f"批次 {batch_index} 计划重新生成完成，共 {len(changes)} 项变更")
            
            return result
            
        except Exception as e:
            import traceback
            logger.error(f"重新生成批次 {batch_index} 计划失败: {e}")
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            
            return BatchRegenerationResult(
                batch_index=batch_index,
                success=False,
                original_commands=original_commands if 'original_commands' in locals() else [],
                regenerated_commands=[],
                changes=[],
                water_level_changes={},
                error_message=str(e)
            )
    
    def _extract_batch_commands(self, plan: Dict[str, Any], batch_index: int) -> List[Dict[str, Any]]:
        """提取指定批次的命令"""
        commands = []
        
        try:
            # 从计划中提取批次相关的命令
            batches = plan.get("batches", [])
            steps = plan.get("steps", [])
            
            # 找到对应批次
            target_batch = None
            for batch in batches:
                if batch.get("index") == batch_index:
                    target_batch = batch
                    break
            
            if target_batch:
                # 提取批次中的田块和命令
                field_plots = target_batch.get("field_plots", [])
                
                for field_plot in field_plots:
                    field_id = field_plot.get("id")
                    commands_list = field_plot.get("commands", [])
                    
                    for cmd in commands_list:
                        command = {
                            "field_id": field_id,
                            "batch_index": batch_index,
                            "command_type": cmd.get("type", "irrigation"),
                            "duration_minutes": cmd.get("duration_minutes", 0),
                            "flow_rate_lps": cmd.get("flow_rate_lps", 0),
                            "water_amount_m3": cmd.get("water_amount_m3", 0),
                            "start_time_h": cmd.get("start_time_h", 0),
                            "end_time_h": cmd.get("end_time_h", 0),
                            "original_data": cmd
                        }
                        commands.append(command)
            
            logger.debug(f"从批次 {batch_index} 提取了 {len(commands)} 个命令")
            
        except Exception as e:
            logger.error(f"提取批次命令失败: {e}")
        
        return commands
    
    def _analyze_water_level_changes(self, 
                                   commands: List[Dict[str, Any]], 
                                   new_water_levels: Dict[str, WaterLevelReading]) -> Dict[str, Tuple[float, float]]:
        """分析水位变化"""
        changes = {}
        
        for command in commands:
            field_id = str(command.get("field_id", ""))
            
            if field_id in new_water_levels:
                new_level = new_water_levels[field_id].water_level_mm
                
                # 从田块配置获取原始水位（如果有的话）
                original_level = 0.0
                if field_id in self.field_configs:
                    field_config = self.field_configs[field_id]
                    if isinstance(field_config, dict):
                        original_level = field_config.get("wl_mm", 0.0)
                
                changes[field_id] = (original_level, new_level)
        
        return changes
    
    async def _regenerate_commands(self, 
                                 original_commands: List[Dict[str, Any]],
                                 new_water_levels: Dict[str, WaterLevelReading],
                                 water_level_changes: Dict[str, Tuple[float, float]]) -> List[Dict[str, Any]]:
        """重新生成命令"""
        regenerated_commands = []
        
        logger.debug(f"开始重新生成命令，原始命令数: {len(original_commands)}")
        
        for i, command in enumerate(original_commands):
            logger.debug(f"处理命令 {i}: {command}")
            field_id = str(command.get("field_id", ""))
            
            # 复制原始命令
            new_command = command.copy()
            
            # 如果有新的水位数据，调整灌溉参数
            if field_id in new_water_levels and field_id in water_level_changes:
                old_level, new_level = water_level_changes[field_id]
                level_diff = new_level - old_level
                
                # 根据水位差异调整灌溉参数
                adjustment_factor = self._calculate_adjustment_factor(level_diff)
                
                # 调整持续时间
                original_duration = command.get("duration_minutes", 0)
                new_duration = max(
                    self.regeneration_rules["min_irrigation_duration_minutes"],
                    min(
                        self.regeneration_rules["max_irrigation_duration_minutes"],
                        original_duration * adjustment_factor
                    )
                )
                new_command["duration_minutes"] = new_duration
                
                # 调整流量（如果启用）
                if self.regeneration_rules["enable_flow_optimization"]:
                    original_flow = command.get("flow_rate_lps", 0)
                    flow_adjustment = min(
                        self.regeneration_rules["max_flow_rate_adjustment_ratio"],
                        abs(level_diff) / 100  # 基于水位差异调整流量
                    )
                    
                    if level_diff < 0:  # 水位下降，增加流量
                        new_flow = original_flow * (1 + flow_adjustment)
                    else:  # 水位上升，减少流量
                        new_flow = original_flow * (1 - flow_adjustment)
                    
                    new_command["flow_rate_lps"] = max(0.1, new_flow)
                
                # 重新计算用水量
                new_water_amount = (new_command["duration_minutes"] / 60) * new_command["flow_rate_lps"] / 1000
                new_command["water_amount_m3"] = new_water_amount
                
                # 更新时间（如果启用时间优化）
                if self.regeneration_rules["enable_timing_optimization"]:
                    # 这里可以添加更复杂的时间优化逻辑
                    pass
            
            regenerated_commands.append(new_command)
            logger.debug(f"添加重新生成的命令 {i}: {new_command}")
        
        logger.debug(f"重新生成完成，命令数: {len(regenerated_commands)}")
        return regenerated_commands
    
    def _calculate_adjustment_factor(self, level_diff_mm: float) -> float:
        """计算调整因子"""
        threshold = self.regeneration_rules["water_level_threshold_mm"]
        target_level = self.regeneration_rules["water_level_target_mm"]
        
        if abs(level_diff_mm) < threshold:
            return 1.0  # 变化不大，不调整
        
        # 基于水位差异计算调整因子
        if level_diff_mm < -threshold:  # 水位下降较多
            # 需要增加灌溉
            adjustment = 1 + min(0.5, abs(level_diff_mm) / target_level)
        elif level_diff_mm > threshold:  # 水位上升较多
            # 需要减少灌溉
            adjustment = 1 - min(0.3, level_diff_mm / target_level)
        else:
            adjustment = 1.0
        
        # 限制调整范围
        max_adjustment = self.regeneration_rules["max_duration_adjustment_ratio"]
        return max(1 - max_adjustment, min(1 + max_adjustment, adjustment))
    
    def _analyze_plan_changes(self, 
                            original_commands: List[Dict[str, Any]], 
                            regenerated_commands: List[Dict[str, Any]]) -> List[PlanChange]:
        """分析计划变更"""
        changes = []
        
        for i, (orig_cmd, new_cmd) in enumerate(zip(original_commands, regenerated_commands)):
            field_id = str(orig_cmd.get("field_id", ""))
            batch_index = orig_cmd.get("batch_index", 0)
            
            # 检查持续时间变化
            orig_duration = orig_cmd.get("duration_minutes", 0)
            new_duration = new_cmd.get("duration_minutes", 0)
            
            if abs(orig_duration - new_duration) > 1:  # 超过1分钟的变化
                impact = self._assess_change_impact(abs(orig_duration - new_duration) / orig_duration if orig_duration > 0 else 0)
                
                change = PlanChange(
                    change_type=PlanChangeType.DURATION_ADJUSTED,
                    impact_level=impact,
                    field_id=field_id,
                    batch_index=batch_index,
                    old_value=orig_duration,
                    new_value=new_duration,
                    reason=f"基于水位变化调整灌溉持续时间"
                )
                changes.append(change)
            
            # 检查流量变化
            orig_flow = orig_cmd.get("flow_rate_lps", 0)
            new_flow = new_cmd.get("flow_rate_lps", 0)
            
            if abs(orig_flow - new_flow) > 0.1:  # 超过0.1L/s的变化
                impact = self._assess_change_impact(abs(orig_flow - new_flow) / orig_flow if orig_flow > 0 else 0)
                
                change = PlanChange(
                    change_type=PlanChangeType.FLOW_RATE_ADJUSTED,
                    impact_level=impact,
                    field_id=field_id,
                    batch_index=batch_index,
                    old_value=orig_flow,
                    new_value=new_flow,
                    reason=f"基于水位变化调整流量"
                )
                changes.append(change)
        
        return changes
    
    def _assess_change_impact(self, change_ratio: float) -> PlanChangeImpact:
        """评估变更影响级别"""
        if change_ratio < 0.1:
            return PlanChangeImpact.MINIMAL
        elif change_ratio < 0.3:
            return PlanChangeImpact.MODERATE
        elif change_ratio < 0.5:
            return PlanChangeImpact.SIGNIFICANT
        else:
            return PlanChangeImpact.CRITICAL
    
    def _calculate_time_adjustment(self, 
                                 original_commands: List[Dict[str, Any]], 
                                 regenerated_commands: List[Dict[str, Any]]) -> float:
        """计算总执行时间调整（秒）"""
        orig_total_minutes = sum(cmd.get("duration_minutes", 0) for cmd in original_commands)
        new_total_minutes = sum(cmd.get("duration_minutes", 0) for cmd in regenerated_commands)
        
        return (new_total_minutes - orig_total_minutes) * 60  # 转换为秒
    
    def _calculate_water_adjustment(self, 
                                  original_commands: List[Dict[str, Any]], 
                                  regenerated_commands: List[Dict[str, Any]]) -> float:
        """计算总用水量调整（立方米）"""
        orig_total_water = sum(cmd.get("water_amount_m3", 0) for cmd in original_commands)
        new_total_water = sum(cmd.get("water_amount_m3", 0) for cmd in regenerated_commands)
        
        return new_total_water - orig_total_water
    
    def validate_regenerated_plan(self, result: BatchRegenerationResult) -> bool:
        """验证重新生成的计划"""
        try:
            # 检查基本有效性
            if not result.success or not result.regenerated_commands:
                return False
            
            # 检查命令完整性
            for command in result.regenerated_commands:
                if not self._validate_command(command):
                    return False
            
            # 检查调整是否在合理范围内
            if abs(result.execution_time_adjustment) > 3600:  # 超过1小时
                logger.warning(f"批次 {result.batch_index} 执行时间调整过大: {result.execution_time_adjustment}秒")
                return False
            
            if abs(result.total_water_adjustment) > 100:  # 超过100立方米
                logger.warning(f"批次 {result.batch_index} 用水量调整过大: {result.total_water_adjustment}m³")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"验证重新生成计划失败: {e}")
            return False
    
    def _validate_command(self, command: Dict[str, Any]) -> bool:
        """验证单个命令"""
        try:
            # 检查必要字段
            required_fields = ["field_id", "duration_minutes", "flow_rate_lps"]
            for field in required_fields:
                if field not in command or command[field] is None:
                    return False
            
            # 检查数值范围
            duration = command.get("duration_minutes", 0)
            if duration < 0 or duration > self.regeneration_rules["max_irrigation_duration_minutes"]:
                return False
            
            flow_rate = command.get("flow_rate_lps", 0)
            if flow_rate < 0 or flow_rate > 100:  # 假设最大流量100L/s
                return False
            
            return True
            
        except Exception:
            return False
    
    def get_regeneration_summary(self, result: BatchRegenerationResult) -> str:
        """获取重新生成摘要"""
        if not result.success:
            return f"批次 {result.batch_index} 重新生成失败: {result.error_message}"
        
        summary_parts = []
        
        # 基本信息
        summary_parts.append(f"批次 {result.batch_index} 重新生成完成")
        
        # 变更统计
        if result.changes:
            change_counts = {}
            for change in result.changes:
                change_type = change.change_type.value
                change_counts[change_type] = change_counts.get(change_type, 0) + 1
            
            change_desc = ", ".join([f"{k}: {v}" for k, v in change_counts.items()])
            summary_parts.append(f"变更: {change_desc}")
        
        # 时间调整
        if abs(result.execution_time_adjustment) > 60:
            time_adj_min = result.execution_time_adjustment / 60
            summary_parts.append(f"执行时间调整: {time_adj_min:.1f}分钟")
        
        # 用水量调整
        if abs(result.total_water_adjustment) > 0.1:
            summary_parts.append(f"用水量调整: {result.total_water_adjustment:.2f}m³")
        
        return "; ".join(summary_parts)

    def _build_field_to_valve_mapping(self, batch_fields: List[Dict[str, Any]]) -> Dict[str, str]:
        """构建田块ID到阀门ID的映射"""
        field_to_valve = {}
        for field in batch_fields:
            field_id = field.get("id")
            inlet_g_id = field.get("inlet_G_id")
            if field_id and inlet_g_id:
                field_to_valve[field_id] = inlet_g_id
        
        logger.info(f"构建田块到阀门映射: {field_to_valve}")
        print(f"[DEBUG] 构建田块到阀门映射: {field_to_valve}")
        return field_to_valve

    async def _regenerate_commands(self, 
                                 original_commands: List[Dict[str, Any]],
                                 new_water_levels: Dict[str, WaterLevelReading],
                                 water_level_changes: Dict[str, Tuple[float, float]],
                                 batch_fields: Optional[List[Dict[str, Any]]] = None,
                                 execution_context: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], List[PlanChange]]:
        """重新生成命令"""
        regenerated_commands = []
        changes = []
        
        # 构建田块到阀门的映射
        field_to_valve = {}
        if batch_fields:
            field_to_valve = self._build_field_to_valve_mapping(batch_fields)
        
        # 构建阀门到田块的反向映射（一个阀门可能控制多个田块）
        valve_to_fields = {}
        for field_id, valve_id in field_to_valve.items():
            if valve_id not in valve_to_fields:
                valve_to_fields[valve_id] = []
            valve_to_fields[valve_id].append(field_id)
        
        print(f"[DEBUG] 阀门到田块映射: {valve_to_fields}")
        
        # 处理每个命令
        for cmd in original_commands:
            cmd_type = cmd.get("type")
            target = cmd.get("target")
            
            # 检查是否是阀门控制命令
            if cmd_type == "set" and target in valve_to_fields:
                # 这是一个需要调整的阀门命令
                controlled_fields = valve_to_fields[target]
                
                # 检查控制的田块是否有水位变化
                needs_adjustment = False
                total_water_change = 0.0
                affected_fields = []
                
                for field_id in controlled_fields:
                    if field_id in water_level_changes:
                        old_wl, new_wl = water_level_changes[field_id]
                        water_deficit = max(0, self.regeneration_rules["water_level_target_mm"] - new_wl)
                        total_water_change += water_deficit
                        affected_fields.append(field_id)
                        needs_adjustment = True
                
                if needs_adjustment:
                    # 调整阀门命令
                    new_cmd, field_changes = await self._adjust_valve_command(
                        cmd, affected_fields, water_level_changes, execution_context
                    )
                    regenerated_commands.append(new_cmd)
                    changes.extend(field_changes)
                    print(f"[DEBUG] 调整阀门 {target} 命令，影响田块: {affected_fields}")
                else:
                    # 保持原命令不变
                    regenerated_commands.append(copy.deepcopy(cmd))
            else:
                # 保持原命令不变（泵控制命令等）
                regenerated_commands.append(copy.deepcopy(cmd))
        
        return regenerated_commands, changes
    
    async def _adjust_valve_command(self, 
                                  original_cmd: Dict[str, Any],
                                  affected_fields: List[str],
                                  water_level_changes: Dict[str, Tuple[float, float]],
                                  execution_context: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], List[PlanChange]]:
        """调整阀门命令"""
        new_cmd = copy.deepcopy(original_cmd)
        changes = []
        
        target_valve = original_cmd.get("target")
        original_duration = original_cmd.get("duration_minutes", 0)
        
        # 计算需要的额外灌溉时间
        total_water_deficit = 0.0
        field_details = []
        
        for field_id in affected_fields:
            if field_id in water_level_changes:
                old_wl, new_wl = water_level_changes[field_id]
                target_wl = self.regeneration_rules["water_level_target_mm"]
                water_deficit = max(0, target_wl - new_wl)
                total_water_deficit += water_deficit
                field_details.append(f"{field_id}({old_wl:.1f}->{new_wl:.1f}mm,缺水{water_deficit:.1f}mm)")
        
        # 根据缺水量调整灌溉时间
        # 简化计算：假设每分钟灌溉可以提供1mm水位
        additional_minutes = min(total_water_deficit, 60)  # 最多增加60分钟
        new_duration = original_duration + additional_minutes
        
        # 限制最大灌溉时间
        max_duration = self.regeneration_rules.get("max_irrigation_duration_minutes", 120)
        new_duration = min(new_duration, max_duration)
        
        if new_duration != original_duration:
            new_cmd["duration_minutes"] = new_duration
            
            change = PlanChange(
                change_type="command_adjustment",
                description=f"调整阀门 {target_valve} 灌溉时间从 {original_duration}分钟 到 {new_duration}分钟",
                details={
                    "valve_id": target_valve,
                    "original_duration_minutes": original_duration,
                    "new_duration_minutes": new_duration,
                    "affected_fields": affected_fields,
                    "field_details": field_details,
                    "total_water_deficit_mm": total_water_deficit
                }
            )
            changes.append(change)
            
            print(f"[DEBUG] 阀门 {target_valve}: {original_duration}min -> {new_duration}min, 影响田块: {field_details}")
        
        return new_cmd, changes
    
    async def _regenerate_field_command(self, 
                                      original_cmd: Dict[str, Any],
                                      new_water_level: WaterLevelReading,
                                      water_level_change: Tuple[float, float],
                                      execution_context: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], List[PlanChange]]:
        """重新生成单个田块的命令"""
        field_id = original_cmd.get("sectionID")
        old_wl, new_wl = water_level_change
        
        # 复制原命令
        new_cmd = copy.deepcopy(original_cmd)
        changes = []
        
        # 更新水位
        new_cmd["waterlevel_mm"] = new_wl
        
        # 获取田块配置
        field_config = self.field_configs.get(field_id, {})
        
        # 计算新的灌溉参数
        irrigation_params = self._calculate_irrigation_parameters(
            field_id, new_wl, field_config, execution_context
        )
        
        # 调整持续时间
        if "duration_minutes" in original_cmd:
            old_duration = original_cmd["duration_minutes"]
            new_duration = irrigation_params.get("duration_minutes", old_duration)
            
            if abs(new_duration - old_duration) > 0.5:  # 超过0.5分钟的变化
                new_cmd["duration_minutes"] = new_duration
                changes.append(PlanChange(
                    change_type=PlanChangeType.DURATION_ADJUSTED,
                    impact_level=self._assess_impact_level(abs(new_duration - old_duration) / old_duration),
                    field_id=field_id,
                    batch_index=original_cmd.get("batch", 0),
                    old_value=old_duration,
                    new_value=new_duration,
                    reason=f"水位从 {old_wl:.1f}mm 变化到 {new_wl:.1f}mm",
                    metadata={"water_level_change": water_level_change}
                ))
        
        # 调整流量
        if "flow_rate" in original_cmd:
            old_flow = original_cmd["flow_rate"]
            new_flow = irrigation_params.get("flow_rate", old_flow)
            
            if abs(new_flow - old_flow) > 0.01:  # 超过0.01的变化
                new_cmd["flow_rate"] = new_flow
                changes.append(PlanChange(
                    change_type=PlanChangeType.FLOW_RATE_ADJUSTED,
                    impact_level=self._assess_impact_level(abs(new_flow - old_flow) / old_flow),
                    field_id=field_id,
                    batch_index=original_cmd.get("batch", 0),
                    old_value=old_flow,
                    new_value=new_flow,
                    reason=f"基于新水位 {new_wl:.1f}mm 优化流量",
                    metadata={"water_level_change": water_level_change}
                ))
        
        # 检查是否需要取消灌溉
        target_wl = self.regeneration_rules.get("water_level_target_mm", 50)
        tolerance = self.regeneration_rules.get("water_level_tolerance_mm", 5)
        
        if new_wl >= (target_wl + tolerance):
            # 水位已经足够，取消灌溉
            new_cmd["action"] = "skip"
            new_cmd["skip_reason"] = f"水位 {new_wl:.1f}mm 已达到目标水位 {target_wl}mm"
            
            changes.append(PlanChange(
                change_type=PlanChangeType.CANCELLED,
                impact_level=PlanChangeImpact.SIGNIFICANT,
                field_id=field_id,
                batch_index=original_cmd.get("batch", 0),
                old_value="execute",
                new_value="skip",
                reason=f"水位 {new_wl:.1f}mm 已达到目标",
                metadata={"target_water_level": target_wl, "tolerance": tolerance}
            ))
        
        return new_cmd, changes
    
    def _calculate_irrigation_parameters(self, 
                                       field_id: str, 
                                       current_wl: float, 
                                       field_config: Dict[str, Any],
                                       execution_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """计算灌溉参数"""
        target_wl = self.regeneration_rules.get("water_level_target_mm", 50)
        
        # 计算需要补充的水量
        water_deficit = max(0, target_wl - current_wl)
        
        # 获取田块面积
        area_ha = field_config.get("area_ha", 1.0)
        
        # 计算所需水量（立方米）
        water_needed_m3 = water_deficit * area_ha * 10  # mm * ha * 10 = m3
        
        # 获取流量配置
        max_flow_rate = field_config.get("max_flow_rate", 50.0)  # L/s
        min_flow_rate = field_config.get("min_flow_rate", 10.0)  # L/s
        
        # 计算最优流量和持续时间
        if water_needed_m3 > 0:
            # 优先使用较高流量以缩短时间
            optimal_flow_rate = min(max_flow_rate, max(min_flow_rate, water_needed_m3 / 60))  # L/s
            duration_seconds = water_needed_m3 * 1000 / optimal_flow_rate  # 秒
            duration_minutes = duration_seconds / 60
            
            # 限制持续时间范围
            min_duration = self.regeneration_rules.get("min_irrigation_duration_minutes", 5)
            max_duration = self.regeneration_rules.get("max_irrigation_duration_minutes", 180)
            
            duration_minutes = max(min_duration, min(max_duration, duration_minutes))
            
            # 根据调整后的持续时间重新计算流量
            optimal_flow_rate = water_needed_m3 * 1000 / (duration_minutes * 60)
        else:
            optimal_flow_rate = min_flow_rate
            duration_minutes = 0
        
        return {
            "duration_minutes": duration_minutes,
            "flow_rate": optimal_flow_rate,
            "water_needed_m3": water_needed_m3,
            "water_deficit_mm": water_deficit
        }
    
    def _assess_impact_level(self, change_ratio: float) -> PlanChangeImpact:
        """评估变更影响级别"""
        if change_ratio < 0.1:
            return PlanChangeImpact.MINIMAL
        elif change_ratio < 0.25:
            return PlanChangeImpact.MODERATE
        elif change_ratio < 0.5:
            return PlanChangeImpact.SIGNIFICANT
        else:
            return PlanChangeImpact.CRITICAL
    
    def _calculate_time_adjustment(self, 
                                 original_commands: List[Dict[str, Any]], 
                                 regenerated_commands: List[Dict[str, Any]]) -> float:
        """计算执行时间调整"""
        original_time = sum(cmd.get("duration_minutes", 0) for cmd in original_commands)
        regenerated_time = sum(cmd.get("duration_minutes", 0) for cmd in regenerated_commands)
        
        return (regenerated_time - original_time) * 60  # 转换为秒
    
    def _calculate_water_adjustment(self, 
                                  original_commands: List[Dict[str, Any]], 
                                  regenerated_commands: List[Dict[str, Any]]) -> float:
        """计算用水量调整"""
        def calculate_water_usage(commands):
            total = 0
            for cmd in commands:
                duration_min = cmd.get("duration_minutes", 0)
                flow_rate_ls = cmd.get("flow_rate", 0)
                total += duration_min * flow_rate_ls * 60 / 1000  # 转换为立方米
            return total
        
        original_water = calculate_water_usage(original_commands)
        regenerated_water = calculate_water_usage(regenerated_commands)
        
        return regenerated_water - original_water
    
    def generate_change_summary(self, changes: List[PlanChange]) -> Dict[str, Any]:
        """生成变更摘要"""
        if not changes:
            return {"total_changes": 0, "summary": "无变更"}
        
        # 按类型统计
        change_counts = {}
        impact_counts = {}
        
        for change in changes:
            change_type = change.change_type.value
            impact_level = change.impact_level.value
            
            change_counts[change_type] = change_counts.get(change_type, 0) + 1
            impact_counts[impact_level] = impact_counts.get(impact_level, 0) + 1
        
        # 生成摘要文本
        summary_parts = []
        for change_type, count in change_counts.items():
            if change_type == "duration_adjusted":
                summary_parts.append(f"{count}个田块调整了灌溉时间")
            elif change_type == "flow_rate_adjusted":
                summary_parts.append(f"{count}个田块调整了流量")
            elif change_type == "cancelled":
                summary_parts.append(f"{count}个田块取消了灌溉")
            else:
                summary_parts.append(f"{count}个{change_type}变更")
        
        return {
            "total_changes": len(changes),
            "change_types": change_counts,
            "impact_levels": impact_counts,
            "summary": "；".join(summary_parts),
            "critical_changes": len([c for c in changes if c.impact_level == PlanChangeImpact.CRITICAL]),
            "fields_affected": len(set(c.field_id for c in changes))
        }
    
    async def validate_regenerated_plan(self, 
                                      regenerated_commands: List[Dict[str, Any]],
                                      execution_context: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str]]:
        """验证重新生成的计划"""
        errors = []
        
        # 检查命令完整性
        for i, cmd in enumerate(regenerated_commands):
            if not cmd.get("sectionID"):
                errors.append(f"命令 {i} 缺少田块ID")
            
            if cmd.get("action") != "skip":
                if not cmd.get("duration_minutes") or cmd["duration_minutes"] <= 0:
                    errors.append(f"命令 {i} 持续时间无效")
                
                if not cmd.get("flow_rate") or cmd["flow_rate"] <= 0:
                    errors.append(f"命令 {i} 流量无效")
        
        # 检查资源冲突
        pump_usage = {}
        for cmd in regenerated_commands:
            if cmd.get("action") == "skip":
                continue
                
            pump_id = cmd.get("pumpID")
            start_time = cmd.get("start_time", 0)
            duration = cmd.get("duration_minutes", 0)
            end_time = start_time + duration
            
            if pump_id:
                if pump_id not in pump_usage:
                    pump_usage[pump_id] = []
                
                # 检查时间冲突
                for existing_start, existing_end in pump_usage[pump_id]:
                    if not (end_time <= existing_start or start_time >= existing_end):
                        errors.append(f"泵 {pump_id} 在时间 {start_time}-{end_time} 与 {existing_start}-{existing_end} 冲突")
                
                pump_usage[pump_id].append((start_time, end_time))
        
        return len(errors) == 0, errors

if __name__ == "__main__":
    # 示例用法
    import asyncio
    from dynamic_waterlevel_manager import WaterLevelReading, WaterLevelSource, WaterLevelQuality
    
    async def main():
        # 创建计划重新生成器
        regenerator = DynamicPlanRegenerator(
            config_path="config.json",
            plan_template_path="irrigation_plan_template.json"
        )
        
        # 模拟原始计划
        original_plan = {
            "commands": [
                {
                    "batch": 1,
                    "sectionID": "23",
                    "pumpID": "pump1",
                    "action": "start",
                    "duration_minutes": 30,
                    "flow_rate": 25.0,
                    "waterlevel_mm": 20.0,
                    "start_time": 0
                }
            ]
        }
        
        # 模拟新的水位数据
        new_water_levels = {
            "23": WaterLevelReading(
                field_id="23",
                water_level_mm=35.0,  # 水位上升了15mm
                timestamp=datetime.now(),
                source=WaterLevelSource.API,
                quality=WaterLevelQuality.EXCELLENT
            )
        }
        
        # 重新生成批次计划
        result = await regenerator.regenerate_batch(
            batch_index=1,
            original_plan=original_plan,
            new_water_levels=new_water_levels
        )
        
        if result.success:
            print(f"批次 {result.batch_index} 重新生成成功")
            print(f"变更数量: {len(result.changes)}")
            print(f"执行时间调整: {result.execution_time_adjustment:.1f} 秒")
            print(f"用水量调整: {result.total_water_adjustment:.2f} 立方米")
            
            # 显示变更详情
            summary = regenerator.generate_change_summary(result.changes)
            print(f"变更摘要: {summary['summary']}")
        else:
            print(f"重新生成失败: {result.error_message}")
    
    # 运行示例
    asyncio.run(main())