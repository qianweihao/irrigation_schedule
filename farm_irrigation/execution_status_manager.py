"""
执行状态管理和日志记录模块

该模块负责：
1. 管理批次执行状态
2. 记录执行日志
3. 提供状态查询和历史记录
4. 处理异常和错误状态
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, asdict
import sqlite3
import threading
from pathlib import Path

class ExecutionStatus(Enum):
    """执行状态枚举"""
    IDLE = "idle"                    # 空闲
    PREPARING = "preparing"          # 准备中
    RUNNING = "running"              # 运行中
    PAUSED = "paused"               # 暂停
    COMPLETED = "completed"          # 完成
    ERROR = "error"                 # 错误
    CANCELLED = "cancelled"          # 取消

class LogLevel(Enum):
    """日志级别枚举"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class ExecutionLogEntry:
    """执行日志条目"""
    timestamp: datetime
    level: LogLevel
    category: str                   # 日志分类：batch, waterlevel, device, system
    message: str
    details: Optional[Dict[str, Any]] = None
    batch_id: Optional[str] = None
    field_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'level': self.level.value,
            'category': self.category,
            'message': self.message,
            'details': self.details,
            'batch_id': self.batch_id,
            'field_id': self.field_id
        }

@dataclass
class BatchExecutionStatus:
    """批次执行状态"""
    batch_id: str
    status: ExecutionStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    progress: float = 0.0           # 进度百分比 (0-100)
    current_field: Optional[str] = None
    total_fields: int = 0
    completed_fields: int = 0
    error_message: Optional[str] = None
    water_level_update_time: Optional[datetime] = None
    plan_regeneration_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'batch_id': self.batch_id,
            'status': self.status.value,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'progress': self.progress,
            'current_field': self.current_field,
            'total_fields': self.total_fields,
            'completed_fields': self.completed_fields,
            'error_message': self.error_message,
            'water_level_update_time': self.water_level_update_time.isoformat() if self.water_level_update_time else None,
            'plan_regeneration_time': self.plan_regeneration_time.isoformat() if self.plan_regeneration_time else None
        }

