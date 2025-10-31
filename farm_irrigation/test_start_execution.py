#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试启动执行功能
"""

import requests
import json

def test_start_execution():
    """测试启动执行端点"""
    url = "http://127.0.0.1:8000/api/irrigation/dynamic-execution/start"
    
    # 准备请求数据
    data = {
        "plan_file_path": "export/20250820_151007/plan.json",
        "farm_id": "test_farm_001",
        "config_file_path": "config.json",
        "water_level_update_interval_minutes": 30,
        "enable_plan_regeneration": True,
        "execution_mode": "automatic"
    }
    
    try:
        print(f"发送POST请求到: {url}")
        print(f"请求数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        response = requests.post(url, json=data, timeout=30)
        
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 启动执行成功")
            print(f"执行ID: {result.get('execution_id')}")
            print(f"调度器状态: {result.get('scheduler_status')}")
        else:
            print(f"❌ 启动执行失败: {response.status_code}")
            try:
                error_detail = response.json()
                print(f"错误详情: {error_detail}")
            except:
                print(f"错误响应: {response.text}")
                
    except Exception as e:
        print(f"❌ 请求异常: {str(e)}")

if __name__ == "__main__":
    test_start_execution()