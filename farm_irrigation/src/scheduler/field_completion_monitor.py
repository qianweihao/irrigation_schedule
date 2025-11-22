#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
田块完成度监控器 - 水位达标后的设备关闭算法

功能优先级：
- P0: 田块水位监控和进水阀关闭
- P1: 支渠节制闸关闭逻辑
- P2: 泵站停止逻辑

设计原则：
- 参考批次划分逻辑（farm_irr_full_device_modified.py）
- 节制闸只有开/关（0%/100%），不调整开度
- 三级联动：田块 → 节制闸 → 泵站
- 监控器只负责判断逻辑和标记，不直接调用硬件API
- 实际硬件控制通过指令队列交给硬件团队执行
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FieldStatus:
    """田块状态"""
    field_id: str              # 如 "S3-G2-F1"
    segment_id: str            # 如 "S3" (基段ID)
    gate_seq: int              # 闸号，如从 "S3-G2" 提取 2
    current_wl: float          # 当前水位 (mm)
    wl_opt: float             # 目标水位 (mm)
    wl_high: float            # 高水位阈值 (mm)
    status: str               # "irrigating" | "completed" | "overflow"
    inlet_device: str         # 进水阀 unique_no
    outlet_device: Optional[str] = None  # 出水阀 unique_no (可选)
    completion_time: Optional[datetime] = None


@dataclass
class RegulatorInfo:
    """节制闸信息"""
    reg_id: str               # 如 "S3-G2"
    gate_type: str            # "main-g" | "branch-g" | "regulator"
    gate_seq: int             # 闸号序列
    segment_id: str           # 所属段
    unique_no: Optional[str] = None  # 设备 unique_no
    status: str = "open"      # "open" | "closed"


