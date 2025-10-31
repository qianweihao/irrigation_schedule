#!/usr/bin/env python3
"""
批次重新生成功能测试脚本
"""

import json
import requests
from datetime import datetime
from typing import Dict, Any

def test_batch_regeneration():
    """测试批次重新生成功能"""
    base_url = "http://127.0.0.1:8000"
    
    print("=== 批次重新生成功能测试 ===")
    
    # 1. 首先创建一个模拟的调度器状态
    print("1. 创建模拟调度器状态...")
    
    # 直接测试批次重新生成API，看看错误信息
    print("2. 测试批次重新生成API...")
    
    regeneration_request = {
        "batch_index": 1,
        "custom_water_levels": {
            "1": 120.0,
            "2": 110.0,
            "3": 105.0
        }
    }
    
    try:
        response = requests.post(
            f"{base_url}/api/irrigation/dynamic-execution/regenerate-batch",
            json=regeneration_request,
            timeout=30
        )
        
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 批次重新生成成功!")
            print(f"批次索引: {result.get('batch_index')}")
            print(f"变更数量: {result.get('changes_count')}")
            print(f"变更摘要: {result.get('change_summary')}")
        elif response.status_code == 404:
            print("❌ 没有找到当前执行计划")
            print("需要先启动动态执行或创建计划")
        else:
            print(f"❌ 批次重新生成失败: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ 请求失败: {e}")
    
    # 3. 测试其他相关API
    print("\n3. 测试相关API...")
    
    # 测试执行状态
    try:
        status_response = requests.get(f"{base_url}/api/irrigation/dynamic-execution/status")
        print(f"执行状态: {status_response.status_code} - {status_response.text[:200]}")
    except Exception as e:
        print(f"获取执行状态失败: {e}")
    
    # 测试水位摘要
    try:
        wl_response = requests.get(f"{base_url}/api/irrigation/dynamic-execution/waterlevel-summary")
        print(f"水位摘要: {wl_response.status_code} - {wl_response.text[:200]}")
    except Exception as e:
        print(f"获取水位摘要失败: {e}")

if __name__ == "__main__":
    test_batch_regeneration()