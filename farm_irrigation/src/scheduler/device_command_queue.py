#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备指令队列管理器

功能：
- 管理所有设备控制指令
- 跟踪指令状态（待执行、已发送、已执行）
- 提供指令查询接口
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DeviceCommand:
    """设备控制指令"""
    command_id: str
    device_type: str  # "pump" | "regulator" | "field_inlet_gate" | "field_outlet_gate"
    device_id: str
    unique_no: Optional[str]
    action: str  # "start" | "stop" | "open" | "close" | "set"
    params: Dict
    priority: int
    phase: str  # "start" | "running" | "stop"
    description: str
    status: str = "pending"  # "pending" | "sent" | "executed" | "failed"
    reason: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    sent_at: Optional[str] = None
    updated_at: Optional[str] = None
    feedback_message: Optional[str] = None


class DeviceCommandQueue:
    """设备指令队列管理器"""
    
    def __init__(self):
        """初始化指令队列"""
        self.commands: List[DeviceCommand] = []
        self.command_counter = 0
    
    def add_command(self, command_data: Dict) -> str:
        """
        添加新指令到队列（带去重机制，防止重复指令）
        
        Args:
            command_data: 指令数据字典
        
        Returns:
            str: 生成的command_id（如果已存在则返回现有ID）
        """
        # 生成指令指纹（设备ID + 动作 + 阶段）
        fingerprint = f"{command_data['device_id']}:{command_data['action']}:{command_data.get('phase', 'running')}"
        
        # 检查是否已存在相同的待执行指令
        for cmd in self.commands:
            if cmd.status in ['pending', 'sent']:
                cmd_fingerprint = f"{cmd.device_id}:{cmd.action}:{cmd.phase}"
                if cmd_fingerprint == fingerprint:
                    logger.debug(f"跳过重复指令: {command_data.get('description', fingerprint)}")
                    return cmd.command_id  # 返回已存在的指令ID
        
        # 不存在重复，添加新指令
        self.command_counter += 1
        command_id = f"cmd_{self.command_counter:04d}"
        
        command = DeviceCommand(
            command_id=command_id,
            device_type=command_data['device_type'],
            device_id=command_data['device_id'],
            unique_no=command_data.get('unique_no'),
            action=command_data['action'],
            params=command_data.get('params', {}),
            priority=command_data.get('priority', 5),
            phase=command_data.get('phase', 'running'),
            description=command_data.get('description', ''),
            reason=command_data.get('reason')
        )
        
        self.commands.append(command)
        logger.info(f"添加指令: {command_id} - {command.description}")
        
        return command_id
    
    def get_commands(self, 
                     phase: Optional[str] = None,
                     status: Optional[str] = None,
                     device_type: Optional[str] = None) -> List[Dict]:
        """
        获取指令列表
        
        Args:
            phase: 阶段筛选 ("start" | "running" | "stop")
            status: 状态筛选 ("pending" | "sent" | "executed" | "failed")
            device_type: 设备类型筛选
        
        Returns:
            List[Dict]: 指令列表
        """
        filtered_commands = self.commands
        
        if phase:
            filtered_commands = [c for c in filtered_commands if c.phase == phase]
        
        if status:
            filtered_commands = [c for c in filtered_commands if c.status == status]
        
        if device_type:
            filtered_commands = [c for c in filtered_commands if c.device_type == device_type]
        
        # 转换为字典格式
        return [self._command_to_dict(cmd) for cmd in filtered_commands]
    
    def get_pending_commands(self, phase: Optional[str] = None) -> List[Dict]:
        """获取待执行指令"""
        return self.get_commands(phase=phase, status='pending')
    
    def mark_as_sent(self, command_id: str) -> bool:
        """
        标记指令已发送
        
        Args:
            command_id: 指令ID
        
        Returns:
            bool: 是否成功
        """
        for cmd in self.commands:
            if cmd.command_id == command_id:
                cmd.status = 'sent'
                cmd.sent_at = datetime.now().isoformat()
                logger.debug(f"指令已发送: {command_id}")
                return True
        return False
    
    def update_command_status(self, 
                             command_id: str,
                             status: str,
                             message: Optional[str] = None) -> bool:
        """
        更新指令状态（接收硬件团队反馈）
        
        Args:
            command_id: 指令ID
            status: 新状态
            message: 反馈消息
        
        Returns:
            bool: 是否成功
        """
        for cmd in self.commands:
            if cmd.command_id == command_id:
                old_status = cmd.status
                cmd.status = status
                cmd.updated_at = datetime.now().isoformat()
                
                if message:
                    cmd.feedback_message = message
                
                logger.info(f"指令状态更新: {command_id} {old_status} → {status}")
                
                if message:
                    logger.info(f"  反馈: {message}")
                
                return True
        
        logger.warning(f"指令不存在: {command_id}")
        return False
    
    def get_statistics(self) -> Dict:
        """获取指令统计信息"""
        total = len(self.commands)
        pending = sum(1 for c in self.commands if c.status == 'pending')
        sent = sum(1 for c in self.commands if c.status == 'sent')
        executed = sum(1 for c in self.commands if c.status == 'executed')
        failed = sum(1 for c in self.commands if c.status == 'failed')
        
        return {
            'total_commands': total,
            'pending': pending,
            'sent': sent,
            'executed': executed,
            'failed': failed
        }
    
    def clear(self):
        """清空所有指令"""
        self.commands.clear()
        self.command_counter = 0
        logger.info("指令队列已清空")
    
    def _command_to_dict(self, cmd: DeviceCommand) -> Dict:
        """将指令对象转换为字典"""
        return {
            'command_id': cmd.command_id,
            'device_type': cmd.device_type,
            'device_id': cmd.device_id,
            'unique_no': cmd.unique_no,
            'action': cmd.action,
            'params': cmd.params,
            'priority': cmd.priority,
            'phase': cmd.phase,
            'description': cmd.description,
            'status': cmd.status,
            'reason': cmd.reason,
            'created_at': cmd.created_at,
            'sent_at': cmd.sent_at,
            'updated_at': cmd.updated_at,
            'feedback_message': cmd.feedback_message
        }
    
    def cleanup_old_commands(self, retention_hours: int = 24) -> int:
        """
        清理旧指令，防止内存无限增长
        
        保留策略：
        1. 所有 pending/sent 状态的指令（待执行）
        2. 最近N小时内的 executed/failed 指令（用于查询历史）
        
        Args:
            retention_hours: 保留时间（小时），默认24小时
            
        Returns:
            int: 清理的指令数量
        """
        from datetime import datetime, timedelta
        
        original_count = len(self.commands)
        cutoff_time = datetime.now() - timedelta(hours=retention_hours)
        
        # 保留策略
        self.commands = [
            cmd for cmd in self.commands
            if cmd.status in ['pending', 'sent'] or  # 待执行的指令
               datetime.fromisoformat(cmd.created_at) > cutoff_time  # 最近的历史
        ]
        
        cleaned_count = original_count - len(self.commands)
        if cleaned_count > 0:
            logger.info(f"清理了 {cleaned_count} 条旧指令，当前保留 {len(self.commands)} 条")
        
        return cleaned_count

