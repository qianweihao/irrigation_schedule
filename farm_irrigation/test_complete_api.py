#!/usr/bin/env python3
"""
完整的API测试脚本
测试动态执行启动和批次重新生成功能
"""

import requests
import json
import time
from datetime import datetime

# API基础URL
BASE_URL = "http://127.0.0.1:8000"

def test_dynamic_execution_start():
    """测试启动动态执行"""
    print("=== 测试启动动态执行 ===")
    
    # 准备请求数据
    request_data = {
        "plan_file_path": "plan.json",
        "farm_id": "farm_001",
        "execution_mode": "simulation",
        "auto_start": True,
        "enable_plan_regeneration": True,
        "water_level_update_interval_minutes": 5
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/irrigation/dynamic-execution/start",
            json=request_data,
            timeout=10
        )
        
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.text}")
        
        if response.status_code == 200:
            print("✅ 动态执行启动成功")
            return True
        else:
            print(f"❌ 动态执行启动失败: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

def test_dynamic_execution_status():
    """测试获取动态执行状态"""
    print("\n=== 测试获取动态执行状态 ===")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/irrigation/dynamic-execution/status",
            timeout=10
        )
        
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            status_data = response.json()
            print("✅ 状态获取成功")
            print(f"执行状态: {status_data.get('is_running', 'Unknown')}")
            print(f"当前批次: {status_data.get('current_batch_index', 'Unknown')}")
            return status_data
        else:
            print(f"❌ 状态获取失败: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return None

def test_batch_regeneration():
    """测试批次重新生成"""
    print("\n=== 测试批次重新生成 ===")
    
    # 准备测试数据
    request_data = {
        "batch_index": 1,
        "custom_water_levels": {
            "1": 85.0,  # 需要补水
            "2": 80.0,  # 需要补水  
            "3": 120.0  # 水位充足
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/irrigation/dynamic-execution/regenerate-batch",
            json=request_data,
            timeout=10
        )
        
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 批次重新生成成功")
            print(f"成功: {result.get('success', False)}")
            print(f"变更数: {result.get('total_changes', 0)}")
            print(f"影响田块数: {result.get('fields_affected', 0)}")
            
            # 显示变更详情
            changes = result.get('changes', [])
            if changes:
                print("变更详情:")
                for i, change in enumerate(changes, 1):
                    print(f"  {i}. {change}")
            
            return result
        else:
            print(f"❌ 批次重新生成失败: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return None

def test_water_level_summary():
    """测试获取水位摘要"""
    print("\n=== 测试获取水位摘要 ===")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/irrigation/dynamic-execution/water-level-summary",
            timeout=10
        )
        
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            summary = response.json()
            print("✅ 水位摘要获取成功")
            print(f"田块数: {len(summary.get('field_summaries', []))}")
            
            # 显示各田块水位
            for field_summary in summary.get('field_summaries', []):
                field_id = field_summary.get('field_id')
                current_level = field_summary.get('current_water_level_mm')
                target_level = field_summary.get('target_water_level_mm')
                print(f"  田块{field_id}: 当前{current_level}mm, 目标{target_level}mm")
            
            return summary
        else:
            print(f"❌ 水位摘要获取失败: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return None

def main():
    """主测试流程"""
    print("开始完整API测试...")
    
    # 1. 启动动态执行
    if not test_dynamic_execution_start():
        print("动态执行启动失败，跳过后续测试")
        return
    
    # 等待一下让系统初始化
    print("\n等待系统初始化...")
    time.sleep(2)
    
    # 2. 检查执行状态
    status = test_dynamic_execution_status()
    if not status:
        print("无法获取执行状态")
        return
    
    # 3. 获取水位摘要
    water_summary = test_water_level_summary()
    
    # 4. 测试批次重新生成
    regeneration_result = test_batch_regeneration()
    
    # 5. 再次检查状态
    print("\n=== 重新生成后的状态检查 ===")
    final_status = test_dynamic_execution_status()
    
    print("\n=== 测试完成 ===")
    if regeneration_result and regeneration_result.get('success'):
        print("✅ 所有测试通过")
    else:
        print("❌ 部分测试失败")

if __name__ == "__main__":
    main()