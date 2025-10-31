#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试JSON序列化问题
"""

import json
from batch_execution_scheduler import BatchExecutionScheduler, BatchStatus, BatchExecution
from datetime import datetime

def test_json_serialization():
    """测试JSON序列化"""
    
    # 创建一个BatchExecution实例
    batch_exec = BatchExecution(
        batch_index=1,
        original_start_time=8.0,
        original_duration=2.0,
        status=BatchStatus.PENDING
    )
    
    print("BatchExecution实例创建成功")
    print(f"Status: {batch_exec.status}")
    print(f"Status value: {batch_exec.status.value}")
    print(f"Status type: {type(batch_exec.status)}")
    
    # 测试状态字典
    status_dict = {
        "status": batch_exec.status.value,
        "batch_index": batch_exec.batch_index,
        "original_start_time": batch_exec.original_start_time,
        "created_at": batch_exec.created_at.isoformat()
    }
    
    print("\n状态字典:")
    print(status_dict)
    
    # 尝试JSON序列化
    try:
        json_str = json.dumps(status_dict)
        print(f"\nJSON序列化成功: {json_str}")
    except Exception as e:
        print(f"\nJSON序列化失败: {e}")
        print(f"错误类型: {type(e)}")
        
        # 逐个测试字段
        for key, value in status_dict.items():
            try:
                json.dumps({key: value})
                print(f"  {key}: OK")
            except Exception as field_error:
                print(f"  {key}: 失败 - {field_error} (类型: {type(value)})")

if __name__ == "__main__":
    test_json_serialization()