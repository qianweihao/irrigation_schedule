#!/usr/bin/env python3
"""
调试执行历史功能
"""

import os
import sys
import sqlite3
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from execution_status_manager import ExecutionStatusManager, ExecutionStatus
from batch_execution_scheduler import BatchExecutionScheduler

def check_database():
    """检查数据库状态"""
    print("=== 检查数据库状态 ===")
    
    db_path = "execution_status.db"
    if os.path.exists(db_path):
        print(f"✅ 数据库文件存在: {db_path}")
        
        # 检查表结构
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            print(f"📊 数据库表: {[table[0] for table in tables]}")
            
            # 检查execution_status表的记录数
            try:
                cursor.execute("SELECT COUNT(*) FROM execution_status")
                count = cursor.fetchone()[0]
                print(f"📈 execution_status表记录数: {count}")
                
                # 显示最近的几条记录
                cursor.execute("SELECT * FROM execution_status ORDER BY created_at DESC LIMIT 3")
                records = cursor.fetchall()
                print(f"📋 最近的记录:")
                for record in records:
                    print(f"   {record}")
                    
            except Exception as e:
                print(f"❌ 查询execution_status表失败: {e}")
                
    else:
        print(f"❌ 数据库文件不存在: {db_path}")

def test_status_manager():
    """测试状态管理器"""
    print("\n=== 测试状态管理器 ===")
    
    try:
        manager = ExecutionStatusManager()
        print("✅ 状态管理器创建成功")
        
        # 测试获取执行历史
        history = manager.get_execution_history(limit=5)
        print(f"📊 执行历史记录数: {len(history)}")
        
        for i, record in enumerate(history):
            print(f"   记录 {i+1}: {record}")
            
    except Exception as e:
        print(f"❌ 状态管理器测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_scheduler():
    """测试调度器"""
    print("\n=== 测试调度器 ===")
    
    try:
        scheduler = BatchExecutionScheduler()
        print("✅ 调度器创建成功")
        
        # 检查是否有get_execution_history方法
        if hasattr(scheduler, 'get_execution_history'):
            print("✅ 调度器有get_execution_history方法")
            
            # 测试获取执行历史
            history = scheduler.get_execution_history(limit=5)
            print(f"📊 调度器执行历史记录数: {len(history)}")
            
            for i, record in enumerate(history):
                print(f"   记录 {i+1}: {record}")
                
        else:
            print("❌ 调度器没有get_execution_history方法")
            
    except Exception as e:
        print(f"❌ 调度器测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_database()
    test_status_manager()
    test_scheduler()