class FieldCompletionMonitor:
    """田块完成度监控器 - 水位达标后关闭设备"""
    
    def __init__(self, 
                 config_data: Dict,
                 app_id: str,
                 secret: str,
                 check_interval: int = 30):
        """
        初始化监控器
        
        Args:
            config_data: 配置数据（包含 segments、gates 等）
            app_id: iLand 平台应用ID
            secret: iLand 平台密钥
            check_interval: 检查间隔（秒）
        """
        self.config_data = config_data
        self.app_id = app_id
        self.secret = secret
        self.check_interval = check_interval
        
        # 田块状态
        self.active_fields: Dict[str, FieldStatus] = {}
        
        # 节制闸状态（使用 active_regulators 保持与调用方一致）
        self.active_regulators: Dict[str, RegulatorInfo] = {}
        
        # 泵站状态
        self.active_pumps: Set[str] = set()
        
        # 统计
        self.total_closures = 0
        self.total_field_completions = 0
    
    def update_water_levels(self, water_levels: Dict[str, float]):
        """
        更新田块水位数据（用于人工调整）
        
        Args:
            water_levels: 田块ID到水位(mm)的映射
        """
        for field_id, wl_mm in water_levels.items():
            if field_id in self.active_fields:
                self.active_fields[field_id].current_wl = wl_mm
                logger.info(f"更新 {field_id} 水位: {wl_mm:.1f}mm")
    
    def initialize_batch(self, 
                         batch_fields: List[Dict],
                         batch_regulators: List[Dict],
                         batch_pumps: List[str]):
        """
        初始化批次监控
        
        Args:
            batch_fields: 批次田块列表，格式：
                [{
                    'id': 'S3-G2-F1',
                    'segment_id': 'S3',
                    'inlet_gid': 'S3-G2',
                    'wl_mm': 25.0,
                    'wl_opt': 50.0,
                    'wl_high': 80.0,
                    'inlet_unique_no': '477379421064159253',
                    'outlet_unique_no': '471743004049787907'  # 可选
                }]
            batch_regulators: 批次节制闸列表，格式：
                [{
                    'id': 'S3-G2',
                    'type': 'branch-g',
                    'segment_id': 'S3',
                    'unique_no': '477379421064159255',
                    'open_pct': 100
                }]
            batch_pumps: 批次水泵列表，如 ['P1', 'P2']
        """
        logger.info(f"初始化批次监控: {len(batch_fields)} 个田块, {len(batch_regulators)} 个节制闸, {len(batch_pumps)} 个泵站")
        
        # 初始化田块状态
        self.active_fields.clear()
        for field in batch_fields:
            gate_seq = self._extract_gate_seq(field.get('inlet_gid', ''))
            
            self.active_fields[field['id']] = FieldStatus(
                field_id=field['id'],
                segment_id=self._extract_base_segment(field.get('segment_id', '')),
                gate_seq=gate_seq,
                current_wl=field.get('wl_mm', 0.0),
                wl_opt=field.get('wl_opt', 50.0),
                wl_high=field.get('wl_high', 80.0),
                status='irrigating',
                inlet_device=field.get('inlet_unique_no', ''),
                outlet_device=field.get('outlet_unique_no')
            )
        
        # 初始化节制闸状态（只记录开启的节制闸）
        self.active_regulators.clear()
        for reg in batch_regulators:
            if reg.get('open_pct', 0) > 0:  # 只监控开启的节制闸
                gate_seq = self._extract_gate_seq(reg['id'])
                self.active_regulators[reg['id']] = RegulatorInfo(
                    reg_id=reg['id'],
                    gate_type=reg.get('type', 'branch-g'),
                    gate_seq=gate_seq,
                    segment_id=reg.get('segment_id', ''),
                    unique_no=reg.get('unique_no'),
                    status='open'
                )
        
        # 初始化泵站状态
        self.active_pumps = set(batch_pumps)
        
        logger.info(f"✅ 监控初始化完成")
    
    async def check_and_close_devices(self, latest_waterlevels: Dict[str, float]) -> Dict[str, any]:
        """
        检查水位并关闭达标设备（核心监控循环）
        
        Args:
            latest_waterlevels: 最新水位数据 {field_id: wl_mm}
        
        Returns:
            Dict: 执行结果统计
                {
                    'completed_fields': List[str],
                    'closed_regulators': List[str],
                    'stopped_pumps': List[str],
                    'all_completed': bool
                }
        """
        logger.info("=" * 60)
        logger.info("开始检查水位和设备状态")
        logger.info("=" * 60)
        
        result = {
            'completed_fields': [],
            'closed_regulators': [],
            'stopped_pumps': [],
            'all_completed': False
        }
        
        # P0: 检查田块水位，关闭达标田块的进水阀
        completed_fields = await self._check_field_completion(latest_waterlevels)
        result['completed_fields'] = completed_fields
        
        if completed_fields:
            # P1: 检查节制闸是否应该关闭
            closed_regulators = await self._check_regulator_closure()
            result['closed_regulators'] = closed_regulators
            
            # P2: 检查泵站是否应该停止
            if closed_regulators or self._all_fields_completed():
                stopped_pumps = await self._check_pump_station_closure()
                result['stopped_pumps'] = stopped_pumps
                result['all_completed'] = len(stopped_pumps) > 0
        
        logger.info("=" * 60)
        logger.info(f"检查完成: 田块完成 {len(completed_fields)}, 节制闸关闭 {len(result['closed_regulators'])}, 泵站停止 {len(result['stopped_pumps'])}")
        logger.info("=" * 60)
        
        return result
    
    # ============ P0: 田块水位监控和进水阀关闭 ============
    
    async def _check_field_completion(self, latest_waterlevels: Dict[str, float]) -> List[str]:
        """
        P0: 检查田块是否达标，关闭进水阀
        
        Returns:
            List[str]: 本次完成的田块ID列表
        """
        completed_fields = []
        
        for field_id, field_status in self.active_fields.items():
            # 跳过已完成的田块
            if field_status.status in ["completed", "overflow"]:
                continue
            
            # 获取最新水位
            current_wl = latest_waterlevels.get(field_id)
            if current_wl is None:
                logger.debug(f"田块 {field_id} 无水位数据，跳过")
                continue
            
            field_status.current_wl = current_wl
            
            # 判断1: 水位达标 (wl_opt <= current_wl <= wl_high)
            if field_status.wl_opt <= current_wl <= field_status.wl_high:
                logger.info(f"✅ 田块 {field_id} 水位达标: {current_wl:.1f}mm (目标: {field_status.wl_opt}mm)")
                
                # 关闭进水阀
                await self._close_inlet_gate(field_status)
                
                # 标记完成
                field_status.status = "completed"
                field_status.completion_time = datetime.now()
                completed_fields.append(field_id)
                self.total_field_completions += 1
            
            # 判断2: 水位过高 (current_wl > wl_high) - 紧急排水
            elif current_wl > field_status.wl_high:
                logger.warning(f"🚨 田块 {field_id} 水位过高: {current_wl:.1f}mm > {field_status.wl_high}mm，紧急排水")
                
                # 关闭进水阀
                await self._close_inlet_gate(field_status)
                
                # 开启出水阀紧急排水
                if field_status.outlet_device:
                    await self._open_outlet_for_emergency(field_status)
                
                field_status.status = "overflow"
            
            # 判断3: 灌溉中
            else:
                progress = (current_wl / field_status.wl_opt) * 100
                logger.debug(f"🔄 田块 {field_id} 灌溉中: {current_wl:.1f}/{field_status.wl_opt}mm ({progress:.0f}%)")
        
        if completed_fields:
            logger.info(f"本轮完成田块数: {len(completed_fields)}")
        
        return completed_fields
    
    async def _close_inlet_gate(self, field_status: FieldStatus):
        """
        记录需要关闭的田块进水阀
        注意：不实际调用硬件API，只记录日志，由后续生成指令
        """
        logger.info(f"  └─ 标记关闭进水阀: {field_status.field_id}")
        self.total_closures += 1
    
    async def _open_outlet_for_emergency(self, field_status: FieldStatus):
        """
        记录需要紧急排水的田块（全开出水阀）
        注意：不实际调用硬件API，只记录日志，由后续生成指令
        """
        logger.info(f"  └─ 标记紧急排水(100%): {field_status.field_id}")
    
    # ============ P1: 支渠节制闸关闭逻辑 ============
    
    async def _check_regulator_closure(self) -> List[str]:
        """
        P1: 检查节制闸是否应该关闭
        
        参考批次划分逻辑：
        - 主渠节制闸 (main-g): 若"其它支渠"所有田块都达标或闸号 > k → 关闭
        - 支渠节制闸 (branch-g/regulator): 若"本支渠"所有田块都达标或闸号 < k → 关闭
        
        Returns:
            List[str]: 本次关闭的节制闸ID列表
        """
        closed_regulators = []
        
        # 按支渠分组田块
        segment_fields = self._group_fields_by_segment()
        
        for reg_id, reg_info in self.active_regulators.items():
            # 跳过已关闭的节制闸
            if reg_info.status == "closed":
                continue
            
            should_close = False
            
            if reg_info.gate_type.lower() == "main-g":
                # 主渠节制闸：检查"其它支渠"的所有田块
                other_seg_fields = [
                    f for seg_id, fields in segment_fields.items()
                    if seg_id != reg_info.segment_id
                    for f in fields
                ]
                
                if not other_seg_fields:
                    should_close = True
                else:
                    # 所有其它支渠田块已完成，或所有闸号 > 本节制闸号
                    all_completed = all(f.status == "completed" for f in other_seg_fields)
                    all_higher = all(f.gate_seq > reg_info.gate_seq for f in other_seg_fields)
                    should_close = all_completed or all_higher
            
            else:  # branch-g / regulator
                # 支渠节制闸：检查"本支渠"的所有田块
                same_seg_fields = segment_fields.get(reg_info.segment_id, [])
                
                if not same_seg_fields:
                    should_close = True
                else:
                    # 本支渠所有田块已完成，或所有闸号 < 本节制闸号
                    all_completed = all(f.status == "completed" for f in same_seg_fields)
                    all_lower = all(f.gate_seq < reg_info.gate_seq for f in same_seg_fields)
                    should_close = all_completed or all_lower
            
            # 执行关闭
            if should_close:
                await self._close_regulator(reg_info)
                reg_info.status = "closed"
                closed_regulators.append(reg_id)
        
        if closed_regulators:
            logger.info(f"✅ 本轮关闭节制闸: {', '.join(closed_regulators)}")
        
        return closed_regulators
    
    async def _close_regulator(self, reg_info: RegulatorInfo):
        """
        记录需要关闭的节制闸
        注意：不实际调用硬件API，只记录日志，由后续生成指令
        """
        if not reg_info.unique_no:
            logger.warning(f"  └─ 节制闸 {reg_info.reg_id} 无 unique_no（配置中缺失）")
        
        logger.info(f"  └─ 标记关闭{reg_info.gate_type}节制闸: {reg_info.reg_id} (支渠{reg_info.segment_id})")
        self.total_closures += 1
    
    # ============ P2: 泵站停止逻辑 ============
    
    async def _check_pump_station_closure(self) -> List[str]:
        """
        P2: 检查泵站是否应该停止
        
        停止条件：
        1. 所有田块都已完成
        2. 或所有节制闸都已关闭
        
        Returns:
            List[str]: 本次停止的泵站ID列表
        """
        stopped_pumps = []
        
        # 检查是否所有田块都完成
        all_fields_completed = self._all_fields_completed()
        
        # 检查是否所有节制闸都关闭
        all_regulators_closed = all(
            reg.status == "closed"
            for reg in self.active_regulators.values()
        )
        
        if all_fields_completed or all_regulators_closed:
            reason = "所有田块已完成" if all_fields_completed else "所有节制闸已关闭"
            logger.info(f"✅ {reason}，准备停止泵站")
            
            # 停止所有泵站
            for pump_id in list(self.active_pumps):
                await self._stop_pump(pump_id)
                stopped_pumps.append(pump_id)
                self.active_pumps.remove(pump_id)
            
            if stopped_pumps:
                logger.info(f"🎉 批次灌溉完成！已停止泵站: {', '.join(stopped_pumps)}")
        
        return stopped_pumps
    
    async def _stop_pump(self, pump_id: str):
        """
        记录需要停止的泵站
        注意：不实际调用硬件API，只记录日志，由后续生成指令
        """
        logger.info(f"  └─ 标记停止泵站: {pump_id}")
        self.total_closures += 1
    
    # ============ 辅助方法 ============
    
    def _group_fields_by_segment(self) -> Dict[str, List[FieldStatus]]:
        """按支渠分组田块"""
        segment_fields = {}
        for field_status in self.active_fields.values():
            seg_id = field_status.segment_id
            if seg_id not in segment_fields:
                segment_fields[seg_id] = []
            segment_fields[seg_id].append(field_status)
        return segment_fields
    
    def _all_fields_completed(self) -> bool:
        """检查是否所有田块都已完成"""
        return all(
            f.status in ["completed", "overflow"]
            for f in self.active_fields.values()
        )
    
    def has_active_fields(self) -> bool:
        """是否还有活跃的田块"""
        return any(
            f.status == "irrigating"
            for f in self.active_fields.values()
        )
    
    @staticmethod
    def _extract_gate_seq(gate_id: str) -> int:
        """从闸门ID提取序号，如 "S3-G2" → 2"""
        if not gate_id:
            return 999999
        match = re.search(r'-G(\d+)', gate_id)
        return int(match.group(1)) if match else 999999
    
    @staticmethod
    def _extract_base_segment(segment_id: str) -> str:
        """提取基段ID，如 "S3" 或 "S3-G2" → "S3" """
        if not segment_id:
            return ""
        # 如果是 Sx-Gy 格式，提取 Sx
        if '-G' in segment_id:
            return segment_id.split('-G')[0]
        return segment_id
    
    def get_statistics(self) -> Dict[str, any]:
        """获取统计信息"""
        return {
            'total_fields': len(self.active_fields),
            'completed_fields': sum(1 for f in self.active_fields.values() if f.status == "completed"),
            'irrigating_fields': sum(1 for f in self.active_fields.values() if f.status == "irrigating"),
            'overflow_fields': sum(1 for f in self.active_fields.values() if f.status == "overflow"),
            'total_regulators': len(self.active_regulators),
            'closed_regulators': sum(1 for r in self.active_regulators.values() if r.status == "closed"),
            'active_pumps': len(self.active_pumps),
            'total_closures': self.total_closures,
            'total_completions': self.total_field_completions
        }

