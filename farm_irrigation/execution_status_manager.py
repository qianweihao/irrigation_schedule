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
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from dataclasses import dataclass, asdict
import sqlite3
import threading
from pathlib import Path

# 配置日志
logger = logging.getLogger(__name__)

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
    farm_id: str
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
            'farm_id': self.farm_id,
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
            farm_id="",
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
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 创建执行状态表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS execution_status (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        farm_id TEXT NOT NULL,
                        batch_index INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        start_time TEXT,
                        end_time TEXT,
                        progress REAL DEFAULT 0.0,
                        total_batches INTEGER DEFAULT 0,
                        current_batch INTEGER DEFAULT 0,
                        error_message TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(farm_id, batch_index)
                    )
                ''')
                
                # 创建执行日志表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS execution_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        farm_id TEXT NOT NULL,
                        batch_index INTEGER,
                        level TEXT NOT NULL,
                        category TEXT NOT NULL,
                        message TEXT NOT NULL,
                        details TEXT,
                        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                        source TEXT,
                        batch_id TEXT,
                        field_id TEXT
                    )
                ''')
                
                # 创建批次详情表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS batch_details (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        farm_id TEXT NOT NULL,
                        batch_index INTEGER NOT NULL,
                        field_id TEXT NOT NULL,
                        command_type TEXT NOT NULL,
                        duration_minutes REAL,
                        flow_rate_lps REAL,
                        water_amount_m3 REAL,
                        start_time_h REAL,
                        end_time_h REAL,
                        status TEXT DEFAULT 'pending',
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                conn.commit()
                logger.info("数据库初始化完成")
                
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise
    
    def _setup_logging(self):
        """设置日志记录"""
        try:
            # 设置实例logger
            self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
            
            # 确保日志目录存在
            log_dir = os.path.dirname(self.log_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            # 配置文件日志处理器
            file_handler = logging.FileHandler(self.log_path, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # 设置日志格式
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(formatter)
            
            # 添加到logger
            self.logger.addHandler(file_handler)
            
            self.logger.info("日志系统初始化完成")
            
        except Exception as e:
            print(f"日志系统初始化失败: {e}")
            # 设置一个基本的logger以防出错
            self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def update_execution_status(self, 
                              farm_id: str, 
                              batch_index: int, 
                              status: ExecutionStatus,
                              progress: float = None,
                              total_batches: int = None,
                              current_batch: int = None,
                              error_message: str = None):
        """更新执行状态"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 检查记录是否存在
                cursor.execute('''
                    SELECT id FROM execution_status 
                    WHERE farm_id = ? AND batch_index = ?
                ''', (farm_id, batch_index))
                
                existing = cursor.fetchone()
                
                if existing:
                    # 更新现有记录
                    update_fields = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
                    update_values = [status.value]
                    
                    if progress is not None:
                        update_fields.append("progress = ?")
                        update_values.append(progress)
                    
                    if total_batches is not None:
                        update_fields.append("total_batches = ?")
                        update_values.append(total_batches)
                    
                    if current_batch is not None:
                        update_fields.append("current_batch = ?")
                        update_values.append(current_batch)
                    
                    if error_message is not None:
                        update_fields.append("error_message = ?")
                        update_values.append(error_message)
                    
                    if status == ExecutionStatus.RUNNING and progress is None:
                        # 如果开始执行但没有指定进度，设置开始时间
                        update_fields.append("start_time = CURRENT_TIMESTAMP")
                    elif status in [ExecutionStatus.COMPLETED, ExecutionStatus.ERROR, ExecutionStatus.CANCELLED]:
                        # 如果执行结束，设置结束时间
                        update_fields.append("end_time = CURRENT_TIMESTAMP")
                    
                    update_values.extend([farm_id, batch_index])
                    
                    cursor.execute(f'''
                        UPDATE execution_status 
                        SET {", ".join(update_fields)}
                        WHERE farm_id = ? AND batch_index = ?
                    ''', update_values)
                    
                else:
                    # 插入新记录
                    start_time = "CURRENT_TIMESTAMP" if status == ExecutionStatus.RUNNING else None
                    
                    cursor.execute('''
                        INSERT INTO execution_status 
                        (farm_id, batch_index, status, progress, total_batches, current_batch, 
                         error_message, start_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (farm_id, batch_index, status.value, progress or 0.0, 
                          total_batches or 0, current_batch or 0, error_message, start_time))
                
                conn.commit()
                
                # 记录状态变更日志
                self.log_event(
                    farm_id=farm_id,
                    batch_index=batch_index,
                    level=LogLevel.INFO,
                    message=f"执行状态更新为: {status.value}",
                    details=f"进度: {progress}, 错误: {error_message}" if progress or error_message else None
                )
                
        except Exception as e:
            logger.error(f"更新执行状态失败: {e}")
            raise
    
    def get_execution_status(self, farm_id: str, batch_index: int = None) -> Union[BatchExecutionStatus, List[BatchExecutionStatus]]:
        """获取执行状态"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                if batch_index is not None:
                    # 获取特定批次状态
                    cursor.execute('''
                        SELECT farm_id, batch_index, status, start_time, end_time, 
                               progress, total_batches, current_batch, error_message,
                               created_at, updated_at
                        FROM execution_status 
                        WHERE farm_id = ? AND batch_index = ?
                    ''', (farm_id, batch_index))
                    
                    row = cursor.fetchone()
                    if row:
                        return self._row_to_batch_status(row)
                    else:
                        return None
                else:
                    # 获取所有批次状态
                    cursor.execute('''
                        SELECT farm_id, batch_index, status, start_time, end_time, 
                               progress, total_batches, current_batch, error_message,
                               created_at, updated_at
                        FROM execution_status 
                        WHERE farm_id = ?
                        ORDER BY batch_index
                    ''', (farm_id,))
                    
                    rows = cursor.fetchall()
                    return [self._row_to_batch_status(row) for row in rows]
                    
        except Exception as e:
            logger.error(f"获取执行状态失败: {e}")
            return [] if batch_index is None else None
    
    def _row_to_batch_status(self, row) -> BatchExecutionStatus:
        """将数据库行转换为BatchExecutionStatus对象"""
        def parse_datetime(dt_str):
            """解析日期时间字符串"""
            if not dt_str:
                return None
            try:
                # 尝试ISO格式
                return datetime.fromisoformat(dt_str)
            except ValueError:
                try:
                    # 尝试SQLite的CURRENT_TIMESTAMP格式 (YYYY-MM-DD HH:MM:SS)
                    return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    # 如果都失败，返回当前时间
                    return datetime.now()
        
        return BatchExecutionStatus(
            batch_id=f"{row[0]}_{row[1]}",  # 组合farm_id和batch_index作为batch_id
            farm_id=row[0],  # farm_id
            status=ExecutionStatus(row[2]),
            start_time=parse_datetime(row[3]),
            end_time=parse_datetime(row[4]),
            progress=row[5] or 0.0,
            error_message=row[8]
            # 注意：忽略total_batches, current_batch, created_at, updated_at字段
            # 因为BatchExecutionStatus没有这些字段
        )
    
    def log_event(self, 
                  farm_id: str, 
                  level: LogLevel, 
                  message: str,
                  batch_index: int = None,
                  details: str = None,
                  source: str = None):
        """记录事件日志"""
        try:
            # 数据库日志
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO execution_logs 
                    (farm_id, batch_index, level, message, details, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (farm_id, batch_index, level.value, message, details, source))
                conn.commit()
            
            # 文件日志
            log_entry = ExecutionLogEntry(
                timestamp=datetime.now(),
                level=level,
                category=source or "system",  # 使用source作为category
                message=message,
                details={"farm_id": farm_id} if farm_id else None,  # 将farm_id放在details中
                batch_id=str(batch_index) if batch_index is not None else None  # 转换为字符串
            )
            
            log_message = f"[{farm_id}]"
            if batch_index is not None:
                log_message += f"[批次{batch_index}]"
            log_message += f" {message}"
            if details:
                log_message += f" - {details}"
            
            if level == LogLevel.ERROR:
                logger.error(log_message)
            elif level == LogLevel.WARNING:
                logger.warning(log_message)
            elif level == LogLevel.INFO:
                logger.info(log_message)
            else:
                logger.debug(log_message)
                
        except Exception as e:
            logger.error(f"记录事件日志失败: {e}")
    
    def get_execution_logs(self, 
                          farm_id: str, 
                          batch_index: int = None,
                          level: LogLevel = None,
                          limit: int = 100,
                          offset: int = 0) -> List[ExecutionLogEntry]:
        """获取执行日志"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 构建查询条件
                conditions = ["farm_id = ?"]
                params = [farm_id]
                
                if batch_index is not None:
                    conditions.append("batch_index = ?")
                    params.append(batch_index)
                
                if level is not None:
                    conditions.append("level = ?")
                    params.append(level.value)
                
                # 添加分页参数
                params.extend([limit, offset])
                
                query = f'''
                    SELECT farm_id, batch_index, level, message, details, 
                           timestamp, source
                    FROM execution_logs 
                    WHERE {" AND ".join(conditions)}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                '''
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                logs = []
                for row in rows:
                    # 解析时间戳
                    try:
                        timestamp = datetime.fromisoformat(row[5])
                    except ValueError:
                        try:
                            timestamp = datetime.strptime(row[5], '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            timestamp = datetime.now()
                    
                    log_entry = ExecutionLogEntry(
                        timestamp=timestamp,
                        level=LogLevel(row[2]),
                        category=row[6] or "system",  # 使用source作为category
                        message=row[3],
                        details={"farm_id": row[0]} if row[0] else None,  # 将farm_id放在details中
                        batch_id=str(row[1]) if row[1] is not None else None  # 转换为字符串
                    )
                    logs.append(log_entry)
                
                return logs
                
        except Exception as e:
            logger.error(f"获取执行日志失败: {e}")
            return []
    
    def save_batch_details(self, 
                          farm_id: str, 
                          batch_index: int, 
                          commands: List[Dict[str, Any]]):
        """保存批次详情"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 先删除现有的批次详情
                cursor.execute('''
                    DELETE FROM batch_details 
                    WHERE farm_id = ? AND batch_index = ?
                ''', (farm_id, batch_index))
                
                # 插入新的批次详情
                for command in commands:
                    cursor.execute('''
                        INSERT INTO batch_details 
                        (farm_id, batch_index, field_id, command_type, 
                         duration_minutes, flow_rate_lps, water_amount_m3,
                         start_time_h, end_time_h)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        farm_id, batch_index, 
                        command.get("field_id", ""),
                        command.get("command_type", "irrigation"),
                        command.get("duration_minutes", 0),
                        command.get("flow_rate_lps", 0),
                        command.get("water_amount_m3", 0),
                        command.get("start_time_h", 0),
                        command.get("end_time_h", 0)
                    ))
                
                conn.commit()
                
                self.log_event(
                    farm_id=farm_id,
                    batch_index=batch_index,
                    level=LogLevel.INFO,
                    message=f"保存批次详情，共 {len(commands)} 个命令"
                )
                
        except Exception as e:
            logger.error(f"保存批次详情失败: {e}")
            raise
    
    def get_batch_details(self, farm_id: str, batch_index: int) -> List[Dict[str, Any]]:
        """获取批次详情"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT field_id, command_type, duration_minutes, 
                           flow_rate_lps, water_amount_m3, start_time_h, 
                           end_time_h, status, created_at, updated_at
                    FROM batch_details 
                    WHERE farm_id = ? AND batch_index = ?
                    ORDER BY field_id
                ''', (farm_id, batch_index))
                
                rows = cursor.fetchall()
                
                details = []
                for row in rows:
                    detail = {
                        "field_id": row[0],
                        "command_type": row[1],
                        "duration_minutes": row[2],
                        "flow_rate_lps": row[3],
                        "water_amount_m3": row[4],
                        "start_time_h": row[5],
                        "end_time_h": row[6],
                        "status": row[7],
                        "created_at": row[8],
                        "updated_at": row[9]
                    }
                    details.append(detail)
                
                return details
                
        except Exception as e:
            logger.error(f"获取批次详情失败: {e}")
            return []
    
    def update_batch_command_status(self, 
                                   farm_id: str, 
                                   batch_index: int, 
                                   field_id: str, 
                                   status: str):
        """更新批次命令状态"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE batch_details 
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE farm_id = ? AND batch_index = ? AND field_id = ?
                ''', (status, farm_id, batch_index, field_id))
                
                conn.commit()
                
                if cursor.rowcount > 0:
                    self.log_event(
                        farm_id=farm_id,
                        batch_index=batch_index,
                        level=LogLevel.INFO,
                        message=f"田块 {field_id} 命令状态更新为: {status}"
                    )
                
        except Exception as e:
            logger.error(f"更新批次命令状态失败: {e}")
    
    def get_execution_summary(self, farm_id: str) -> Dict[str, Any]:
        """获取执行摘要"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 获取总体统计
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_batches,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_batches,
                        SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running_batches,
                        SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_batches,
                        AVG(progress) as avg_progress
                    FROM execution_status 
                    WHERE farm_id = ?
                ''', (farm_id,))
                
                stats = cursor.fetchone()
                
                # 获取最近的日志
                cursor.execute('''
                    SELECT level, message, timestamp
                    FROM execution_logs 
                    WHERE farm_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 10
                ''', (farm_id,))
                
                recent_logs = cursor.fetchall()
                
                summary = {
                    "farm_id": farm_id,
                    "total_batches": stats[0] or 0,
                    "completed_batches": stats[1] or 0,
                    "running_batches": stats[2] or 0,
                    "error_batches": stats[3] or 0,
                    "avg_progress": stats[4] or 0.0,
                    "recent_logs": [
                        {
                            "level": log[0],
                            "message": log[1],
                            "timestamp": log[2]
                        } for log in recent_logs
                    ]
                }
                
                return summary
                
        except Exception as e:
            logger.error(f"获取执行摘要失败: {e}")
            return {"farm_id": farm_id, "error": str(e)}
    
    def cleanup_old_data(self, days_to_keep: int = 30):
        """清理旧数据"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            cutoff_str = cutoff_date.isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 清理旧的执行日志
                cursor.execute('''
                    DELETE FROM execution_logs 
                    WHERE timestamp < ?
                ''', (cutoff_str,))
                
                logs_deleted = cursor.rowcount
                
                # 清理已完成的旧执行状态
                cursor.execute('''
                    DELETE FROM execution_status 
                    WHERE updated_at < ? AND status IN ('completed', 'error', 'cancelled')
                ''', (cutoff_str,))
                
                status_deleted = cursor.rowcount
                
                # 清理对应的批次详情
                cursor.execute('''
                    DELETE FROM batch_details 
                    WHERE created_at < ?
                ''', (cutoff_str,))
                
                details_deleted = cursor.rowcount
                
                conn.commit()
                
                logger.info(f"数据清理完成: 删除 {logs_deleted} 条日志, {status_deleted} 条状态, {details_deleted} 条详情")
                
        except Exception as e:
            logger.error(f"清理旧数据失败: {e}")
    
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
                    farm_id, timestamp, level, category, message, details, batch_id, field_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.current_status.farm_id,
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