class ExecutionStatusManager:
    """执行状态管理器"""
    
    def __init__(self, db_path: str = "execution_status.db", log_path: str = "execution_logs"):
        """
        初始化状态管理器
        
        Args:
            db_path: 数据库文件路径
            log_path: 日志文件目录路径
        """
        self.db_path = db_path
        self.log_path = Path(log_path)
        self.log_path.mkdir(exist_ok=True)
        
        # 当前执行状态
        self.current_status = BatchExecutionStatus(
            batch_id="",
            status=ExecutionStatus.IDLE
        )
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 初始化数据库
        self._init_database()
        
        # 设置日志记录器
        self._setup_logging()
    
    def _init_database(self):
        """初始化数据库"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 创建执行状态表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS execution_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    progress REAL DEFAULT 0.0,
                    current_field TEXT,
                    total_fields INTEGER DEFAULT 0,
                    completed_fields INTEGER DEFAULT 0,
                    error_message TEXT,
                    water_level_update_time TEXT,
                    plan_regeneration_time TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 创建执行日志表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS execution_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    batch_id TEXT,
                    field_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    def _setup_logging(self):
        """设置日志记录器"""
        # 创建日志记录器
        self.logger = logging.getLogger('execution_status')
        self.logger.setLevel(logging.DEBUG)
        
        # 创建文件处理器
        log_file = self.log_path / f"execution_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 创建格式器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # 添加处理器
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def update_status(self, **kwargs):
        """
        更新执行状态
        
        Args:
            **kwargs: 状态字段更新
        """
        with self._lock:
            # 更新当前状态
            for key, value in kwargs.items():
                if hasattr(self.current_status, key):
                    setattr(self.current_status, key, value)
            
            # 保存到数据库
            self._save_status_to_db()
            
            # 记录日志
            self.log_info(
                "status_update",
                f"执行状态更新: {kwargs}",
                details=kwargs
            )
    
    def _save_status_to_db(self):
        """保存状态到数据库"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            status_dict = self.current_status.to_dict()
            cursor.execute('''
                INSERT INTO execution_status (
                    batch_id, status, start_time, end_time, progress,
                    current_field, total_fields, completed_fields,
                    error_message, water_level_update_time, plan_regeneration_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                status_dict['batch_id'],
                status_dict['status'],
                status_dict['start_time'],
                status_dict['end_time'],
                status_dict['progress'],
                status_dict['current_field'],
                status_dict['total_fields'],
                status_dict['completed_fields'],
                status_dict['error_message'],
                status_dict['water_level_update_time'],
                status_dict['plan_regeneration_time']
            ))
            
            conn.commit()
    
    def get_current_status(self) -> Dict[str, Any]:
        """获取当前执行状态"""
        with self._lock:
            return self.current_status.to_dict()
    
    def start_execution(self, batch_id: str, total_fields: int = 0):
        """开始执行"""
        self.update_status(
            batch_id=batch_id,
            status=ExecutionStatus.RUNNING,
            start_time=datetime.now(),
            end_time=None,
            progress=0.0,
            total_fields=total_fields,
            completed_fields=0,
            error_message=None
        )
    
    def complete_execution(self):
        """完成执行"""
        self.update_status(
            status=ExecutionStatus.COMPLETED,
            end_time=datetime.now(),
            progress=100.0
        )
    
    def error_execution(self, error_message: str):
        """执行错误"""
        self.update_status(
            status=ExecutionStatus.ERROR,
            end_time=datetime.now(),
            error_message=error_message
        )
    
    def cancel_execution(self):
        """取消执行"""
        self.update_status(
            status=ExecutionStatus.CANCELLED,
            end_time=datetime.now()
        )
    
    def update_progress(self, completed_fields: int, current_field: Optional[str] = None):
        """更新进度"""
        progress = 0.0
        if self.current_status.total_fields > 0:
            progress = (completed_fields / self.current_status.total_fields) * 100
        
        self.update_status(
            completed_fields=completed_fields,
            current_field=current_field,
            progress=progress
        )
    
    def log_entry(self, level: LogLevel, category: str, message: str, 
                  details: Optional[Dict[str, Any]] = None,
                  batch_id: Optional[str] = None,
                  field_id: Optional[str] = None):
        """记录日志条目"""
        entry = ExecutionLogEntry(
            timestamp=datetime.now(),
            level=level,
            category=category,
            message=message,
            details=details,
            batch_id=batch_id or self.current_status.batch_id,
            field_id=field_id
        )
        
        # 保存到数据库
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO execution_logs (
                    timestamp, level, category, message, details, batch_id, field_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                entry.timestamp.isoformat(),
                entry.level.value,
                entry.category,
                entry.message,
                json.dumps(self._serialize_details(entry.details)) if entry.details else None,
                entry.batch_id,
                entry.field_id
            ))
            conn.commit()
        
        # 记录到文件日志
        log_method = getattr(self.logger, level.value.lower())
        log_method(f"[{category}] {message}")
    
    def _serialize_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """安全地序列化details字典，处理枚举类型和datetime对象"""
        if not details:
            return details
            
        serialized = {}
        for key, value in details.items():
            if hasattr(value, 'value'):  # 枚举类型
                serialized[key] = value.value
            elif isinstance(value, datetime):  # datetime对象
                serialized[key] = value.isoformat()
            elif isinstance(value, dict):
                serialized[key] = self._serialize_details(value)
            elif isinstance(value, list):
                serialized[key] = [
                    item.value if hasattr(item, 'value') else 
                    item.isoformat() if isinstance(item, datetime) else item
                    for item in value
                ]
            else:
                serialized[key] = value
        return serialized
    
    def log_debug(self, category: str, message: str, **kwargs):
        """记录调试日志"""
        self.log_entry(LogLevel.DEBUG, category, message, **kwargs)
    
    def log_info(self, category: str, message: str, **kwargs):
        """记录信息日志"""
        self.log_entry(LogLevel.INFO, category, message, **kwargs)
    
    def log_warning(self, category: str, message: str, **kwargs):
        """记录警告日志"""
        self.log_entry(LogLevel.WARNING, category, message, **kwargs)
    
    def log_error(self, category: str, message: str, **kwargs):
        """记录错误日志"""
        self.log_entry(LogLevel.ERROR, category, message, **kwargs)
    
    def log_critical(self, category: str, message: str, **kwargs):
        """记录严重错误日志"""
        self.log_entry(LogLevel.CRITICAL, category, message, **kwargs)
    
    def get_execution_history(self, limit: int = 50, offset: int = 0,
                            batch_id: Optional[str] = None,
                            start_date: Optional[datetime] = None,
                            end_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """获取执行历史"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM execution_status WHERE 1=1"
            params = []
            
            if batch_id:
                query += " AND batch_id = ?"
                params.append(batch_id)
            
            if start_date:
                query += " AND created_at >= ?"
                params.append(start_date.isoformat())
            
            if end_date:
                query += " AND created_at <= ?"
                params.append(end_date.isoformat())
            
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    def get_logs(self, limit: int = 100, offset: int = 0,
                 level: Optional[LogLevel] = None,
                 category: Optional[str] = None,
                 batch_id: Optional[str] = None,
                 field_id: Optional[str] = None,
                 start_date: Optional[datetime] = None,
                 end_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """获取日志记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM execution_logs WHERE 1=1"
            params = []
            
            if level:
                query += " AND level = ?"
                params.append(level.value)
            
            if category:
                query += " AND category = ?"
                params.append(category)
            
            if batch_id:
                query += " AND batch_id = ?"
                params.append(batch_id)
            
            if field_id:
                query += " AND field_id = ?"
                params.append(field_id)
            
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date.isoformat())
            
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date.isoformat())
            
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            columns = [desc[0] for desc in cursor.description]
            logs = []
            for row in rows:
                log_dict = dict(zip(columns, row))
                if log_dict['details']:
                    log_dict['details'] = json.loads(log_dict['details'])
                logs.append(log_dict)
            
            return logs
    
    def cleanup_old_records(self, days: int = 30):
        """清理旧记录"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 清理旧的执行状态记录
            cursor.execute(
                "DELETE FROM execution_status WHERE created_at < ?",
                (cutoff_date.isoformat(),)
            )
            
            # 清理旧的日志记录
            cursor.execute(
                "DELETE FROM execution_logs WHERE created_at < ?",
                (cutoff_date.isoformat(),)
            )
            
            conn.commit()
        
        self.log_info("system", f"清理了 {days} 天前的旧记录")

# 全局状态管理器实例
_status_manager = None

def get_status_manager() -> ExecutionStatusManager:
    """获取全局状态管理器实例"""
    global _status_manager
    if _status_manager is None:
        _status_manager = ExecutionStatusManager()
    return _status_manager

# 示例使用
if __name__ == "__main__":
    # 创建状态管理器
    manager = ExecutionStatusManager()
    
    # 开始执行
    manager.start_execution("batch_001", total_fields=5)
    
    # 记录日志
    manager.log_info("batch", "开始执行批次 batch_001")
    
    # 更新进度
    manager.update_progress(1, "field_001")
    manager.log_info("field", "完成田块 field_001 的灌溉")
    
    # 模拟错误
    manager.log_error("device", "水泵启动失败", details={"pump_id": "pump_001", "error_code": "E001"})
    
    # 完成执行
    manager.complete_execution()
    manager.log_info("batch", "批次执行完成")
    
    # 查询状态和日志
    print("当前状态:", manager.get_current_status())
    print("执行历史:", manager.get_execution_history(limit=5))
    print("最近日志:", manager.get_logs(limit=10))